"""MIDOG 2022 canine histology audit. Source boxes are xyxy, not COCO xywh."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
RECORD_URL = 'https://zenodo.org/api/records/6547151'
ANNOTATIONS = 'MIDOG2022_training_png.json'
EXPECTED_MD5 = '83002a6cc8c9a1de890fd6b7fcc04686'
DOMAINS = ((151, 194, 'canine lung carcinoma'), (195, 249, 'canine lymphoma'),
           (250, 299, 'canine mast cell tumor'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def domain(image_id):
    return next((name for lo, hi, name in DOMAINS if lo <= image_id <= hi), None)


def xywh(box, width, height):
    if len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
        raise ValueError('Expected four finite source corner coordinates.')
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        raise ValueError('Source box has no area.')
    clipped = [max(0, x1), max(0, y1), min(width, x2), min(height, y2)]
    a, b, c, d = clipped
    if c <= a or d <= b:
        raise ValueError('Source box lies outside image.')
    return [a, b, c - a, d - b], clipped != list(box)


def convert(data, case_ids):
    """Single positive class; source category 2 is retained as hard-negative metadata."""
    categories = {c['id']: c['name'] for c in data['categories']}
    if categories != {1: 'mitotic figure', 2: 'not mitotic figure'}:
        raise ValueError('Unexpected source categories; review schema before importing.')
    images = {i['id']: i for i in data['images']}
    if len(images) != len(data['images']) or not case_ids or len(set(case_ids)) != len(case_ids):
        raise ValueError('Duplicate image IDs or empty/duplicate case selection.')
    if any(i not in images or domain(i) is None for i in case_ids):
        raise ValueError('Select known canine cases only.')
    selected = set(case_ids)
    out = {'info': {'task': 'canine histology mitosis detection', 'source_bbox': 'xyxy',
                    'split_unit': 'source case/ROI; patient independence unverified'},
           'images': [], 'annotations': [], 'hard_negatives': [],
           'categories': [{'id': 1, 'name': 'mitotic figure'}]}
    for i in sorted(selected):
        item = images[i]
        if type(item['width']) is not int or type(item['height']) is not int or min(item['width'], item['height']) <= 0:
            raise ValueError('Invalid image dimensions.')
        out['images'].append({'id': i, 'file_name': item['file_name'], 'width': item['width'],
                              'height': item['height'], 'case_id': i, 'domain': domain(i)})
    seen = set()
    clipped = 0
    for a in data['annotations']:
        if a['id'] in seen or a['image_id'] not in images or a['category_id'] not in categories:
            raise ValueError('Duplicate annotation ID or unknown image/category.')
        seen.add(a['id'])
        if a['image_id'] not in selected:
            continue
        im = images[a['image_id']]
        box, changed = xywh(a['bbox'], im['width'], im['height'])
        clipped += changed
        target = 'annotations' if a['category_id'] == 1 else 'hard_negatives'
        out[target].append({'id': a['id'], 'image_id': a['image_id'], 'category_id': a['category_id'],
                            'bbox': box, 'area': box[2] * box[3], 'iscrowd': 0})
    return out, clipped


def audit(path):
    raw = Path(path).read_bytes()
    if hashlib.md5(raw).hexdigest() != EXPECTED_MD5:
        raise ValueError('Annotation checksum mismatch; source version requires review.')
    data = json.loads(raw)
    ids = [i['id'] for i in data['images'] if domain(i['id'])]
    converted, clipped = convert(data, ids)
    counts = Counter((domain(a['image_id']), a['category_id']) for a in data['annotations'] if a['image_id'] in ids)
    return {'source': RECORD_URL, 'annotation_md5': EXPECTED_MD5,
            'annotation_sha256': hashlib.sha256(raw).hexdigest(),
            'source_image_count': len(data['images']), 'canine_case_count': len(ids),
            'positive_boxes': len(converted['annotations']), 'hard_negative_boxes': len(converted['hard_negatives']),
            'clipped_border_boxes': clipped,
            'domains': {name: {'cases': sum(domain(i) == name for i in ids),
                              'positive_boxes': counts[name, 1], 'hard_negative_boxes': counts[name, 2]}
                        for _, _, name in DOMAINS},
            'source_bbox_format': 'xyxy; explicitly converted to xywh',
            'embedded_licenses': data.get('licenses'), 'zenodo_record_license': 'cc-by-4.0',
            'readiness': 'NOT READY: conflicting license metadata; patient mapping not established',
            'scope': 'Histology only. No cytology or clinical diagnostic performance established.'}


def require_rights(path):
    rights = json.loads(Path(path).read_text(encoding='utf-8'))
    if rights.get('status') != 'verified' or rights.get('image_preparation_permitted') is not True or not rights.get('evidence', '').strip():
        raise ValueError('Image preparation blocked: documented applicable image-use terms required.')


def fetch_metadata():
    with urlopen(RECORD_URL, timeout=60) as response:
        record = json.load(response)
    entry = next(f for f in record['files'] if f['key'] == ANNOTATIONS)
    if entry['checksum'] != 'md5:' + EXPECTED_MD5 or entry['size'] > 3_000_000:
        raise ValueError('Unexpected source version or metadata size.')
    with urlopen(entry['links']['self'], timeout=60) as response:
        raw = response.read(3_000_001)
    if len(raw) != entry['size'] or hashlib.md5(raw).hexdigest() != EXPECTED_MD5:
        raise ValueError('Source length/checksum mismatch.')
    write(ROOT / 'metadata/zenodo-record.json', record)
    target = ROOT / 'metadata' / ANNOTATIONS
    target.write_bytes(raw)
    return target


def prepare(source, images_dir, output, cases, rights):
    require_rights(rights)
    audit(source)  # Pin the source version before interpreting coordinates.
    data, clipped = convert(json.loads(Path(source).read_bytes()), cases)
    from PIL import Image
    base = Path(images_dir).resolve()
    for item in data['images']:
        path = (base / item['file_name']).resolve()
        if not path.is_relative_to(base):
            raise ValueError('Source filename escapes image directory.')
        with Image.open(path) as im:
            if im.size != (item['width'], item['height']):
                raise ValueError('Image dimensions do not match annotations.')
        item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    data['info']['clipped_border_boxes'] = clipped
    write(output, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['fetch-metadata', 'audit', 'prepare'])
    parser.add_argument('--source', type=Path, default=ROOT / 'metadata' / ANNOTATIONS)
    parser.add_argument('--images', type=Path, default=ROOT / 'raw')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cases', type=int, nargs='+', default=[250, 251, 252])
    parser.add_argument('--rights', type=Path, default=ROOT / 'rights-review.json')
    args = parser.parse_args()
    if args.command == 'fetch-metadata':
        print(fetch_metadata())
    elif args.command == 'audit':
        report = audit(args.source)
        write(args.output or ROOT / 'reports/annotation-audit.json', report)
        print(json.dumps(report, indent=2))
    else:
        try:
            prepare(args.source, args.images, args.output or ROOT / 'derived/canine.json', args.cases, args.rights)
        except ValueError as error:
            parser.error(str(error))


if __name__ == '__main__':
    main()
