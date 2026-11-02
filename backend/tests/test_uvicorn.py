"""Real HTTP smoke check with a process restart and isolated persistent storage."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from tests.auth_helpers import PASSWORD
from tests.test_annotations import image_bytes


class UvicornTests(unittest.TestCase):
    def test_http_and_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "VETINSIGHT_DATA_DIR": directory}
            subprocess.run([sys.executable, '-c', '''
import asyncio
from app import main, security
async def setup():
    async with main.lifespan(main.app):
        with main.database() as db:
            security.create_first_admin(db, security.NewUser(username='test-admin',display_name='Test admin',password='Isolated-test-password-2026!'))
asyncio.run(setup())
'''], cwd=Path(__file__).resolve().parents[1], env=env, check=True)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                case_id = None
                link = None
                content = b"%PDF-1.4\nHTTP persistence fixture"
                annotation_path = None
                image_link = None
                annotation_payload = {'revision': 0, 'review_status': 'In Progress', 'annotations': [
                    {'id': '9571fd3a-2b3b-4ca1-9b1d-c361c0b60d68', 'x': .1, 'y': .2, 'width': .3, 'height': .4,
                     'category': 'Unclassified', 'review_status': 'Needs Review', 'notes': ''}]}
                for run in range(2):
                    process = subprocess.Popen(
                        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                        cwd=Path(__file__).resolve().parents[1], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    try:
                        for attempt in range(100):
                            self.assertIsNone(process.poll(), "Uvicorn exited before becoming ready")
                            try:
                                response = client.get("/health")
                                if response.status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            time.sleep(0.1)
                        else:
                            self.fail("Uvicorn did not become ready")
                        client.headers['X-VetInsight-Request'] = '1'
                        self.assertEqual(client.post('/auth/login', json={'username': 'test-admin', 'password': PASSWORD}).status_code, 200)
                        self.assertEqual(client.get("/docs").status_code, 200)
                        self.assertEqual(client.get("/openapi.json").status_code, 200)
                        if run == 0:
                            response = client.post("/cases", json={"patient_name": "HTTP test", "species": "Cat"})
                            self.assertEqual(response.status_code, 201)
                            case_id = response.json()["id"]
                            response = client.post(f"/cases/{case_id}/uploads", files={"file": ("report.pdf", content, "application/pdf")})
                            self.assertEqual(response.status_code, 201)
                            link = response.json()["download_url"]
                            image = client.post(f'/cases/{case_id}/uploads', files={'file': ('geometry.png', image_bytes(), 'image/png')})
                            self.assertEqual(image.status_code, 201)
                            annotation_path = f'/cases/{case_id}/uploads/{image.json()["id"]}/annotations'
                            image_link = image.json()['download_url']
                            self.assertEqual(client.put(annotation_path, json=annotation_payload).status_code, 200)
                            assignment = client.put(f'/cases/{case_id}/dataset-assignment', json={'split': 'validation', 'revision': 0})
                            self.assertEqual(assignment.status_code, 200)
                        self.assertEqual(client.get("/cases").json()[0]["id"], case_id)
                        self.assertEqual(len(client.get(f"/cases/{case_id}").json()["uploads"]), 2)
                        self.assertEqual(client.get(link).content, content)
                        self.assertEqual(client.get(image_link).content, image_bytes())
                        saved = client.get(annotation_path).json()
                        self.assertEqual(saved['revision'], 1)
                        self.assertEqual(saved['annotations'], annotation_payload['annotations'])
                        self.assertEqual(client.get(f'/cases/{case_id}/dataset-assignment').json()['split'], 'validation')
                        self.assertEqual(client.get(f'/cases/{case_id}/dataset-assignment').json()['revision'], 1)
                    finally:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
