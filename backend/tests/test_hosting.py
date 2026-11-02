"""Same-origin hosting must expose assets without exposing case data."""
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient


class HostingTests(TestCase):
    def test_static_files_api_auth_and_remote_setup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / 'static'
            (static / 'assets').mkdir(parents=True)
            (static / 'index.html').write_text('<html>VetInsight</html>')
            (static / 'assets' / 'app.js').write_text('/* fixture */')
            with patch.dict(os.environ, VETINSIGHT_DATA_DIR=str(root / 'data'),
                            VETINSIGHT_STATIC_DIR=str(static), RAILWAY_PUBLIC_DOMAIN='vet.test'):
                from app import main
                importlib.reload(main)
                with TestClient(main.app, base_url='https://vet.test') as client:
                    self.assertEqual(client.get('/').status_code, 200)
                    self.assertEqual(client.get('/assets/app.js').status_code, 200)
                    self.assertEqual(client.get('/cases').status_code, 401)
                    self.assertEqual(client.get('/assets/../cases').status_code, 401)
                    self.assertEqual(client.get('/auth/status').json()['web_setup_available'], False)
                    self.assertEqual(client.post('/auth/setup', json={'username': 'fixture-admin', 'display_name': 'Fixture', 'password': 'Fixture-only-password!2026'}, headers={'X-VetInsight-Request': '1', 'Origin': 'https://vet.test'}).status_code, 403)
                    response = client.options('/cases', headers={'Origin': 'https://vet.test', 'Access-Control-Request-Method': 'POST'})
                    self.assertEqual(response.headers['access-control-allow-origin'], 'https://vet.test')
            importlib.reload(main)
