import importlib
from io import BytesIO
from pathlib import Path
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from tests import test_api
from tests.auth_helpers import sign_in


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (1000, 500), '#dde5ee').save(output, 'PNG')
    return output.getvalue()


class AnnotationTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def attach_image(self):
        case_id = self.create()
        content = image_bytes()
        response = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('geometry.png', content, 'image/png')})
        self.assertEqual(response.status_code, 201)
        return case_id, response.json(), content

    def payload(self):
        return {'revision': 0, 'review_status': 'In Progress', 'annotations': [
            {'id': str(uuid4()), 'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.4,
             'category': 'Unclassified', 'review_status': 'Needs Review', 'notes': 'Manual region'}]}

    def test_annotations_survive_restart_and_leave_records_unchanged(self):
        case_id, upload, content = self.attach_image()
        path = f'/cases/{case_id}/uploads/{upload["id"]}/annotations'
        initial = self.client.get(path).json()
        self.assertEqual((initial['image_width'], initial['image_height']), (1000, 500))
        self.assertEqual(initial['annotations'], [])
        self.assertEqual(initial['revision'], 0)
        case = self.client.get(f'/cases/{case_id}').json()
        payload = self.payload()
        response = self.client.put(path, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['annotations'], payload['annotations'])
        self.assertEqual(self.client.get(f'/cases/{case_id}').json(), case)
        self.assertEqual(self.client.get(upload['download_url']).content, content)
        self.client.__exit__(None, None, None)
        self.main = importlib.reload(self.main)
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        sign_in(self.client)
        self.assertEqual(self.client.get(path).json(), saved)
        self.assertEqual(self.client.get('/dashboard').json()['needs_review_count'], 1)
        edited = {**payload, 'revision': 1, 'review_status': 'Reviewed', 'annotations': [{**payload['annotations'][0], 'category': 'Custom category', 'review_status': 'Reviewed'}]}
        self.assertEqual(self.client.put(path, json=edited).status_code, 200)
        self.assertEqual(self.client.get(path).json()['annotations'][0]['category'], 'Custom category')
        self.assertEqual(self.client.put(path, json=payload).status_code, 409)
        self.assertEqual(self.client.get(path).json()['revision'], 2)
        self.assertEqual(self.client.get('/dashboard').json()['needs_review_count'], 0)
        deleted = {**edited, 'revision': 2, 'annotations': []}
        self.assertEqual(self.client.put(path, json=deleted).status_code, 200)
        self.assertEqual(self.client.get(path).json()['annotations'], [])

    def test_coordinate_validation_and_review_status(self):
        case_id, upload, _ = self.attach_image()
        path = f'/cases/{case_id}/uploads/{upload["id"]}/annotations'
        for fields in [{'x': -0.1}, {'y': 1.1}, {'width': 0}, {'height': -1}, {'x': 0.9}, {'height': 0.9},
                       {'category': ' '}, {'review_status': 'AI verified'}, {'id': 'not-uuid'}]:
            payload = self.payload()
            payload['annotations'][0].update(fields)
            self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.payload()
        payload['annotations'].append(payload['annotations'][0].copy())
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.payload()
        payload['review_status'] = 'Reviewed'
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        self.assertEqual(self.client.get(path).json()['revision'], 0)

    def test_case_ownership_missing_file_and_non_image(self):
        case_id, upload, _ = self.attach_image()
        other = self.create()
        self.assertEqual(self.client.get(f'/cases/{other}/uploads/{upload["id"]}/annotations').status_code, 404)
        self.assertEqual(self.client.put(f'/cases/{other}/uploads/{upload["id"]}/annotations', json=self.payload()).status_code, 404)
        pdf = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('record.pdf', b'%PDF-1.4')}).json()
        self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/{pdf["id"]}/annotations').status_code, 415)
        bad = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('bad.jpg', b'\xff\xd8\xffbroken')}).json()
        self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/{bad["id"]}/annotations').status_code, 422)
        with self.main.database() as db:
            stored = db.execute('SELECT storage_name FROM uploads WHERE id=?', (upload['id'],)).fetchone()[0]
        (Path(self.temp.name) / 'uploads' / stored).unlink()
        self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/{upload["id"]}/annotations').status_code, 404)

    def test_dashboard_filters_and_put_cors(self):
        case_id, _, _ = self.attach_image()
        self.assertEqual(self.client.get('/dashboard').json()['case_count'], 1)
        self.assertEqual(self.client.get('/dashboard').json()['image_count'], 1)
        self.assertEqual(self.client.get(f'/cases?search={case_id}').json()[0]['image_count'], 1)
        self.assertEqual(self.client.get(f'/cases?search=CASE-{case_id:04d}').json()[0]['id'], case_id)
        self.assertEqual(self.client.get('/cases?search=Luna&species=Dog').json()[0]['id'], case_id)
        self.assertEqual(self.client.get('/cases?search=missing').json(), [])
        self.assertEqual(self.client.get('/cases?species=Cat').json(), [])
        self.assertEqual(self.client.get('/cases?search=%25').json(), [])
        response = self.client.options('/cases/1/uploads/1/annotations', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'PUT', 'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(response.status_code, 200)
