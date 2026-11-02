"""Migration safety against isolated local fixtures; not a PostgreSQL substitute."""
from contextlib import contextmanager
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from fastapi import HTTPException
from dotenv import dotenv_values

from app import database, migrate_cloud
from app.cloud_config import CloudSettings
from tests import test_api
from tests.test_documents import pdf_bytes


class SequenceProxy:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        if sql.startswith('SELECT setval('):
            return None
        return self.raw.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class FixtureStore:
    def __init__(self):
        self.objects = {}

    def checked_name(self, name):
        from app.object_storage import ObjectStorage
        return ObjectStorage.checked_name(self, name)

    def ensure_private_bucket(self, create=False):
        pass

    def upload(self, name, path, content_type):
        if name in self.objects:
            raise AssertionError('An existing object must never be overwritten')
        self.objects[name] = path.read_bytes()

    @contextmanager
    def local_copy(self, name):
        if name not in self.objects:
            raise HTTPException(404)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / name
            path.write_bytes(self.objects[name])
            yield path


class CloudMigrationTests(unittest.TestCase):
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def setUp(self):
        test_api.ApiTests.setUp(self)
        self.root = Path(self.temp.name)
        self.target = self.root / 'cloud-fixture'; self.target.mkdir()
        self.case_id = self.create()
        self.content = pdf_bytes(['Migration fixture, not a clinical record'])
        response = self.client.post(f'/cases/{self.case_id}/uploads', files={'file': ('fixture.pdf', self.content, 'application/pdf')})
        self.assertEqual(response.status_code, 201)
        self.store = FixtureStore()
        self.settings = CloudSettings('postgresql://fixture:secret@example.com/db?sslmode=require', 'supabase', 'https://fixture.supabase.co', 'sb_secret_fixture')
        self.active_file = self.root / 'active.env'

    @contextmanager
    def target_connect(self, *args):
        with database.connect(self.target) as db:
            db.raw = SequenceProxy(db.raw)
            yield db

    def run_migration(self, activate=True):
        with patch.object(migrate_cloud, 'connect', self.target_connect), patch.object(migrate_cloud, 'ObjectStorage', return_value=self.store), patch.object(migrate_cloud, 'ACTIVE_FILE', self.active_file):
            return migrate_cloud.migrate(self.root, self.settings, self.root / 'backups', activate)

    def test_all_rows_files_and_account_hashes_preserved_before_activation(self):
        with self.main.database() as db:
            expected = migrate_cloud.rows(db)
        manifest = self.run_migration()
        self.assertTrue(manifest['activated'])
        with database.connect(self.target) as db:
            self.assertEqual(migrate_cloud.rows(db), expected)
        self.assertEqual(list(self.store.objects.values()), [self.content])
        self.assertEqual(dotenv_values(self.active_file)['SUPABASE_SECRET_KEY'], 'sb_secret_fixture')
        backups = list((self.root / 'backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / 'vetinsight.sqlite3').is_file())
        self.assertEqual(next((backups[0] / 'uploads').iterdir()).read_bytes(), self.content)

    def test_different_existing_rows_are_never_overwritten(self):
        self.run_migration(False)
        with database.connect(self.target) as db:
            db.execute('UPDATE cases SET notes=?', ('Cloud change',))
        with self.assertRaises(migrate_cloud.MigrationError):
            self.run_migration()
        self.assertFalse(self.active_file.exists())
        with database.connect(self.target) as db:
            self.assertEqual(db.execute('SELECT notes FROM cases').fetchone()[0], 'Cloud change')

    def test_different_cloud_file_refuses_activation_without_overwriting(self):
        self.run_migration(False)
        name = next(iter(self.store.objects))
        self.store.objects[name] = b'changed cloud file'
        with self.assertRaises(migrate_cloud.MigrationError):
            self.run_migration()
        self.assertFalse(self.active_file.exists())
        self.assertEqual(self.store.objects[name], b'changed cloud file')

    def test_late_verification_failure_rolls_back_imported_rows(self):
        with patch.object(migrate_cloud, 'check_rows', side_effect=migrate_cloud.MigrationError('simulated verification failure')):
            with self.assertRaises(migrate_cloud.MigrationError):
                self.run_migration()
        self.assertFalse(self.active_file.exists())
        with database.connect(self.target) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cases').fetchone()[0], 0)
        self.assertTrue((self.root / 'vetinsight.sqlite3').exists())

    def test_running_backend_port_refuses_offline_migration(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0)); server.listen(1)
            port = server.getsockname()[1]
            with self.assertRaises(migrate_cloud.MigrationError):
                with migrate_cloud.require_offline(port):
                    self.fail('Migration must refuse an occupied port')
