import importlib
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


class FirstAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get('VETINSIGHT_DATA_DIR')
        os.environ['VETINSIGHT_DATA_DIR'] = self.temp.name
        from app import main
        self.main = importlib.reload(main)
        self.client = self.local_client()
        self.client.__enter__()
        self.payload = {'username': 'local-admin', 'display_name': 'Local administrator', 'password': 'Local-test-password!2026'}

    def local_client(self):
        return TestClient(self.main.app, base_url='http://localhost:8000', client=('127.0.0.1', 12345),
                          headers={'X-VetInsight-Request': '1', 'Origin': 'http://localhost:5173'})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self.previous is None:
            os.environ.pop('VETINSIGHT_DATA_DIR', None)
        else:
            os.environ['VETINSIGHT_DATA_DIR'] = self.previous
        self.temp.cleanup()

    def test_local_setup_creates_admin_and_session_and_closes_registration(self):
        self.assertTrue(self.client.get('/auth/status').json()['web_setup_available'])
        response = self.client.post('/auth/setup', json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['role'], 'admin')
        self.assertFalse(response.json()['must_change_password'])
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertNotIn(self.payload['password'], response.text)
        self.assertEqual(self.client.get('/admin/users').status_code, 200)
        self.assertFalse(self.client.get('/auth/status').json()['web_setup_available'])
        self.assertEqual(self.client.post('/auth/setup', json=self.payload).status_code, 409)

    def test_remote_requests_and_nonlocal_hosts_cannot_bootstrap(self):
        for host, address in [('http://localhost:8000', '192.0.2.10'), ('http://public.example', '127.0.0.1')]:
            client = TestClient(self.main.app, base_url=host, client=(address, 12345), headers={'X-VetInsight-Request': '1'})
            self.assertFalse(client.get('/auth/status').json()['web_setup_available'])
            self.assertEqual(client.post('/auth/setup', json=self.payload).status_code, 403)

    def test_forwarded_requests_cannot_bootstrap(self):
        for header in ['Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto']:
            headers = {header: 'untrusted'}
            self.assertFalse(self.client.get('/auth/status', headers=headers).json()['web_setup_available'])
            self.assertEqual(self.client.post('/auth/setup', json=self.payload, headers=headers).status_code, 403)

    def test_origin_and_security_header_are_required_for_browser_writes(self):
        self.assertEqual(self.client.post('/auth/setup', json=self.payload, headers={'X-VetInsight-Request': ''}).status_code, 403)
        self.assertEqual(self.client.post('/auth/setup', json=self.payload, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertTrue(self.client.get('/auth/status').json()['needs_setup'])

    def test_validation_does_not_echo_password_or_create_account(self):
        response = self.client.post('/auth/setup', json={**self.payload, 'password': 'bad-secret'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('bad-secret', response.text)
        self.assertTrue(self.client.get('/auth/status').json()['needs_setup'])

    def test_concurrent_setup_only_creates_one_administrator(self):
        def create(index):
            with self.local_client() as client:
                return client.post('/auth/setup', json={**self.payload, 'username': f'local-admin-{index}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(create, [1, 2]))
        self.assertEqual(sorted(statuses), [201, 409])
        with self.main.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
