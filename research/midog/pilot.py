"""Bounded MIDOG++ canine histology engineering pilot."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'phem'))
from pipeline import digest, write_json

KIND = 'MIDOGPP_THREE_CASE_HISTOLOGY_ENGINEERING_PILOT'
CATEGORIES = [{'id': 1, 'name': 'mitotic figure'}]
CASES = {'train': [250], 'test': [251, 252]}


def review():
    doc = json.loads((ROOT / 'reports/midogpp-source-review.json').read_text())
    source = ROOT / 'metadata/MIDOGpp.json'
    if digest(source) != doc['annotation_sha256']:
        raise ValueError('Annotation source changed since license review.')
    data = json.loads(source.read_bytes())
    if data['licenses'][0]['name'] != 'CC0' or any(
        f['license_url'] != 'https://creativecommons.org/publicdomain/zero/1.0/' for f in doc['selected_files']
    ):
        raise ValueError('Selected files require matching reviewed CC0 terms.')
    if data['categories'] != CATEGORIES + [{'id': 2, 'name': 'not mitotic figure'}]:
        raise ValueError('Source category schema changed.')
    return doc, data


def fetch():
    doc, _ = review()
    raw_dir = ROOT / 'raw/midogpp'
    raw_dir.mkdir(parents=True, exist_ok=True)
    for entry in doc['selected_files']:
        if not entry['name'].endswith('.tiff'):
            continue
        path = raw_dir / entry['name']
        if path.name != entry['name'] or entry['bytes'] > 150_000_000:
            raise ValueError('Unexpected image name or download size.')
        if path.exists():
            verify_file(path, entry)
            print('Verified existing ' + path.name, flush=True)
            continue
        partial = path.with_suffix('.tiff.partial')
        size = 0
        with urlopen(entry['download_url'], timeout=90) as response, partial.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > entry['bytes']:
                    raise ValueError('Download exceeds published size.')
                output.write(chunk)
        verify_file(partial, entry)
        partial.replace(path)
        print('Downloaded and verified ' + path.name, flush=True)


def verify_file(path, entry):
    checksum = hashlib.md5()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    if path.stat().st_size != entry['bytes'] or checksum.hexdigest() != entry['md5']:
        raise ValueError('Published size/checksum mismatch for ' + entry['name'])


def corner_box(box, width, height):
    if len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
        raise ValueError('Invalid source box.')
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        raise ValueError('Invalid source corners.')
    clipped = [max(0, x1), max(0, y1), min(width, x2), min(height, y2)]
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise ValueError('Source box outside image.')
    return clipped


def prepare(output):
    from PIL import Image, ImageDraw
    review_doc, source = review()
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a fresh dataset output directory.')
    entries = {f['name']: f for f in review_doc['selected_files']}
    images = {i['id']: i for i in source['images']}
    # Verify every selected image before writing any derived dataset.
    for case_id in (250, 251, 252):
        image = images[case_id]
        if image['tumor_type'] != 'canine lymphosarcoma':
            raise ValueError('Unexpected domain. MIDOG++ numbering differs from MIDOG 2022.')
        path = ROOT / 'raw/midogpp' / image['file_name']
        verify_file(path, entries[image['file_name']])
        with Image.open(path) as im:
            if im.size != (image['width'], image['height']):
                raise ValueError('Source dimensions disagree.')
    output.mkdir(parents=True)
    (output / 'images').mkdir()
    tile_size = 512
    summary = {'kind': KIND, 'tile_size': tile_size, 'cases': CASES,
               'selection': 'All nonoverlapping grid tiles including empty tiles; grid fixed independently of labels.',
               'split_unit': 'Source case/ROI; patient independence unverified',
               'annotation_sha256': review_doc['annotation_sha256'], 'splits': {}}
    previews = []
    image_id = 0
    for split, case_ids in CASES.items():
        data = {'info': summary.copy(), 'categories': CATEGORIES, 'images': [], 'annotations': [], 'hard_negatives': []}
        for case_id in case_ids:
            image = images[case_id]
            boxes = [(a, corner_box(a['bbox'], image['width'], image['height']))
                     for a in source['annotations'] if a['image_id'] == case_id]
            with Image.open(ROOT / 'raw/midogpp' / image['file_name']) as slide:
                slide = slide.convert('RGB')
                for y in range(0, slide.height, tile_size):
                    for x in range(0, slide.width, tile_size):
                        image_id += 1
                        tile = slide.crop((x, y, x + tile_size, y + tile_size))
                        filename = f'images/{case_id}-{x}-{y}.png'
                        tile.save(output / filename)
                        data['images'].append({'id': image_id, 'file_name': filename, 'width': tile_size,
                                               'height': tile_size, 'source_case': case_id, 'split': split,
                                               'sha256': digest(output / filename), 'origin': [x, y]})
                        positive_count = 0
                        for annotation, (x1, y1, x2, y2) in boxes:
                            # Assign each object once, by its center. Clip at tile boundaries.
                            if not (x <= (x1 + x2) / 2 < x + tile_size and y <= (y1 + y2) / 2 < y + tile_size):
                                continue
                            box = [max(x1, x) - x, max(y1, y) - y,
                                   min(x2, x + tile_size) - max(x1, x), min(y2, y + tile_size) - max(y1, y)]
                            target = 'annotations' if annotation['category_id'] == 1 else 'hard_negatives'
                            data[target].append({'id': annotation['id'], 'image_id': image_id,
                                                 'category_id': annotation['category_id'], 'bbox': box,
                                                 'area': box[2] * box[3], 'iscrowd': 0})
                            positive_count += annotation['category_id'] == 1
                        if positive_count and sum(item[0] == case_id for item in previews) < 2:
                            shown = tile.copy()
                            draw = ImageDraw.Draw(shown)
                            for a in data['annotations'] + data['hard_negatives']:
                                if a['image_id'] == image_id:
                                    a_x, a_y, w, h = a['bbox']
                                    draw.rectangle((a_x, a_y, a_x + w, a_y + h), outline='lime' if a['category_id'] == 1 else 'orange', width=2)
                            previews.append((case_id, shown))
        write_json(output / f'{split}.json', data)
        summary['splits'][split] = {'tiles': len(data['images']), 'mitoses': len(data['annotations']),
                                    'hard_negatives': len(data['hard_negatives'])}
    contact = Image.new('RGB', (3 * tile_size, 2 * (tile_size + 25)), 'white')
    draw = ImageDraw.Draw(contact)
    for index, (case_id, image) in enumerate(previews):
        x, y = index % 3 * tile_size, index // 3 * (tile_size + 25)
        contact.paste(image, (x, y + 25))
        draw.text((x + 5, y + 5), f'Case {case_id} | green mitosis | orange hard negative', fill='black')
    contact.save(output / 'label-review.jpg')
    write_json(output / 'manifest.json', summary)
    print(json.dumps(summary, indent=2))


def load_data(root):
    from baseline_data import read_dataset
    data = {}
    cases_seen, hashes_seen = {}, {}
    for split, expected_cases in CASES.items():
        path = Path(root) / f'{split}.json'
        # Shared reader validates hashes, dimensions, bounds, and categories.
        document = read_dataset(path, categories=CATEGORIES)
        if document['info']['kind'] != KIND:
            raise ValueError('Wrong dataset kind.')
        for image in document['images']:
            case_id = image['source_case']
            if case_id not in expected_cases or image['split'] != split:
                raise ValueError('Unexpected source case split.')
            for value, seen in ((case_id, cases_seen), (image['sha256'], hashes_seen)):
                if value in seen and seen[value] != split:
                    raise ValueError('Case or duplicate image crosses splits.')
                seen[value] = split
        data[split] = document
    return data


def train(root, output):
    import time
    import torch
    import torchvision
    import platform
    from baseline import build_model, seed_all, infer
    from baseline_data import CocoDataset
    from evaluate import metrics
    data = load_data(root)
    source_review, _ = review()
    if any(d['info']['annotation_sha256'] != source_review['annotation_sha256'] for d in data.values()):
        raise ValueError('Dataset does not match reviewed annotations.')
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a fresh run output directory.')
    settings = {'seed': 42, 'threads': 2, 'min_size': 256, 'max_size': 256, 'proposal_limit': 100,
                'pretrained': True, 'freeze_backbone': True, 'epochs': 1, 'batch_size': 2,
                'learning_rate': 0.001, 'weight_decay': 0.0005, 'device': 'cpu'}
    seed_all(settings['seed'], settings['threads'])
    model = build_model(settings, initialize=True, num_classes=2)
    from torchvision.models.detection import FasterRCNN_MobileNet_V3_Large_FPN_Weights
    from urllib.parse import urlsplit
    weight_url = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1.url
    initial_weights = Path(torch.hub.get_dir()) / 'checkpoints' / Path(urlsplit(weight_url).path).name
    output.mkdir(parents=True)
    provenance = {'kind': KIND, 'settings': settings, 'categories': CATEGORIES,
                  'initialization': 'Torchvision COCO_V1', 'cases': CASES,
                  'initial_weights': {'url': weight_url, 'sha256': digest(initial_weights)},
                  'dataset_hashes': {s: digest(Path(root) / f'{s}.json') for s in data},
                  'source_review_sha256': digest(ROOT / 'reports/midogpp-source-review.json'),
                  'code_sha256': {str(p.relative_to(ROOT.parent)): digest(p) for p in
                                  (Path(__file__), ROOT.parent / 'phem/baseline.py', ROOT.parent / 'phem/baseline_data.py', ROOT.parent / 'phem/evaluate.py')},
                  'versions': {'torch': str(torch.__version__), 'torchvision': str(torchvision.__version__),
                               'python': platform.python_version()},
                  'protocol': 'Fixed one epoch; final checkpoint; no tuning or model selection on held-out cases.',
                  'limitation': 'Single training case, two held-out source cases; patient independence unverified.'}
    write_json(output / 'run.json', provenance)
    dataset = CocoDataset(Path(root) / 'train.json', data['train'])
    loader = torch.utils.data.DataLoader(dataset, batch_size=2, shuffle=True, num_workers=0,
                                         generator=torch.Generator().manual_seed(42),
                                         collate_fn=lambda batch: tuple(zip(*batch)))
    optimizer = torch.optim.SGD([p for p in model.parameters() if p.requires_grad], lr=.001, momentum=.9, weight_decay=.0005)
    initial = model.roi_heads.box_predictor.cls_score.weight.detach().clone()
    model.train()
    model.backbone.eval()
    started = time.monotonic()
    losses = []
    for step, (images, targets) in enumerate(loader, 1):
        optimizer.zero_grad(set_to_none=True)
        loss = sum(model(list(images), list(targets)).values())
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite loss.')
        loss.backward()
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 10, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
        if step % 10 == 0:
            print(f'Training {step}/{len(loader)} batches', flush=True)
    checkpoint = output / 'last.pt'
    torch.save({'model': model.state_dict(), 'provenance': provenance}, checkpoint)
    # Verify the actual saved checkpoint before generating held-out predictions.
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    restored = build_model(settings, num_classes=2)
    restored.load_state_dict(saved['model'], strict=True)
    predictions = infer(restored, CocoDataset(Path(root) / 'test.json', data['test']), torch.device('cpu'))
    write_json(output / 'test-predictions.json', predictions)
    measured = metrics(data['test'], predictions)
    measured.update({'kind': KIND, 'checkpoint_sha256': digest(checkpoint), 'case_count': 2,
                     'evaluation_unit': '512px tiles; object assigned once by center and clipped at tile boundary',
                     'limitation': provenance['limitation']})
    write_json(output / 'evaluation.json', measured)
    summary = {'kind': KIND, 'optimizer_steps': len(losses), 'mean_loss': sum(losses) / len(losses),
               'classifier_weights_changed': not torch.equal(initial, model.roi_heads.box_predictor.cls_score.weight.detach()),
               'elapsed_seconds': time.monotonic() - started, 'held_out_metrics': measured['metrics']}
    write_json(output / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['fetch', 'prepare', 'train'])
    parser.add_argument('--data', type=Path, default=ROOT / 'derived/midogpp-pilot')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'fetch':
        fetch()
    elif args.command == 'prepare':
        prepare(args.output or args.data)
    else:
        train(args.data, args.output or ROOT / 'runs/midogpp-pilot')


if __name__ == '__main__':
    main()
