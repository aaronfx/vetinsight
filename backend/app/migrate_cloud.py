"""Offline, backed-up migration. Never overwrites existing cloud records."""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3

from fastapi import HTTPException

from .cloud_config import ACTIVE_FILE, BACKEND_DIR, pending_settings, save_settings
from .database import TABLES, DatabaseError, connect
from .object_storage import ObjectStorage


class MigrationError(Exception):
    pass


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def rows(db):
    return {table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in TABLES}


def fingerprint(snapshot, files):
    return hashlib.sha256(json.dumps({'tables': snapshot, 'files': files}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_rows(db, expected):
    actual = rows(db)
    for table in TABLES:
        if actual[table] != expected[table]:
            raise MigrationError(f'Cloud verification failed for {table}. Activation refused.')


@contextmanager
def require_offline(port=8000):
    # Hold the loopback port so the app cannot start while the snapshot is copied.
    guard = socket.socket()
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        guard.bind(('127.0.0.1', port))
    except OSError:
        guard.close()
        raise MigrationError('Stop the local backend before migration. No cloud records were changed.') from None
    try:
        yield
    finally:
        guard.close()


def migrate(source_dir, settings, backup_root, activate=False):
    from .main import initialize_database
    settings.validate(require_cloud=True)
    if not (source_dir / 'vetinsight.sqlite3').is_file():
        raise MigrationError('The source SQLite database does not exist.')
    store = ObjectStorage(source_dir, settings)
    # Validate connectivity and bucket privacy before reading any source content remotely.
    with connect(source_dir, settings.database_url, settings.schema) as db:
        initialize_database(db)
    store.ensure_private_bucket(create=True)

    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_dir = backup_root / name
    backup_dir.mkdir(parents=True, exist_ok=False)
    source = sqlite3.connect(source_dir / 'vetinsight.sqlite3', timeout=10)
    source.row_factory = sqlite3.Row
    try:
        source.execute('BEGIN')
        snapshot = rows(source)
        with closing(sqlite3.connect(backup_dir / 'vetinsight.sqlite3')) as backup:
            source.backup(backup)
        hashes = {}
        (backup_dir / 'uploads').mkdir()
        for upload in snapshot['uploads']:
            filename = store.checked_name(upload['storage_name'])
            original = source_dir / 'uploads' / filename
            if not original.is_file() or original.stat().st_size != upload['size_bytes']:
                raise MigrationError(f'Upload {upload["id"]} is missing or has an unexpected size. Activation refused.')
            hashes[filename] = digest(original)
            shutil.copy2(original, backup_dir / 'uploads' / filename)
        source_hash = fingerprint(snapshot, hashes)
        manifest = {'created_at': name, 'source_fingerprint': source_hash,
                    'row_counts': {table: len(items) for table, items in snapshot.items()},
                    'file_sha256': hashes, 'activated': False}
        (backup_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'Local backup created: {backup_dir}', flush=True)

        with connect(source_dir, settings.database_url, settings.schema) as db:
            existing = any(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in TABLES)
            if existing:
                check_rows(db, snapshot)
                print('Cloud rows already match this source; verifying files without overwriting.', flush=True)
        for upload in snapshot['uploads']:
            filename = upload['storage_name']
            try:
                with store.local_copy(filename) as downloaded:
                    if digest(downloaded) != hashes[filename]:
                        raise MigrationError(f'Cloud object for upload {upload["id"]} differs. No object was overwritten.')
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                store.upload(filename, backup_dir / 'uploads' / filename, upload['content_type'])
            with store.local_copy(filename) as downloaded:
                if digest(downloaded) != hashes[filename]:
                    raise MigrationError(f'Byte verification failed for upload {upload["id"]}.')
        with connect(source_dir, settings.database_url, settings.schema) as db:
            db.execute('BEGIN IMMEDIATE')
            # Check again after uploads; another process might have written in the meantime.
            populated = any(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in TABLES)
            if populated:
                check_rows(db, snapshot)
            else:
                for table in TABLES:
                    for item in snapshot[table]:
                        columns = ','.join(item)
                        markers = ','.join('?' for _ in item)
                        db.execute(f'INSERT INTO {table} ({columns}) VALUES ({markers})', tuple(item.values()))
                for table in ('cases', 'uploads', 'users', 'audit_events'):
                    highest = max((item['id'] for item in snapshot[table]), default=0)
                    db.raw.execute('SELECT setval(pg_get_serial_sequence(%s,%s),%s,%s)',
                                   (f'{settings.schema}.{table}', 'id', highest or 1, highest > 0))
            check_rows(db, snapshot)
        with connect(source_dir, settings.database_url, settings.schema) as db:
            check_rows(db, snapshot)
        # Verify originals still match the exact backed-up source.
        for filename, expected_hash in hashes.items():
            if digest(source_dir / 'uploads' / filename) != expected_hash:
                raise MigrationError('A local original changed during migration. Activation refused.')
        print('Verified all database rows and original upload SHA-256 hashes.', flush=True)
        if activate:
            if ACTIVE_FILE.exists():
                shutil.copy2(ACTIVE_FILE, backup_dir / 'previous.env.local')
            save_settings(ACTIVE_FILE, settings)
            manifest['activated'] = True
            print('Cloud configuration activated. Start the backend to use Supabase.', flush=True)
        (backup_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return manifest
    finally:
        source.rollback(); source.close()


def main():
    parser = argparse.ArgumentParser(description='Back up and migrate VetInsight to Supabase while the backend is stopped.')
    parser.add_argument('--activate', action='store_true', help='Switch local backend settings only after every verification passes.')
    args = parser.parse_args()
    try:
        settings = pending_settings()
        with require_offline():
            migrate(BACKEND_DIR / 'data', settings, BACKEND_DIR / 'backups', args.activate)
    except (MigrationError, DatabaseError, ValueError, HTTPException, OSError):
        # Never print raw connection exceptions, API responses or credentials.
        print('Migration did not complete. The running configuration was not switched unless activation was already reported. Check credentials/network, bucket privacy, source file sizes and whether cloud tables already contain different data. Local data and backups remain available.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
