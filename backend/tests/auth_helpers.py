from app import security

PASSWORD = 'Isolated-test-password-2026!'


def bootstrap(main):
    with main.database() as db:
        if not db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            security.create_first_admin(db, security.NewUser(username='test-admin', display_name='Test admin', password=PASSWORD))


def sign_in(client):
    client.headers['X-VetInsight-Request'] = '1'
    response = client.post('/auth/login', json={'username': 'test-admin', 'password': PASSWORD})
    assert response.status_code == 200, response.text
