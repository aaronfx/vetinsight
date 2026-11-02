"""Private storage; originals are always served through the authenticated API."""
from contextlib import contextmanager
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import httpx
from starlette.background import BackgroundTask

MAX_BYTES = 20 * 1024 * 1024


class ObjectStorage:
    def __init__(self, data_dir, settings, transport=None):
        self.directory, self.settings, self.transport = data_dir / 'uploads', settings, transport

    @property
    def remote(self):
        return self.settings.storage_provider == 'supabase'

    def checked_name(self, name):
        if not re.fullmatch(r'[a-f0-9]{32}\.(?:pdf|png|jpg|jpeg)', name):
            raise HTTPException(404, 'Uploaded file is missing from storage.')
        return name

    def local_path(self, name):
        path = (self.directory / self.checked_name(name)).resolve()
        if path.parent != self.directory.resolve() or not path.is_file():
            raise HTTPException(404, 'Uploaded file is missing from storage.')
        return path

    def client(self):
        # sb_secret keys belong in apikey, not a JWT Authorization header.
        return httpx.Client(base_url=f'{self.settings.supabase_url}/storage/v1',
                            headers={'apikey': self.settings.secret_key}, transport=self.transport,
                            timeout=httpx.Timeout(60, connect=10), trust_env=False, follow_redirects=False)

    def object_path(self, name):
        return f'/object/{self.settings.bucket}/records/{self.checked_name(name)}'

    def download_path(self, name):
        return f'/object/authenticated/{self.settings.bucket}/records/{self.checked_name(name)}'

    def ensure_private_bucket(self, create=False):
        if not self.remote:
            return
        try:
            with self.client() as client:
                response = client.get(f'/bucket/{self.settings.bucket}')
                if response.status_code == 404 and create:
                    response = client.post('/bucket', json={'id': self.settings.bucket, 'name': self.settings.bucket, 'public': False,
                        'file_size_limit': MAX_BYTES, 'allowed_mime_types': ['application/pdf', 'image/png', 'image/jpeg']})
                    if response.is_success:
                        response = client.get(f'/bucket/{self.settings.bucket}')
                if not response.is_success:
                    raise HTTPException(503, 'Private storage bucket is unavailable. Check the server configuration.')
                if response.json().get('public') is not False:
                    raise HTTPException(503, 'Storage bucket must be private. Startup refused.')
        except httpx.HTTPError:
            raise HTTPException(503, 'Cannot reach private storage.') from None

    def upload(self, name, source, content_type):
        self.checked_name(name)
        if not self.remote:
            raise ValueError('Remote upload requested in local mode.')
        try:
            with self.client() as client, source.open('rb') as stream:
                response = client.post(self.object_path(name), content=stream,
                    headers={'Content-Type': content_type, 'x-upsert': 'false'})
                if not response.is_success:
                    raise HTTPException(503, 'Private upload failed. The case remains saved; retry the attachment.')
        except httpx.HTTPError:
            raise HTTPException(503, 'Cannot reach private storage. Retry the attachment.') from None

    def delete(self, name):
        try:
            with self.client() as client:
                response = client.request('DELETE', f'/object/{self.settings.bucket}', json={'prefixes': [f'records/{self.checked_name(name)}']})
                if not response.is_success:
                    raise HTTPException(503, 'Private upload cleanup failed.')
        except httpx.HTTPError:
            raise HTTPException(503, 'Private upload cleanup failed.') from None

    @contextmanager
    def local_copy(self, name):
        self.checked_name(name)
        if not self.remote:
            path = self.local_path(name)
            yield path
            return
        with TemporaryDirectory(prefix='vetinsight-read-') as temporary:
            path = Path(temporary) / name
            try:
                with self.client() as client, client.stream('GET', self.download_path(name)) as response:
                    self.check_download(response)
                    total = 0
                    with path.open('wb') as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            total += len(chunk)
                            if total > MAX_BYTES:
                                raise HTTPException(413, 'Stored file exceeds the supported size.')
                            output.write(chunk)
            except httpx.HTTPError:
                raise HTTPException(503, 'Cannot retrieve the private file.') from None
            yield path

    @staticmethod
    def check_download(response):
        if response.status_code in (400, 404):
            raise HTTPException(404, 'Uploaded file is missing from storage.')
        if not response.is_success:
            raise HTTPException(503, 'Private file storage is unavailable.')

    def response(self, row, headers, inline=False):
        name = self.checked_name(row['storage_name'])
        disposition = 'inline' if inline else 'attachment'
        if not self.remote:
            path = self.local_path(name)
            return FileResponse(path, media_type=row['content_type'], filename=row['filename'],
                                content_disposition_type=disposition, headers=headers)
        client = self.client()
        try:
            response = client.send(client.build_request('GET', self.download_path(name)), stream=True)
            self.check_download(response)
        except httpx.HTTPError:
            client.close()
            raise HTTPException(503, 'Cannot retrieve the private file.') from None
        except BaseException:
            client.close()
            raise
        def close():
            response.close(); client.close()
        def stream():
            try:
                total = 0
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise RuntimeError('Stored file exceeds the supported size.')
                    yield chunk
            finally:
                close()
        delivery = {**headers, 'Content-Disposition': f"{disposition}; filename*=utf-8''{quote(row['filename'], safe='')}"}
        return StreamingResponse(stream(), media_type=row['content_type'], headers=delivery, background=BackgroundTask(close))
