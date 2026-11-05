"""Download only the recorded P-Hem files, with size/hash checks. No code execution."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent


def fetch(record):
    target = (ROOT / record['local_path']).resolve()
    if not target.is_relative_to(ROOT.resolve()):
        raise ValueError('Destination must remain inside the dataset directory.')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with target.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if checksum != record['sha256']:
            raise ValueError(f'Existing file checksum differs: {target.name}')
        print(f'Verified existing {target.name}')
        return
    temporary = target.with_suffix(target.suffix + '.partial')
    hasher, length = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(record['url'], timeout=45) as response, temporary.open('wb') as stream:
            while chunk := response.read(1024 * 1024):
                length += len(chunk)
                if length > record['size_bytes']:
                    raise ValueError('Download exceeded the recorded size.')
                hasher.update(chunk)
                stream.write(chunk)
        if length != record['size_bytes'] or hasher.hexdigest() != record['sha256']:
            raise ValueError('Download size/checksum differs from recorded source. Review upstream changes.')
        temporary.replace(target)
        print(f'Downloaded and verified {target.name}: {length} bytes')
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-smoke-slide', action='store_true', help='Also fetch the single 238 MB veterinary slide for local inspection. Image license remains unverified.')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'sources.json').read_text(encoding='utf-8'))
    for record in manifest['files']:
        if record['kind'] == 'image' and not args.include_smoke_slide:
            continue
        fetch(record)


if __name__ == '__main__':
    main()
