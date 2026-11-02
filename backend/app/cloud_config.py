"""Backend-only settings. The pending configuration never activates itself."""
from dataclasses import dataclass, field
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from dotenv import dotenv_values, set_key

BACKEND_DIR = Path(__file__).resolve().parents[1]
PENDING_FILE = BACKEND_DIR / '.env.supabase'
ACTIVE_FILE = BACKEND_DIR / '.env.local'


@dataclass(frozen=True)
class CloudSettings:
    database_url: str = field(default='', repr=False)
    storage_provider: str = 'local'
    supabase_url: str = ''
    secret_key: str = field(default='', repr=False)
    bucket: str = 'vetinsight-records'
    schema: str = 'vetinsight'

    @classmethod
    def from_values(cls, values):
        return cls(database_url=values.get('VETINSIGHT_DATABASE_URL', '') or '',
                   storage_provider=values.get('VETINSIGHT_STORAGE_PROVIDER', 'local') or 'local',
                   supabase_url=(values.get('SUPABASE_URL', '') or '').rstrip('/'),
                   secret_key=values.get('SUPABASE_SECRET_KEY', '') or '',
                   bucket=values.get('SUPABASE_BUCKET', 'vetinsight-records') or 'vetinsight-records',
                   schema=values.get('VETINSIGHT_DATABASE_SCHEMA', 'vetinsight') or 'vetinsight')

    def validate(self, require_cloud=False):
        if not re.fullmatch(r'vetinsight(?:_[a-z0-9_]{1,40})?', self.schema):
            raise ValueError('Use a private VetInsight schema.')
        if require_cloud and (not self.database_url or self.storage_provider != 'supabase'):
            raise ValueError('PostgreSQL and Supabase Storage settings are required.')
        if self.database_url:
            uri = urlsplit(self.database_url)
            if uri.scheme not in ('postgres', 'postgresql') or not uri.hostname or not uri.password:
                raise ValueError('A PostgreSQL connection URL with credentials is required.')
            if uri.hostname not in ('localhost', '127.0.0.1', '::1') and parse_qs(uri.query).get('sslmode', [''])[0] not in ('require', 'verify-ca', 'verify-full'):
                raise ValueError('Remote database connections must explicitly configure SSL.')
        if self.storage_provider not in ('local', 'supabase'):
            raise ValueError('Unknown storage provider.')
        if self.storage_provider == 'supabase':
            uri = urlsplit(self.supabase_url)
            if uri.scheme != 'https' or not uri.hostname or not uri.hostname.endswith('.supabase.co') or uri.path or uri.username:
                raise ValueError('Use the HTTPS project URL from Supabase.')
            if not self.secret_key.startswith('sb_secret_'):
                raise ValueError('Use a backend Supabase secret key (sb_secret_), not a publishable key.')
            if not self.bucket or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in self.bucket):
                raise ValueError('Invalid storage bucket name.')


def runtime_settings():
    # Explicit isolated data directories must not inherit the live cloud file.
    values = {} if os.environ.get('VETINSIGHT_DATA_DIR') else dict(dotenv_values(ACTIVE_FILE, interpolate=False))
    values.update(os.environ)
    settings = CloudSettings.from_values(values)
    settings.validate()
    return settings


def pending_settings():
    if not PENDING_FILE.is_file():
        raise ValueError('Run Configure-Supabase.cmd to save the pending credentials locally first.')
    settings = CloudSettings.from_values(dotenv_values(PENDING_FILE, interpolate=False))
    settings.validate(require_cloud=True)
    return settings


def save_settings(path, settings):
    """Atomically persist the exact settings that were verified, without printing them."""
    settings.validate(require_cloud=True)
    temporary = Path(str(path) + '.tmp')
    temporary.write_text('', encoding='utf-8')
    for name, value in {'VETINSIGHT_DATABASE_URL': settings.database_url, 'VETINSIGHT_STORAGE_PROVIDER': settings.storage_provider,
                        'SUPABASE_URL': settings.supabase_url, 'SUPABASE_SECRET_KEY': settings.secret_key,
                        'SUPABASE_BUCKET': settings.bucket, 'VETINSIGHT_DATABASE_SCHEMA': settings.schema}.items():
        set_key(temporary, name, value)
    os.replace(temporary, path)
