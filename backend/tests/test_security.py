import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests import test_api
from tests.auth_helpers import PASSWORD, sign_in
from app import security


class SecurityTests(test_api.ApiTests):
    def member(self, name='member-one'):
        response = self.client.post('/admin/users', json={'username': name, 'display_name': 'Member', 'password': PASSWORD, 'role': 'member'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def login_member(self, name='member-one', change=True):
        client = TestClient(self.main.app, headers={'X-VetInsight-Request': '1'})
        response = client.post('/auth/login', json={'username': name, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        if change:
            response = client.post('/auth/password', json={'current_password': PASSWORD, 'password': 'Changed-member-password!2026'})
            self.assertEqual(response.status_code, 200, response.text)
        return client

    def test_anonymous_routes_and_forged_role(self):
        client = TestClient(self.main.app)
        for path in ['/cases', '/cases/1', '/dashboard', '/admin/users', '/admin/audit', '/docs', '/openapi.json', '/cases/1/uploads/1/preview', '/cases/1/exports/coco']:
            self.assertEqual(client.get(path, headers={'X-Role': 'admin'}).status_code, 401, path)
        self.assertEqual(client.get('/health').status_code, 200)
        self.assertFalse(client.get('/auth/status').json()['needs_setup'])

    def test_member_cannot_admin_but_can_use_workspace(self):
        self.member()
        client = self.login_member()
        for path in ['/admin/users', '/admin/audit', '/admin/overview', '/openapi.json']:
            self.assertEqual(client.get(path).status_code, 403)
        self.assertEqual(client.post('/admin/users', json={}).status_code, 403)
        self.assertEqual(client.put('/admin/users/1', json={'role': 'admin'}).status_code, 403)
        self.assertEqual(client.post('/cases', json={'patient_name': 'Test', 'species': 'Cat'}).status_code, 201)
        self.assertEqual(client.get('/dashboard').status_code, 200)
        self.assertEqual(client.post('/auth/password', json={'current_password': 'wrong', 'password': 'Another-password-2026!'}).status_code, 400)

    def test_temporary_password_blocks_workspace_until_changed(self):
        self.member()
        client = self.login_member(change=False)
        self.assertTrue(client.get('/auth/me').json()['must_change_password'])
        self.assertEqual(client.get('/cases').status_code, 403)
        self.assertEqual(client.post('/auth/password', json={'current_password': PASSWORD, 'password': PASSWORD}).status_code, 422)
        self.assertEqual(client.post('/auth/password', json={'current_password': PASSWORD, 'password': 'Replacement-password-2026!'}).status_code, 200)
        self.assertEqual(client.get('/cases').status_code, 200)

    def test_disable_role_change_and_reset_revoke_sessions(self):
        user = self.member()
        client = self.login_member()
        changed = {'display_name': 'Member', 'role': 'admin', 'active': True}
        self.assertEqual(self.client.put(f'/admin/users/{user["id"]}', json=changed).status_code, 200)
        self.assertEqual(client.get('/cases').status_code, 401)
        client.post('/auth/login', json={'username': user['username'], 'password': 'Changed-member-password!2026'})
        self.assertEqual(client.get('/admin/users').status_code, 200)
        changed['active'] = False
        self.assertEqual(self.client.put(f'/admin/users/{user["id"]}', json=changed).status_code, 200)
        self.assertEqual(client.get('/cases').status_code, 401)
        self.assertEqual(client.post('/auth/login', json={'username': user['username'], 'password': 'Changed-member-password!2026'}).status_code, 401)
        changed['active'] = True
        self.client.put(f'/admin/users/{user["id"]}', json=changed)
        client.post('/auth/login', json={'username': user['username'], 'password': 'Changed-member-password!2026'})
        self.assertEqual(self.client.post(f'/admin/users/{user["id"]}/password', json={'password': PASSWORD}).status_code, 200)
        self.assertEqual(client.get('/cases').status_code, 401)
        self.assertTrue(client.post('/auth/login', json={'username': user['username'], 'password': PASSWORD}).json()['must_change_password'])

    def test_last_admin_and_bootstrap_protection(self):
        for role, active in [('member', True), ('admin', False)]:
            response = self.client.put('/admin/users/1', json={'display_name': 'Test admin', 'role': role, 'active': active})
            self.assertEqual(response.status_code, 409)
        with self.main.database() as db:
            with self.assertRaises(ValueError):
                security.create_first_admin(db, security.NewUser(username='second-admin', display_name='Admin', password=PASSWORD))

    def test_csrf_cors_and_cookie_flags(self):
        self.assertEqual(self.client.post('/auth/logout', headers={'X-VetInsight-Request': ''}).status_code, 403)
        for origin in ['https://evil.example', 'null', 'http://localhost:5173.evil.example']:
            self.assertEqual(self.client.post('/cases', json={}, headers={'Origin': origin}).status_code, 403)
        response = self.client.options('/auth/login', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,x-vetinsight-request'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-credentials'], 'true')
        response = self.client.post('/auth/login', json={'username': 'test-admin', 'password': PASSWORD})
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie); self.assertIn('samesite=lax', cookie)
        self.assertNotIn('password_hash', response.text)

    def test_logout_expiry_and_hash_storage(self):
        token = self.client.cookies.get(security.COOKIE)
        with self.main.database() as db:
            row = db.execute('SELECT * FROM sessions WHERE token_hash=?', (security.token_hash(token),)).fetchone()
            self.assertNotEqual(row['token_hash'], token)
            self.assertNotIn(PASSWORD, db.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0])
        self.client.post('/auth/logout')
        self.client.cookies.set(security.COOKIE, token)
        self.assertEqual(self.client.get('/cases').status_code, 401)
        self.client.cookies.clear(); sign_in(self.client)
        with self.main.database() as db:
            db.execute('UPDATE sessions SET expires_at=?', (time.time() - 1,))
        self.assertEqual(self.client.get('/auth/me').status_code, 401)

    def test_password_change_rotates_session(self):
        old_token = self.client.cookies.get(security.COOKIE)
        response = self.client.post('/auth/password', json={'current_password': PASSWORD, 'password': 'New-admin-password-2026!'})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.client.cookies.get(security.COOKIE), old_token)
        other = TestClient(self.main.app)
        other.cookies.set(security.COOKIE, old_token)
        self.assertEqual(other.get('/cases').status_code, 401)
        self.assertEqual(self.client.get('/cases').status_code, 200)

    def test_validation_audit_and_counts(self):
        self.create()
        self.member()
        self.assertEqual(self.client.post('/admin/users', json={'username': 'MEMBER-ONE', 'display_name': 'Dup', 'password': PASSWORD}).status_code, 409)
        self.assertEqual(self.client.post('/admin/users', json={'username': 'bad name', 'display_name': 'Bad', 'password': PASSWORD}).status_code, 422)
        self.assertEqual(self.client.post('/admin/users', json={'username': 'good-name', 'display_name': ' ', 'password': 'short'}).status_code, 422)
        self.assertEqual(self.client.put('/admin/users/999', json={'display_name': 'Missing', 'role': 'member', 'active': True}).status_code, 404)
        self.assertEqual(self.client.get('/admin/users?limit=101').status_code, 422)
        overview = self.client.get('/admin/overview').json()
        self.assertEqual((overview['users'], overview['cases']), (2, 1))
        events = self.client.get('/admin/audit?limit=2').json()
        self.assertEqual(len(events['items']), 2)
        self.assertGreater(events['total'], 2)
        all_events = self.client.get('/admin/audit').json()
        self.assertIn('workspace.post', [item['action'] for item in all_events['items']])
        self.assertNotIn(PASSWORD, str(all_events))

    def test_login_throttle_survives_clients(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/auth/login', json={'username': 'nonexistent', 'password': 'bad'}).status_code, 401)
        client = TestClient(self.main.app, headers={'X-VetInsight-Request': '1'})
        response = client.post('/auth/login', json={'username': 'NONEXISTENT', 'password': 'bad'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('retry-after', response.headers)

    def test_case_mutation_rolls_back_when_audit_write_fails(self):
        with patch('app.security.audit', side_effect=RuntimeError('simulated audit failure')):
            with self.assertRaises(Exception):
                self.client.post('/cases', json={'patient_name': 'Rollback fixture', 'species': 'Test'})
        self.assertEqual(self.client.get('/cases').json(), [])
