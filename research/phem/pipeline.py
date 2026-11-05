"""Offline P-Hem data audit and bounded whole-slide patch preparation.

No API, unpickling, upstream notebook execution, training, or production writes.
"""
import argparse
import ast
from collections import Counter, defaultdict
from contextlib import closing
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
GRADES = tuple(range(5))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def annotations(path, slide=None):
    if Path(path).suffix == '.sqlite':
        yield from sqlite_annotations(path, slide)
        return
    seen = set()
    required = {'unique_identifier', 'species', 'image_name', 'grade', 'vector', 'version'}
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Annotation CSV is missing required columns.')
        for line, row in enumerate(reader, 2):
            if slide is not None and row['image_name'] != slide:
                continue
            uid = row['unique_identifier']
            if not uid or uid in seen:
                raise ValueError(f'Empty or duplicate annotation ID at row {line}.')
            seen.add(uid)
            grade = int(row['grade'])
            if grade not in GRADES or row['version'] != 'Density':
                raise ValueError(f'Unexpected grade or annotation version at row {line}.')
            # The authors serialize a four-number dict in this CSV. Never eval it.
            if len(row['vector']) > 500:
                raise ValueError(f'Oversized vector at row {line}.')
            vector = ast.literal_eval(row['vector'])
            if not isinstance(vector, dict) or set(vector) != {'x1', 'y1', 'x2', 'y2'}:
                raise ValueError(f'Unexpected vector fields at row {line}.')
            values = [vector[key] for key in ('x1', 'y1', 'x2', 'y2')]
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError(f'Invalid coordinates at row {line}.')
            x1, y1, x2, y2 = values
            if min(x1, y1) < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError(f'Invalid box at row {line}.')
            if Path(row['image_name']).name != row['image_name']:
                raise ValueError('Slide names must be plain filenames.')
            yield {'id': uid, 'species': row['species'].lower(), 'slide': row['image_name'],
                   'grade': grade, 'box': [x1, y1, x2, y2]}


def sqlite_annotations(path, slide=None):
    species = {}
    with Path(path).with_name('images_meta_data.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            name, value = row['file'], row['species'].lower()
            if name in species and species[name] != value:
                raise ValueError('Inconsistent species metadata.')
            species[name] = value
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        query = '''SELECT a.uid,s.filename,k.name,MIN(c.coordinateX),MIN(c.coordinateY),
                   MAX(c.coordinateX),MAX(c.coordinateY),COUNT(c.uid)
                   FROM Annotations a JOIN Slides s ON s.uid=a.slide
                   JOIN Classes k ON k.uid=a.agreedClass
                   LEFT JOIN Annotations_coordinates c ON c.annoId=a.uid AND c.slide=a.slide
                   WHERE a.deleted=0 AND (? IS NULL OR s.filename=?)
                   GROUP BY a.uid ORDER BY a.uid'''
        for uid, name, category, x1, y1, x2, y2, count in db.execute(query, (slide, slide)):
            grade = int(category)
            if name not in species or grade not in GRADES or count != 2:
                raise ValueError('SQLite annotation has missing metadata or unexpected geometry.')
            values = (x1, y1, x2, y2)
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError('Invalid SQLite coordinates.')
            if min(x1, y1) < 0 or x2 <= x1 or y2 <= y1 or Path(name).name != name:
                raise ValueError('Invalid SQLite annotation box/slide name.')
            yield {'id': f'sqlite-{uid}', 'species': species[name], 'slide': name,
                   'grade': grade, 'box': list(values)}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def audit(csv_path, output):
    species = Counter()
    grades = Counter()
    slides = defaultdict(Counter)
    slide_species = {}
    for row in annotations(csv_path):
        species[row['species']] += 1
        grades[row['grade']] += 1
        slides[row['slide']][row['grade']] += 1
        if row['slide'] in slide_species and slide_species[row['slide']] != row['species']:
            raise ValueError('A slide has inconsistent species labels.')
        slide_species[row['slide']] = row['species']
    result = {'source_sha256': digest(csv_path), 'annotation_version': 'Density',
              'total_annotations': sum(species.values()), 'total_slides': len(slides),
              'annotations_by_species': dict(species), 'annotations_by_grade': dict(sorted(grades.items())),
              'slides_by_species': dict(Counter(slide_species.values())),
              'patient_grouping': 'UNVERIFIED: no verified patient map available; no evaluation split created.',
              'slides': [{'slide': name, 'species': slide_species[name],
                          'annotations': sum(counts.values()), 'grades': dict(sorted(counts.items()))}
                         for name, counts in sorted(slides.items())]}
    write_json(output, result)
    return result


def csv_quality(csv_path, output):
    identifiers, malformed, bad_ids = Counter(), Counter(), set()
    with Path(csv_path).open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            identifiers[row['unique_identifier']] += 1
            try:
                if len(row['vector']) > 500:
                    raise ValueError('Oversized coordinate field')
                vector = ast.literal_eval(row['vector'])
                if not isinstance(vector, dict) or set(vector) != {'x1', 'y1', 'x2', 'y2'}:
                    raise ValueError('Invalid coordinate fields')
            except (ValueError, SyntaxError):
                malformed[row['species']] += 1
                bad_ids.add(row['unique_identifier'])
    result = {'source_sha256': digest(csv_path), 'csv_rows': sum(identifiers.values()),
              'unique_csv_ids': len(identifiers), 'malformed_coordinate_rows': sum(malformed.values()),
              'malformed_unique_ids': len(bad_ids), 'malformed_rows_by_species': dict(malformed),
              'duplicate_id_count': sum(value > 1 for value in identifiers.values()),
              'policy': 'Strict import rejects malformed vectors and duplicate IDs. SQLite is a separate author source, not a silent repair.'}
    write_json(output, result)
    return result


def clipped_box(box, x, y, width, height):
    x1, y1, x2, y2 = box
    a, b, c, d = max(x1, x), max(y1, y), min(x2, x + width), min(y2, y + height)
    if c <= a or d <= b:
        return None
    return [a - x, b - y, c - a, d - b]


def prepare(csv_path, slide_path, output, limit=8, size=1024):
    import openslide
    from PIL import Image, ImageDraw

    if not 1 <= limit <= 64 or not 256 <= size <= 2048:
        raise ValueError('Use 1–64 smoke patches, sized 256–2048 pixels.')
    output = Path(output)
    # Immutable runs make it impossible to silently mix old patches/new labels.
    if output.exists():
        raise ValueError('Output already exists. Choose a new run directory.')
    rows = sorted(annotations(csv_path, Path(slide_path).name), key=lambda item: item['id'])
    if not rows or any(row['species'] == 'human' for row in rows):
        raise ValueError('Choose a veterinary slide with matching annotations.')
    with openslide.OpenSlide(str(slide_path)) as slide:
        width, height = slide.dimensions
        if width < size or height < size:
            raise ValueError('Slide is smaller than requested patch size.')
        if any(row['box'][2] > width or row['box'][3] > height for row in rows):
            raise ValueError('Annotation coordinates exceed level-0 slide dimensions.')
        # Deterministic annotation-centred smoke regions; not a representative sample.
        origins = []
        for row in rows:
            x1, y1, x2, y2 = row['box']
            x = max(0, min(width - size, int((x1 + x2) / 2) - size // 2))
            y = max(0, min(height - size, int((y1 + y2) / 2) - size // 2))
            if all(abs(x - a) >= size or abs(y - b) >= size for a, b in origins):
                origins.append((x, y))
            if len(origins) == limit:
                break
        output.mkdir(parents=True)
        (output / 'images').mkdir()
        coco = {'info': {'description': 'P-Hem veterinary smoke patches; not a training/evaluation split'},
                'images': [], 'annotations': [],
                'categories': [{'id': grade + 1, 'name': f'hemosiderophage_grade_{grade}'} for grade in GRADES]}
        tiles = []
        for image_id, (x, y) in enumerate(origins, 1):
            patch = slide.read_region((x, y), 0, (size, size)).convert('RGB')
            filename = f'images/patch-{image_id:03d}.png'
            patch.save(output / filename)
            coco['images'].append({'id': image_id, 'file_name': filename, 'width': size, 'height': size,
                                   'source_slide': Path(slide_path).name, 'origin_level0': [x, y],
                                   'split': 'smoke_only', 'patient_id': None})
            display = patch.copy()
            drawing = ImageDraw.Draw(display)
            for row in rows:
                box = clipped_box(row['box'], x, y, size, size)
                if box is None:
                    continue
                bx, by, bw, bh = box
                truncated = row['box'][0] < x or row['box'][1] < y or row['box'][2] > x + size or row['box'][3] > y + size
                coco['annotations'].append({'id': len(coco['annotations']) + 1, 'image_id': image_id,
                    'category_id': row['grade'] + 1, 'bbox': box, 'area': bw * bh, 'iscrowd': 0,
                    'source_annotation_id': row['id'], 'truncated': truncated})
                drawing.rectangle((bx, by, bx + bw, by + bh), outline='#ef4444', width=3)
                drawing.text((bx, by), str(row['grade']), fill='#ef4444')
            display.thumbnail((384, 384))
            tiles.append(display)
        columns = min(4, len(tiles))
        montage = Image.new('RGB', (columns * 384, math.ceil(len(tiles) / columns) * 410), 'white')
        drawing = ImageDraw.Draw(montage)
        for index, tile in enumerate(tiles):
            x, y = index % columns * 384, index // columns * 410
            montage.paste(tile, (x, y + 24))
            drawing.text((x + 4, y + 4), f'Patch {index + 1}: SOURCE labels, no predictions', fill='black')
        montage.save(output / 'source-labels-contact-sheet.png')
        manifest = {'purpose': 'Import/coordinate smoke test only; no model or clinical results.',
                    'dataset_citation': 'Marzahl et al., Scientific Data 9, 269 (2022), doi:10.1038/s41597-022-01389-0',
                    'slide': Path(slide_path).name, 'slide_sha256': digest(slide_path),
                    'annotation_sha256': digest(csv_path), 'level0_dimensions': [width, height],
                    'patch_count': len(origins), 'patch_size': size, 'annotation_count': len(coco['annotations']),
                    'source_slide_annotations': len(rows), 'species': rows[0]['species'],
                    'image_license': 'UNVERIFIED; no redistribution or training approved by this pipeline.',
                    'patient_grouping': 'UNVERIFIED; all patches remain one smoke-only slide group.',
                    'sampling': 'Source-ID-sorted cell-centred, non-overlapping patches; biased sample, not an evaluation set.',
                    'coordinates': 'Level-0 pixels, COCO xywh; all intersecting labels retained and clipped at patch boundaries.',
                    'image_hashes': {item['file_name']: digest(output / item['file_name']) for item in coco['images']}}
        write_json(output / 'annotations.json', coco)
        write_json(output / 'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('audit')
    check.add_argument('--annotations', '--csv', dest='csv', type=Path, default=ROOT / 'metadata/SDATA_Final_Annotations.sqlite')
    check.add_argument('--output', type=Path, default=ROOT / 'reports/annotation-audit.json')
    quality = sub.add_parser('csv-quality')
    quality.add_argument('--csv', type=Path, default=ROOT / 'metadata/SDATA_Final_Annotations.csv')
    quality.add_argument('--output', type=Path, default=ROOT / 'reports/csv-quality.json')
    patches = sub.add_parser('patches')
    patches.add_argument('--annotations', '--csv', dest='csv', type=Path, default=ROOT / 'metadata/SDATA_Final_Annotations.sqlite')
    patches.add_argument('--slide', type=Path, required=True)
    patches.add_argument('--output', type=Path, required=True)
    patches.add_argument('--limit', type=int, default=8)
    patches.add_argument('--size', type=int, default=1024)
    args = parser.parse_args()
    if args.command == 'audit':
        result = audit(args.csv, args.output)
        print(json.dumps({key: value for key, value in result.items() if key != 'slides'}, indent=2))
    elif args.command == 'csv-quality':
        print(json.dumps(csv_quality(args.csv, args.output), indent=2))
    else:
        print(json.dumps(prepare(args.csv, args.slide, args.output, args.limit, args.size), indent=2))


if __name__ == '__main__':
    main()
