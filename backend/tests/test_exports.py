from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from uuid import uuid4
from zipfile import ZipFile

from PIL import Image
from tests import test_api


class ExportTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def attach(self, case_id, orientation=None):
        output = BytesIO()
        image = Image.new('RGB', (100, 60), 'red')
        image.paste('blue', (0, 0, 50, 60))
        if orientation:
            exif = Image.Exif(); exif[274] = orientation
            image.save(output, 'JPEG', exif=exif)
        else:
            image.save(output, 'PNG')
        content = output.getvalue()
        upload = self.client.post(f'/cases/{case_id}/uploads', files={'file':
            ('private.jpg' if orientation else 'private.png', content)}).json()
        return upload, content

    def review(self, case_id, upload, category='Cell', status='Reviewed', empty=False):
        payload = {'revision': 0, 'review_status': status, 'annotations': [] if empty else [
            {'id': str(uuid4()), 'x': .1, 'y': .2, 'width': .3, 'height': .4,
             'category': category, 'review_status': 'Reviewed', 'notes': 'Manual observation'}]}
        response = self.client.put(f'/cases/{case_id}/uploads/{upload["id"]}/annotations', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_coco_boxes_manifest_and_storage_preserved(self):
        case_id = self.create()
        first, content = self.attach(case_id)
        saved = self.review(case_id, first, 'Z cell')
        second, _ = self.attach(case_id)
        self.review(case_id, second, 'A cell')
        excluded, _ = self.attach(case_id)
        self.review(case_id, excluded, 'Unclassified')
        other_case = self.create()
        other_image, _ = self.attach(other_case)
        self.review(other_case, other_image, 'Foreign cell')
        case = self.client.get(f'/cases/{case_id}').json()
        response = self.client.get(f'/cases/{case_id}/exports/coco')
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertEqual(response.headers['content-type'], 'application/zip')
        self.assertIn('attachment', response.headers['content-disposition'])
        with ZipFile(BytesIO(response.content)) as archive:
            coco = json.loads(archive.read('annotations.json'))
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(coco['categories'], [{'id': 1, 'name': 'A cell'}, {'id': 2, 'name': 'Z cell'}])
            self.assertEqual([image['id'] for image in coco['images']], [first['id'], second['id']])
            self.assertEqual(coco['annotations'][0]['bbox'], [10, 12, 30, 24])
            self.assertEqual(coco['annotations'][0]['area'], 720)
            self.assertEqual(coco['annotations'][0]['category_id'], 2)
            self.assertEqual(coco['annotations'][0]['image_id'], first['id'])
            self.assertEqual(manifest['images'][0]['annotations'], saved['annotations'])
            self.assertEqual(manifest['images'][0]['revision'], saved['revision'])
            self.assertEqual(manifest['case_id'], case_id)
            self.assertEqual(manifest['skipped_images'][0]['upload_id'], excluded['id'])
            self.assertIsNone(manifest['split'])
            self.assertNotIn('patient_name', manifest)
            self.assertNotIn('private.png', json.dumps(manifest))
            image = Image.open(BytesIO(archive.read(coco['images'][0]['file_name'])))
            self.assertEqual(image.size, (100, 60))
            self.assertEqual(image.getpixel((10, 10)), (0, 0, 255))
        self.assertEqual(self.client.get(f'/cases/{case_id}').json(), case)
        self.assertEqual(self.client.get(first['download_url']).content, content)
        self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/{first["id"]}/annotations').json(), saved)

    def test_oriented_pixels_and_bbox_agree(self):
        case_id = self.create()
        upload, content = self.attach(case_id, 6)
        self.review(case_id, upload)
        with ZipFile(BytesIO(self.client.get(f'/cases/{case_id}/exports/coco').content)) as archive:
            coco = json.loads(archive.read('annotations.json'))
            self.assertEqual(coco['annotations'][0]['bbox'], [6, 20, 18, 40])
            image = Image.open(BytesIO(archive.read(coco['images'][0]['file_name'])))
            self.assertEqual(image.size, (60, 100))
            self.assertFalse(image.getexif())
            self.assertGreater(image.getpixel((30, 10))[2], 240)
            self.assertGreater(image.getpixel((30, 90))[0], 240)
        self.assertEqual(self.client.get(upload['download_url']).content, content)

    def test_empty_incomplete_and_placeholder_categories_are_excluded(self):
        case_id = self.create()
        for category, status, empty in [('Cell', 'Needs Review', False),
            ('Unclassified', 'Reviewed', False), ('needs REVIEW', 'Reviewed', False), ('Cell', 'Reviewed', True)]:
            upload, _ = self.attach(case_id)
            self.review(case_id, upload, category, status, empty)
        response = self.client.get(f'/cases/{case_id}/exports/coco')
        self.assertEqual(response.status_code, 422)
        self.assertIn('No exportable images', response.json()['detail'])
        other = self.create()
        self.assertEqual(self.client.get(f'/cases/{other}/exports/coco').status_code, 422)
        self.assertEqual(self.client.get('/cases/999/exports/coco').status_code, 404)

    def test_missing_file_and_export_cleanup(self):
        case_id = self.create()
        upload, _ = self.attach(case_id)
        self.review(case_id, upload)
        import app.exports as exports
        original = exports.TemporaryDirectory
        paths = []
        def tracked(*args, **kwargs):
            result = original(*args, **kwargs); paths.append(Path(result.name)); return result
        with patch.object(exports, 'TemporaryDirectory', tracked):
            self.assertEqual(self.client.get(f'/cases/{case_id}/exports/coco').status_code, 200)
            with self.main.database() as db:
                storage = db.execute('SELECT storage_name FROM uploads WHERE id=?', (upload['id'],)).fetchone()[0]
            (Path(self.temp.name) / 'uploads' / storage).unlink()
            self.assertEqual(self.client.get(f'/cases/{case_id}/exports/coco').status_code, 404)
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_transparency_and_pixel_limit(self):
        case_id = self.create()
        output = BytesIO()
        Image.new('RGBA', (100, 60), (0, 0, 0, 0)).save(output, 'PNG')
        upload = self.client.post(f'/cases/{case_id}/uploads', files={'file': ('transparent.png', output.getvalue())}).json()
        self.review(case_id, upload)
        with ZipFile(BytesIO(self.client.get(f'/cases/{case_id}/exports/coco').content)) as archive:
            coco = json.loads(archive.read('annotations.json'))
            image = Image.open(BytesIO(archive.read(coco['images'][0]['file_name'])))
            self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.getpixel((10, 10)), (255, 255, 255))
        with patch.object(self.main, 'image_dimensions_for_file', return_value=(10001, 10000)):
            response = self.client.get(f'/cases/{case_id}/exports/coco')
            self.assertEqual(response.status_code, 413)
            self.assertIn('pixel limit', response.json()['detail'])
