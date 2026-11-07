import io
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from tests import test_api
from app import analysis


class AnalysisTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def upload(self):
        case = self.create()
        image = io.BytesIO()
        Image.new('RGB', (80, 60)).save(image, 'PNG')
        upload = self.client.post(f'/cases/{case}/uploads', files={'file': ('demo.png', image.getvalue(), 'image/png')}).json()
        return f'/cases/{case}/uploads/{upload["id"]}'

    def test_real_request_contract_persistence_and_manual_isolation(self):
        path = self.upload()
        payload = {'task': 'histology', 'request_id': str(uuid4()), 'acknowledge_experimental': True}
        result = {'candidates': [], 'model_id': 'test-double', 'image_width': 80, 'image_height': 60}
        with patch.object(analysis, 'available', return_value=True), patch.object(analysis, 'detect', return_value=result):
            self.assertEqual(self.client.post(path + '/analysis', json={**payload, 'acknowledge_experimental': False}).status_code, 422)
            response = self.client.post(path + '/analysis', json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            for _ in range(100):
                run = self.client.get(path + '/analysis').json()[0]
                if run['status'] not in ('queued', 'running'):
                    break
                time.sleep(.02)
            self.assertEqual(run['status'], 'completed', run)
            self.assertEqual(run['result'], result)
            self.assertEqual(self.client.post(path + '/analysis', json=payload).json()['id'], run['id'])
            self.assertEqual(len(self.client.get(path + '/analysis').json()), 1)
            self.assertEqual(self.client.get(path + '/annotations').json()['annotations'], [])
            with self.main.database() as db:
                analysis.initialize(db)
            self.assertEqual(self.client.get(path + '/analysis').json()[0]['result'], result)

    def test_cytology_runs_with_installed_model_and_labels_candidates(self):
        path = self.upload()
        payload = {'task': 'cytology', 'request_id': str(uuid4()), 'acknowledge_experimental': True}
        result = {'candidates': [{'id': 'a', 'x': .1, 'y': .1, 'width': .2, 'height': .2, 'score': .9, 'category': 'LSIL'}],
                  'model_id': 'test-double', 'image_width': 80, 'image_height': 60}
        seen = []
        def fake_detect(file_path, task='histology'):
            seen.append(task)
            return result
        with patch.object(analysis, 'available', return_value=True), patch.object(analysis, 'detect', side_effect=fake_detect):
            self.assertEqual(self.client.post(path + '/analysis', json=payload).status_code, 202)
            for _ in range(100):
                run = self.client.get(path + '/analysis').json()[0]
                if run['status'] not in ('queued', 'running'):
                    break
                time.sleep(.02)
        self.assertEqual(seen, ['cytology'])
        self.assertEqual(run['task'], 'cytology')
        self.assertEqual(run['result']['candidates'][0]['category'], 'LSIL')
        self.assertEqual(self.client.get(path + '/annotations').json()['annotations'], [])

    def test_cytology_is_unavailable_without_model_and_restart_marks_interrupted_jobs(self):
        path = self.upload()
        payload = {'task': 'cytology', 'request_id': str(uuid4()), 'acknowledge_experimental': True}
        with patch.object(analysis, 'available', return_value=False):
            self.assertEqual(self.client.post(path + '/analysis', json=payload).status_code, 409)
            models = self.client.get('/analysis/models').json()
            self.assertFalse(models['cytology']['available'])
            self.assertIn('No cytology model', models['cytology']['limitation'])
        with self.main.database() as db:
            upload = db.execute('SELECT id FROM uploads').fetchone()['id']
            db.execute('INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?)', (str(uuid4()), upload, 1, 'histology', 'running', '{}', '', analysis.stamp(), analysis.stamp()))
        with self.main.database() as db:
            analysis.initialize(db)
        run = self.client.get(path + '/analysis').json()[0]
        self.assertEqual(run['status'], 'failed')
        self.assertIn('restart', run['error'])
