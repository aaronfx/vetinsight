from pathlib import Path
import tempfile
import unittest

from app.cloud_config import CloudSettings
from app.database import connect, IntegrityError, postgres_sql, Record


class DatabaseAdapterTests(unittest.TestCase):
    def test_markers_do_not_modify_literals_or_parameter_values(self):
        self.assertEqual(postgres_sql("SELECT '?' AS question, 'it''s ?' AS literal WHERE id=? AND name LIKE 'a%'"),
                         "SELECT '?' AS question, 'it''s ?' AS literal WHERE id=%s AND name LIKE 'a%%'")

    def test_sqlite_transactions_and_integrity_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            with connect(Path(directory)) as db:
                db.executescript('CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT UNIQUE);')
            with self.assertRaises(IntegrityError):
                with connect(Path(directory)) as db:
                    db.execute('INSERT INTO items VALUES (?,?)', (1, 'test'))
                    db.execute('INSERT INTO items VALUES (?,?)', (2, 'test'))
            with connect(Path(directory)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 0)

    def test_record_supports_existing_named_and_positional_reads(self):
        record = Record({'count': 3, 'name': 'fixture'})
        self.assertEqual(record[0], 3)
        self.assertEqual(record['name'], 'fixture')
        self.assertEqual(dict(record), {'count': 3, 'name': 'fixture'})

    def test_remote_settings_require_ssl_and_server_secret(self):
        with self.assertRaises(ValueError):
            CloudSettings('postgresql://user:secret@example.com/db?sslmode=disable').validate()
        with self.assertRaises(ValueError):
            CloudSettings('', 'supabase', 'https://fixture.supabase.co', 'sb_publishable_test').validate()
        secret = CloudSettings('postgresql://user:secret@example.com/db?sslmode=require', 'supabase', 'https://fixture.supabase.co', 'sb_secret_test')
        secret.validate(require_cloud=True)
        self.assertNotIn('sb_secret_test', repr(secret))
        self.assertNotIn('user:secret', repr(secret))
