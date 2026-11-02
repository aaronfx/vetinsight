from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from uuid import uuid4
from zipfile import ZipFile

from fastapi import HTTPException
import httpx

from app.cloud_config import CloudSettings
from app.object_storage import ObjectStorage
from tests import test_api
from tests.test_annotations import image_bytes
from tests.test_documents import pdf_bytes


class CloudStorageTests(unittest.TestCase):
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def setUp(self):
        test_api.ApiTests.setUp(self)
        self.objects = {}
        self.fail_upload = False
        self.public = False
        self.calls = []
        settings = CloudSettings('', 'supabase', 'https://fixture.supabase.co', 'sb_secret_test_fixture')
        self.main.STORE = ObjectStorage(Path(self.temp.name), settings, transport=httpx.MockTransport(self.handle))

    def handle(self, request):
        self.calls.append(request)
        self.assertEqual(request.headers['apikey'], 'sb_secret_test_fixture')
        self.assertNotIn('authorization', request.headers)
        path = request.url.path
        if '/bucket/' in path:
            return httpx.Response(200, json={'public': self.public})
        if request.method == 'POST':
            if self.fail_upload:
                return httpx.Response(503)
            key = path.split('/records/')[1]
            if key in self.objects:
                return httpx.Response(400)
            self.assertEqual(request.headers['x-upsert'], 'false')
            self.objects[key] = request.read()
            return httpx.Response(200, json={'Key': key})
        if request.method == 'DELETE':
            for prefix in json.loads(request.read())['prefixes']:
                self.objects.pop(prefix.split('/')[-1], None)
            return httpx.Response(200, json=[])
        self.assertIn('/object/authenticated/', path)
        key = path.split('/records/')[1]
        if key not in self.objects:
            return httpx.Response(404)
        return httpx.Response(200, content=self.objects[key])

    def test_private_originals_previews_text_and_temporary_cleanup(self):
        case_id = self.create()
        content = pdf_bytes(['Private fictional document'])
        response = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('private.pdf', content, 'application/pdf')})
        self.assertEqual(response.status_code, 201, response.text)
        info = response.json()
        for endpoint, disposition in [('preview_url', 'inline'), ('download_url', 'attachment')]:
            response = self.client.get(info[endpoint])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, content)
            self.assertIn(disposition, response.headers['content-disposition'])
            self.assertNotIn('supabase.co', response.text)
        self.assertIn('Private fictional document', self.client.get(info['text_url']).json()['pages'][0]['text'])
        with self.main.stored_record(case_id, info['id']) as (_, path):
            temporary = path
            self.assertTrue(path.exists())
        self.assertFalse(temporary.exists())
        self.assertEqual(list((Path(self.temp.name) / 'uploads').iterdir()), [])
        self.client.cookies.clear()
        self.assertEqual(self.client.get(info['download_url']).status_code, 401)

    def test_remote_annotation_and_coco_export_preserve_source(self):
        case_id = self.create()
        content = image_bytes()
        info = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('shape.png', content, 'image/png')}).json()
        payload = {'revision': 0, 'review_status': 'Reviewed', 'annotations': [
            {'id': str(uuid4()), 'x': .1, 'y': .2, 'width': .3, 'height': .4, 'category': 'Geometry', 'review_status': 'Reviewed', 'notes': 'Test fixture'}]}
        self.assertEqual(self.client.put(f'/cases/{case_id}/uploads/{info["id"]}/annotations', json=payload).status_code, 200)
        response = self.client.get(f'/cases/{case_id}/exports/coco')
        self.assertEqual(response.status_code, 200, response.text[:100] if response.status_code != 200 else '')
        with ZipFile(BytesIO(response.content)) as archive:
            coco = json.loads(archive.read('annotations.json'))
            self.assertEqual(coco['annotations'][0]['bbox'], [100, 100, 300, 200])
        self.assertEqual(next(iter(self.objects.values())), content)

    def test_failed_upload_and_database_failure_do_not_leave_metadata(self):
        case_id = self.create()
        self.fail_upload = True
        response = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('shape.png', image_bytes(), 'image/png')})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get(f'/cases/{case_id}').json()['uploads'], [])
        self.fail_upload = False
        with patch('app.security.audit', side_effect=RuntimeError('simulated database failure')):
            with self.assertRaises(Exception):
                self.client.post(f'/cases/{case_id}/uploads', files={'file': ('shape.png', image_bytes(), 'image/png')})
        self.assertEqual(self.objects, {})
        self.assertEqual(self.client.get(f'/cases/{case_id}').json()['uploads'], [])

    def test_public_bucket_and_missing_object_fail_closed(self):
        self.public = True
        with self.assertRaises(HTTPException) as failure:
            self.main.STORE.ensure_private_bucket()
        self.assertEqual(failure.exception.status_code, 503)
        self.public = False
        case_id = self.create()
        info = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('shape.png', image_bytes(), 'image/png')}).json()
        self.objects.clear()
        self.assertEqual(self.client.get(info['preview_url']).status_code, 404)
        self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/{info["id"]}/annotations').status_code, 404)
