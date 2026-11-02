"""Isolated browser QA backend on port 8001; live case storage is never used."""
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import sqlite3

# Keep both direct script execution and `python -m tests.preview_server` working.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app import security
from tests.auth_helpers import PASSWORD
from PIL import Image, ImageDraw


def main():
    with tempfile.TemporaryDirectory(prefix='vetinsight-browser-qa-') as directory:
        env = {**os.environ, 'VETINSIGHT_DATA_DIR': directory, 'VETINSIGHT_FRONTEND_ORIGIN': 'http://localhost:5174'}
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001'],
                                   cwd=Path(__file__).resolve().parents[1], env=env)
        try:
            with httpx.Client(base_url='http://127.0.0.1:8001', trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('QA backend failed to start')
                    try:
                        if client.get('/health').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('QA backend startup timed out')
                with sqlite3.connect(Path(directory) / 'vetinsight.sqlite3') as db:
                    security.create_first_admin(db, security.NewUser(username='test-admin', display_name='QA administrator', password=PASSWORD))
                client.headers['X-VetInsight-Request'] = '1'
                client.post('/auth/login', json={'username': 'test-admin', 'password': PASSWORD}).raise_for_status()
                case = client.post('/cases', json={'patient_name': 'Geometry test — not a clinical case', 'species': 'Test fixture',
                    'notes': 'Isolated browser QA data. Shapes are geometric targets, not cells.'})
                case.raise_for_status()
                image = Image.new('RGB', (1000, 600), '#e9eff7')
                draw = ImageDraw.Draw(image)
                draw.text((30, 20), 'GEOMETRY TEST FIXTURE - NOT A CLINICAL IMAGE', fill='#003644', font_size=25)
                for x in range(0, 1000, 100):
                    draw.line((x, 70, x, 600), fill='#c0cfde')
                for y in range(100, 600, 100):
                    draw.line((0, y, 1000, y), fill='#c0cfde')
                draw.ellipse((200, 150, 380, 330), fill='#98b7da', outline='#134e5e', width=4)
                draw.rectangle((600, 300, 820, 500), fill='#c6daca', outline='#005338', width=4)
                buffer = BytesIO()
                image.save(buffer, 'PNG')
                upload = client.post(f'/cases/{case.json()["id"]}/uploads', files={'file': ('geometry-test.png', buffer.getvalue(), 'image/png')})
                upload.raise_for_status()
                print('QA fixture ready: case', case.json()['id'], 'image', upload.json()['id'], flush=True)
            process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    main()
