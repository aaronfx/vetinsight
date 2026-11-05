"""Pin and download a case-grouped MIDOG++ development cohort."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
SPLITS = {'train': [250, 254, 255, 258, 259, 260], 'validation': [261, 263], 'test': [253, 256, 257]}
REVIEW = ROOT / 'reports/cohort-source-review.json'


def get_json(url):
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def verify(path, entry):
    checksum = hashlib.md5()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    if path.stat().st_size != entry['bytes'] or checksum.hexdigest() != entry['md5']:
        raise ValueError('Published length or MD5 mismatch for ' + entry['name'])


def pin():
    if REVIEW.exists():
        raise ValueError('Cohort is already pinned. Preserve its review and case selection.')
    source_path = ROOT / 'metadata/MIDOGpp.json'
    source = json.loads(source_path.read_bytes())
    expected = '686c91bcabcc079a000a5be13cc2f542'
    if hashlib.md5(source_path.read_bytes()).hexdigest() != expected or source['licenses'][0]['name'] != 'CC0':
        raise ValueError('Unexpected annotation source or embedded license.')
    with (ROOT / 'metadata/midogpp-splits.csv').open() as stream:
        original_splits = {int(row['Slide']): row for row in csv.DictReader(stream, delimiter=';')}
    images = {image['id']: image for image in source['images']}
    for split, case_ids in SPLITS.items():
        for case_id in case_ids:
            if images[case_id]['tumor_type'] != 'canine lymphosarcoma':
                raise ValueError('Unexpected specimen domain.')
            expected_split = 'test' if split == 'test' else 'train'
            if original_splits[case_id]['Dataset'] != expected_split:
                raise ValueError('Cohort contradicts author train/test assignment.')
    notebook = json.loads((ROOT / 'metadata/midogpp-setup.ipynb').read_text())
    mapping_cell = next(''.join(c.get('source', [])) for c in notebook['cells']
                        if ''.join(c.get('source', [])).startswith('filename = {'))
    mapping = ast.literal_eval(mapping_cell.split('=', 1)[1].strip())
    file_ids = {name: file_id for file_id, name in mapping.items()}
    articles = json.loads((ROOT / 'metadata/midogpp-collection-articles.json').read_text())
    selected = [images[case_id]['file_name'] for ids in SPLITS.values() for case_id in ids]
    article_urls = []
    for name in selected:
        file_id = file_ids[name]
        article = next(a for a in articles if '/' + file_id + '/' in a.get('thumb', ''))
        article_urls.append(article['url'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(get_json, article_urls))
    files = []
    for name, record in zip(selected, records):
        if record['license']['name'] != 'CC0':
            raise ValueError('Image record lacks matching CC0 terms for ' + name)
        item = next(f for f in record['files'] if f['name'] == name)
        if item['size'] > 160_000_000:
            raise ValueError('Unexpected source image size.')
        files.append({'name': name, 'bytes': item['size'], 'md5': item['computed_md5'],
                      'download_url': item['download_url'], 'article_url': record['url_public_html'],
                      'article_id': record['id'], 'license_url': record['license']['url']})
    annotation_record = get_json('https://api.figshare.com/v2/articles/23531121')
    if annotation_record['license']['name'] != 'CC0':
        raise ValueError('Annotation record terms changed.')
    review = {'release': 'MIDOG++', 'verified_on': '2026-11-04', 'cases': SPLITS,
              'selection': 'Fixed case IDs before training. Validation drawn from author train cases. New test excludes prior pilot test cases 251 and 252.',
              'split_unit': 'Source case/ROI; patient linkage unverified',
              'annotation_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
              'split_source_sha256': hashlib.sha256((ROOT / 'metadata/midogpp-splits.csv').read_bytes()).hexdigest(),
              'annotation_article_url': annotation_record['url_public_html'],
              'annotation_license': annotation_record['license'], 'selected_files': files,
              'total_image_bytes': sum(f['bytes'] for f in files)}
    REVIEW.write_text(json.dumps(review, indent=2) + '\n')
    (ROOT / 'metadata/cohort-records.json').write_text(json.dumps(records + [annotation_record]))
    print(json.dumps({'cases': SPLITS, 'total_image_bytes': review['total_image_bytes']}), flush=True)


def fetch():
    review = json.loads(REVIEW.read_text())
    folder = ROOT / 'raw/midogpp'
    folder.mkdir(parents=True, exist_ok=True)
    if review['cases'] != SPLITS or review['total_image_bytes'] > 1_600_000_000:
        raise ValueError('Unexpected cohort or download budget.')

    def download(entry):
        if entry['license_url'] != 'https://creativecommons.org/publicdomain/zero/1.0/' or Path(entry['name']).name != entry['name']:
            raise ValueError('Unexpected filename or terms.')
        path = folder / entry['name']
        if path.exists():
            verify(path, entry)
            print('Verified existing ' + path.name, flush=True)
            return
        partial = path.with_suffix('.tiff.partial')
        for attempt in range(3):
            try:
                size = 0
                url = entry['download_url'] + '?cohort=vetinsight&attempt=' + str(attempt)
                with urlopen(url, timeout=90) as response, partial.open('wb') as stream:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > entry['bytes']:
                            raise ValueError('Download exceeds reviewed size.')
                        stream.write(chunk)
                verify(partial, entry)
                partial.replace(path)
                print('Downloaded and verified ' + path.name, flush=True)
                return
            except (OSError, TimeoutError) as error:
                if attempt == 2:
                    raise
                print('Retrying ' + path.name + ' after ' + type(error).__name__, flush=True)
                time.sleep(2)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, review['selected_files']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['pin', 'fetch'])
    args = parser.parse_args()
    pin() if args.command == 'pin' else fetch()
