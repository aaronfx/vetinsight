"""Validated COCO input and reproducible geometry fixtures for detector software QA."""
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import random

from PIL import Image, ImageDraw

from pipeline import digest, write_json

CATEGORIES = [{'id': grade + 1, 'name': f'hemosiderophage_grade_{grade}'} for grade in range(5)]
SYNTHETIC = 'SYNTHETIC_GEOMETRY_NOT_CYTOLOGY'


def generate(root):
    root = Path(root)
    if root.exists():
        raise ValueError('Fixture directory already exists; choose a fresh path.')
    root.mkdir(parents=True)
    (root / 'images').mkdir()
    rng = random.Random(42)
    image_id = 0
    for split, count in [('train', 2), ('validation', 1), ('test', 1)]:
        data = {'info': {'dataset_kind': SYNTHETIC, 'generator_seed': 42},
                'categories': CATEGORIES, 'images': [], 'annotations': []}
        for _ in range(count):
            image_id += 1
            image = Image.new('RGB', (128, 128), (245, 245, rng.randrange(220, 245)))
            drawing = ImageDraw.Draw(image)
            for grade in range(5):
                x = 6 + grade % 3 * 40 + rng.randrange(3)
                y = 6 + grade // 3 * 55 + rng.randrange(6)
                drawing.ellipse((x, y, x + 20, y + 24), fill=(40 + grade * 35, 30 + image_id * 13, 180 - grade * 20))
                data['annotations'].append({'id': len(data['annotations']) + 1, 'image_id': image_id,
                    'category_id': grade + 1, 'bbox': [x, y, 20, 24], 'area': 480, 'iscrowd': 0})
            filename = f'images/synthetic-{image_id}.png'
            image.save(root / filename)
            data['images'].append({'id': image_id, 'file_name': filename, 'width': 128, 'height': 128,
                'split': split, 'patient_group': f'synthetic-group-{image_id}',
                'source_slide': f'synthetic-slide-{image_id}', 'sha256': digest(root / filename)})
        write_json(root / f'{split}.json', data)
    return root


def read_dataset(path, categories=None):
    categories = CATEGORIES if categories is None else categories
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['categories'] != categories or not data['images']:
        raise ValueError('Expected the explicit category mapping and nonempty images.')
    images = {}
    for item in data['images']:
        if type(item['id']) is not int or item['id'] in images:
            raise ValueError('Image IDs must be unique integers.')
        image_path = (path.parent / item['file_name']).resolve()
        if not image_path.is_relative_to(path.parent):
            raise ValueError('Image path escapes dataset directory.')
        if digest(image_path) != item.get('sha256'):
            raise ValueError('Image hash is missing or changed: ' + item['file_name'])
        with Image.open(image_path) as image:
            if list(image.size) != [item['width'], item['height']]:
                raise ValueError('Image dimensions disagree with metadata.')
        images[item['id']] = item
    ids = set()
    for item in data['annotations']:
        if item['id'] in ids or item['image_id'] not in images or item['category_id'] not in {c['id'] for c in categories}:
            raise ValueError('Unknown/repeated annotation or category ID.')
        ids.add(item['id'])
        box = item['bbox']
        if len(box) != 4 or any(type(value) not in (int, float) or not math.isfinite(value) for value in box):
            raise ValueError('Invalid bounding box.')
        x, y, width, height = box
        image = images[item['image_id']]
        if min(x, y) < 0 or min(width, height) <= 0 or x + width > image['width'] or y + height > image['height']:
            raise ValueError('Box lies outside image or has zero area.')
        if item.get('iscrowd', 0) != 0:
            raise ValueError('This baseline requires non-crowd annotations.')
    return data


def validate_splits(paths, software_check, readiness=None, grouping_path=None):
    datasets = {split: read_dataset(path) for split, path in paths.items()}
    seen_patients, seen_slides, seen_hashes = {}, {}, {}
    approved = {}
    if not software_check:
        if not readiness or not readiness['ready_for_experiment'] or not grouping_path:
            raise ValueError('Real training requires a freshly validated rights and patient-grouping review.')
        with Path(grouping_path).open(encoding='utf-8-sig', newline='') as stream:
            approved = {row['slide']: row for row in csv.DictReader(stream)}
    for split, data in datasets.items():
        synthetic = data.get('info', {}).get('dataset_kind') == SYNTHETIC
        if software_check != synthetic:
            raise ValueError('Software checks accept only explicit synthetic geometry fixtures; real data is not a fixture.')
        if not software_check and data.get('info', {}).get('annotation_source_sha256') != readiness['annotation_source_sha256']:
            raise ValueError('Dataset does not match reviewed source hash.')
        if not software_check and {item['category_id'] for item in data['annotations']} != set(range(1, 6)):
            raise ValueError('Every real split must include actual patch labels for all five grades.')
        for item in data['images']:
            if item.get('split') != split or not item.get('patient_group') or not item.get('source_slide'):
                raise ValueError('Every patch must declare its split, patient group and source slide.')
            if not software_check:
                row = approved.get(item['source_slide'])
                if not row or row['split'] != split or row['patient_group'] != item['patient_group']:
                    raise ValueError('Patch does not match reviewed grouping map.')
            for value, seen in [(item['patient_group'], seen_patients), (item['source_slide'], seen_slides), (item['sha256'], seen_hashes)]:
                if value in seen and seen[value] != split:
                    raise ValueError('Patient, slide, or duplicate image leaks across dataset splits.')
                seen[value] = split
    return datasets


class CocoDataset:
    def __init__(self, path, data=None):
        self.path = Path(path)
        self.data = data if data is not None else read_dataset(path)
        self.images = self.data['images']
        self.boxes = defaultdict(list)
        for item in self.data['annotations']:
            self.boxes[item['image_id']].append(item)

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        import torch
        from torchvision.transforms.functional import pil_to_tensor
        item = self.images[index]
        with Image.open(self.path.parent / item['file_name']) as image:
            tensor = pil_to_tensor(image.convert('RGB')).float() / 255
        boxes, labels = [], []
        for annotation in self.boxes[item['id']]:
            x, y, width, height = annotation['bbox']
            boxes.append([x, y, x + width, y + height])
            labels.append(annotation['category_id'])
        return tensor, {'boxes': torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
                        'labels': torch.tensor(labels, dtype=torch.int64), 'image_id': torch.tensor(item['id'])}
