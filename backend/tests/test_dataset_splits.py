import importlib
from io import BytesIO
import json
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from tests.auth_helpers import sign_in
from tests import test_api, test_exports


class DatasetSplitTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create
    attach = test_exports.ExportTests.attach
    review = test_exports.ExportTests.review

    def test_default_validation_and_case_isolation(self):
        case_id = self.create()
        path = f'/cases/{case_id}/dataset-assignment'
        self.assertEqual(self.client.get(path).json(),
            {'case_id': case_id, 'split': 'unassigned', 'revision': 0, 'updated_at': None})
        for payload in [{'split': 'testing', 'revision': 0}, {'split': 'train', 'revision': -1},
                        {'split': 'train', 'revision': True}, {'split': 'train', 'revision': '0'},
                        {'split': 'train', 'revision': 0, 'upload_id': 1}, {'split': 'train'}]:
            self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        self.assertEqual(self.client.get('/cases/999/dataset-assignment').status_code, 404)
        self.assertEqual(self.client.put('/cases/999/dataset-assignment', json={'split': 'train', 'revision': 0}).status_code, 404)
        self.assertEqual(self.client.put(path, json={'split': 'train', 'revision': 0}).status_code, 200)
        other = self.create()
        self.assertEqual(self.client.get(f'/cases/{other}/dataset-assignment').json()['split'], 'unassigned')

    def test_conflicts_reassignment_unassignment_and_restart(self):
        case_id = self.create()
        path = f'/cases/{case_id}/dataset-assignment'
        saved = self.client.put(path, json={'split': 'validation', 'revision': 0}).json()
        self.assertEqual(saved['revision'], 1)
        self.assertIsNotNone(saved['updated_at'])
        # Duplicate requests at the current revision are no-ops.
        self.assertEqual(self.client.put(path, json={'split': 'validation', 'revision': 1}).json(), saved)
        self.assertEqual(self.client.put(path, json={'split': 'test', 'revision': 0}).status_code, 409)
        self.assertEqual(self.client.get(path).json(), saved)
        self.client.__exit__(None, None, None)
        self.main = importlib.reload(self.main)
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        sign_in(self.client)
        self.assertEqual(self.client.get(path).json(), saved)
        self.assertEqual(self.client.put(path, json={'split': 'test', 'revision': 1}).json()['revision'], 2)
        reset = self.client.put(path, json={'split': 'unassigned', 'revision': 2}).json()
        self.assertEqual(reset['split'], 'unassigned')
        self.assertEqual(reset['revision'], 3)

    def test_all_case_images_inherit_split_exports_and_records_stay_unchanged(self):
        case_id = self.create()
        first, original = self.attach(case_id)
        saved = self.review(case_id, first)
        path = f'/cases/{case_id}/dataset-assignment'
        assigned = self.client.put(path, json={'split': 'train', 'revision': 0}).json()
        # New uploads inherit the case assignment without individual split rows.
        second, _ = self.attach(case_id)
        self.review(case_id, second)
        case = self.client.get(f'/cases/{case_id}').json()
        response = self.client.get(f'/cases/{case_id}/exports/coco')
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['split'], 'train')
            self.assertEqual(manifest['dataset_assignment'], assigned)
            self.assertEqual([item['split'] for item in manifest['images']], ['train', 'train'])
            self.assertEqual([item['case_id'] for item in manifest['images']], [case_id, case_id])
        self.client.put(path, json={'split': 'test', 'revision': 1})
        with ZipFile(BytesIO(self.client.get(f'/cases/{case_id}/exports/coco').content)) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json'))['split'], 'test')
        # Previously downloaded archives remain snapshots, not mutable datasets.
        self.assertEqual(manifest['split'], 'train')
        self.assertEqual(self.client.get(f'/cases/{case_id}').json(), case)
        self.assertEqual(self.client.get(first['download_url']).content, original)
        self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/{first["id"]}/annotations').json(), saved)
