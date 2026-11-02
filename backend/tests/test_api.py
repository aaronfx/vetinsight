import importlib
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from tests.auth_helpers import bootstrap, sign_in


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("VETINSIGHT_DATA_DIR")
        os.environ["VETINSIGHT_DATA_DIR"] = self.temp.name
        from app import main
        self.main = importlib.reload(main)
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        bootstrap(self.main)
        sign_in(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self.previous is None:
            os.environ.pop("VETINSIGHT_DATA_DIR", None)
        else:
            os.environ["VETINSIGHT_DATA_DIR"] = self.previous
        self.temp.cleanup()

    def create(self):
        response = self.client.post("/cases", json={"patient_name": "  Luna  ", "species": "Dog", "notes": "Check-up"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["patient_name"], "Luna")
        return response.json()["id"]

    def test_cases_uploads_and_restart_persistence(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok", "database": "ok"})
        case_id = self.create()
        fixtures = [("report.pdf", b"%PDF-1.4\nfixture", "application/pdf"),
                    ("scan.jpg", b"\xff\xd8\xff\xe0fixture", "image/jpeg"),
                    ("scan.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")]
        links = []
        for filename, content, content_type in fixtures:
            result = self.client.post(f"/cases/{case_id}/uploads", files={"file": (filename, content, content_type)})
            self.assertEqual(result.status_code, 201, result.text)
            info = result.json()
            self.assertEqual(info["size_bytes"], len(content))
            links.append((info["download_url"], content))
        # Close and reload the application against the same disk storage.
        self.client.__exit__(None, None, None)
        self.main = importlib.reload(self.main)
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        sign_in(self.client)
        self.assertEqual(self.client.get("/cases").json()[0]["id"], case_id)
        detail = self.client.get(f"/cases/{case_id}").json()
        self.assertEqual(len(detail["uploads"]), 3)
        for link, content in links:
            self.assertEqual(self.client.get(link).content, content)
        other_id = self.create()
        self.assertEqual(self.client.get(links[0][0].replace(f"/cases/{case_id}/", f"/cases/{other_id}/")).status_code, 404)

    def test_validation_and_missing_records(self):
        for payload in [{}, {"patient_name": "  ", "species": "Dog"},
                        {"patient_name": "Luna", "species": "Dog", "unknown": True},
                        {"patient_name": "a" * 121, "species": "Dog"},
                        {"patient_name": "Luna", "species": "Dog", "notes": "x" * 10001}]:
            self.assertEqual(self.client.post("/cases", json=payload).status_code, 422)
        for url in ["/cases/0", "/cases/nope", "/cases?limit=101", "/cases?offset=-1"]:
            self.assertEqual(self.client.get(url).status_code, 422)
        self.assertEqual(self.client.get("/cases/999").status_code, 404)
        self.assertEqual(self.client.post("/cases/999/uploads", files={"file": ("x.pdf", b"%PDF-1.4")}).status_code, 404)
        self.assertEqual(self.client.post("/cases", content="{", headers={"Content-Type": "application/json"}).status_code, 422)

    def test_bad_uploads_cleanup_and_safe_names(self):
        case_id = self.create()
        for name, data, status in [("bad.txt", b"hello", 415), ("bad.pdf", b"hello", 415),
                                   ("empty.png", b"", 400),
                                   ("big.pdf", b"%PDF-" + b"x" * self.main.MAX_UPLOAD_BYTES, 413)]:
            response = self.client.post(f"/cases/{case_id}/uploads", files={"file": (name, data)})
            self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(list((Path(self.temp.name) / "uploads").iterdir()), [])
        self.assertEqual(self.client.get(f"/cases/{case_id}").json()["uploads"], [])
        response = self.client.post(f"/cases/{case_id}/uploads", files={"file": ("../../report.pdf", b"%PDF-1.4")})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["filename"], "report.pdf")
        self.assertFalse((Path(self.temp.name) / "report.pdf").exists())

    def test_cors(self):
        for origin in ["http://localhost:5173", "http://127.0.0.1:5173"]:
            response = self.client.options("/cases", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], origin)
        response = self.client.options("/cases", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
