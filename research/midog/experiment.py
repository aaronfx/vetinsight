"""Case-separated MIDOG++ baseline comparison with validation model selection."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'phem'))
from pipeline import digest, write_json
from baseline_data import CocoDataset, read_dataset
from cohort import SPLITS, REVIEW, verify

KIND = 'MIDOGPP_CASE_GROUPED_HISTOLOGY_EXPERIMENT_V2'
CATEGORIES = [{'id': 1, 'name': 'mitotic figure'}]
DATA = ROOT / 'derived/cohort-v2'
RUNS = ROOT / 'runs/cohort-v2-r2'
CORE = 448
HALO = 32
TILE = CORE + HALO * 2
SETTINGS = {'seed': 42, 'threads': 2, 'proposal_limit': 32, 'pretrained': True,
            'freeze_backbone': True, 'epochs': 3, 'batch_size': 2, 'weight_decay': .0005,
            'device': 'cpu', 'rpn_score_thresh': 0.0}
VARIANTS = {
    'baseline': {'min_size': 256, 'max_size': 256, 'learning_rate': .001, 'anchors': None},
    'small-cells': {'min_size': 512, 'max_size': 512, 'learning_rate': .005, 'anchors': [16, 24, 32, 48, 64]},
}


def checked_review():
    review = json.loads(REVIEW.read_text())
    if review['cases'] != SPLITS or digest(ROOT / 'metadata/MIDOGpp.json') != review['annotation_sha256']:
        raise ValueError('Cohort or annotation source differs from reviewed inputs.')
    if any(f['license_url'] != 'https://creativecommons.org/publicdomain/zero/1.0/' for f in review['selected_files']):
        raise ValueError('Selected files require reviewed CC0 terms.')
    ids = [case for cases in SPLITS.values() for case in cases]
    if len(ids) != len(set(ids)) or set(SPLITS['test']) & {251, 252}:
        raise ValueError('Repeated source case or previously inspected pilot test case.')
    return review


def prepare(output):
    from PIL import Image, ImageDraw
    from pilot import corner_box
    review = checked_review()
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a fresh dataset output directory.')
    source = json.loads((ROOT / 'metadata/MIDOGpp.json').read_bytes())
    images = {i['id']: i for i in source['images']}
    boxes = defaultdict(list)
    for item in source['annotations']:
        if item['category_id'] not in (1, 2):
            raise ValueError('Unknown source category.')
        if item['image_id'] in {case for cases in SPLITS.values() for case in cases}:
            image = images[item['image_id']]
            box = corner_box(item['bbox'], image['width'], image['height'])
            if max(box[2] - box[0], box[3] - box[1]) > HALO * 2:
                raise ValueError('Halo is too small for an annotated cell.')
            boxes[item['image_id']].append((item, box))
    entries = {f['name']: f for f in review['selected_files']}
    for case in [case for cases in SPLITS.values() for case in cases]:
        verify(ROOT / 'raw/midogpp' / images[case]['file_name'], entries[images[case]['file_name']])
    output.mkdir(parents=True)
    (output / 'images').mkdir()
    manifest = {'kind': KIND, 'cases': SPLITS, 'annotation_sha256': review['annotation_sha256'],
                'review_sha256': digest(REVIEW), 'tile_size': TILE, 'core_size': CORE, 'halo': HALO,
                'split_unit': 'Source case/ROI; patient independence unverified',
                'selection': 'Every fixed core grid tile including empty tiles. Objects assigned once by center.',
                'splits': {}}
    for split, cases in SPLITS.items():
        data = {'info': {k: v for k, v in manifest.items() if k != 'splits'},
                'images': [], 'annotations': [], 'hard_negatives': [], 'categories': CATEGORIES}
        preview = []
        for case in cases:
            source_image = images[case]
            with Image.open(ROOT / 'raw/midogpp' / source_image['file_name']) as slide:
                if slide.size != (source_image['width'], source_image['height']):
                    raise ValueError('Source dimensions changed.')
                slide = slide.convert('RGB')
                tile_index = 0
                for y in range(0, slide.height, CORE):
                    for x in range(0, slide.width, CORE):
                        tile_index += 1
                        image_id = case * 1_000_000 + tile_index
                        origin_x, origin_y = x - HALO, y - HALO
                        tile = slide.crop((origin_x, origin_y, origin_x + TILE, origin_y + TILE))
                        filename = f'images/{case}-{x}-{y}.png'
                        tile.save(output / filename)
                        core = [HALO, HALO, min(CORE, slide.width - x), min(CORE, slide.height - y)]
                        data['images'].append({'id': image_id, 'file_name': filename, 'width': TILE, 'height': TILE,
                                               'source_case': case, 'split': split, 'origin': [origin_x, origin_y],
                                               'valid_core': core, 'sha256': digest(output / filename)})
                        tile_boxes = []
                        for annotation, (x1, y1, x2, y2) in boxes[case]:
                            if x <= (x1 + x2) / 2 < x + CORE and y <= (y1 + y2) / 2 < y + CORE:
                                box = [x1 - origin_x, y1 - origin_y, x2 - x1, y2 - y1]
                                target = 'annotations' if annotation['category_id'] == 1 else 'hard_negatives'
                                data[target].append({'id': annotation['id'], 'image_id': image_id,
                                                     'category_id': annotation['category_id'], 'bbox': box,
                                                     'area': box[2] * box[3], 'iscrowd': 0})
                                tile_boxes.append((annotation['category_id'], box))
                        if split != 'test' and any(c == 1 for c, _ in tile_boxes) and len(preview) < 6:
                            shown = tile.copy()
                            draw = ImageDraw.Draw(shown)
                            draw.rectangle((HALO, HALO, HALO + core[2], HALO + core[3]), outline='cyan', width=1)
                            for category, (a, b, w, h) in tile_boxes:
                                draw.rectangle((a, b, a + w, b + h), outline='lime' if category == 1 else 'orange', width=2)
                            preview.append((case, shown))
            print(f'Prepared {split} case {case}', flush=True)
        expected_positive = sum(a['category_id'] == 1 for case in cases for a, _ in boxes[case])
        expected_negative = sum(a['category_id'] == 2 for case in cases for a, _ in boxes[case])
        if len(data['annotations']) != expected_positive or len(data['hard_negatives']) != expected_negative:
            raise ValueError('Source labels were lost or duplicated during tiling.')
        write_json(output / f'{split}.json', data)
        manifest['splits'][split] = {'cases': len(cases), 'tiles': len(data['images']),
                                    'mitoses': expected_positive, 'hard_negatives': expected_negative}
        if preview:
            contact = Image.new('RGB', (3 * TILE, 2 * (TILE + 25)), 'white')
            draw = ImageDraw.Draw(contact)
            for index, (case, shown) in enumerate(preview):
                a, b = index % 3 * TILE, index // 3 * (TILE + 25)
                contact.paste(shown, (a, b + 25))
                draw.text((a + 5, b + 5), f'{split} case {case} | green source mitosis | cyan core', fill='black')
            contact.save(output / f'{split}-label-review.jpg')
    write_json(output / 'manifest.json', manifest)
    print(json.dumps(manifest, indent=2), flush=True)


def load_split(folder, split):
    review = checked_review()
    doc = read_dataset(Path(folder) / f'{split}.json', categories=CATEGORIES)
    if doc['info']['kind'] != KIND or doc['info']['review_sha256'] != digest(REVIEW):
        raise ValueError('Dataset does not match pinned cohort review.')
    if doc['info']['annotation_sha256'] != review['annotation_sha256']:
        raise ValueError('Wrong annotation source.')
    if {i['source_case'] for i in doc['images']} != set(SPLITS[split]):
        raise ValueError('Missing or unexpected source cases.')
    if any(i['split'] != split or i['width'] != TILE or i['height'] != TILE for i in doc['images']):
        raise ValueError('Invalid split or patch dimensions.')
    return doc


def filter_core(predictions, data):
    images = {image['id']: image for image in data['images']}
    kept = []
    for p in predictions:
        x, y, w, h = p['bbox']
        a, b, cw, ch = images[p['image_id']]['valid_core']
        if a <= x + w / 2 < a + cw and b <= y + h / 2 < b + ch:
            kept.append(p)
    return kept


def score(model, folder, split, data):
    import torch
    from baseline import infer
    predictions = infer(model, CocoDataset(Path(folder) / f'{split}.json', data), torch.device('cpu'))
    return filter_core(predictions, data)


def train(folder, output, variant):
    import torch
    import torchvision
    from baseline import build_model, seed_all
    from evaluate import metrics
    from torchvision.models.detection import FasterRCNN_MobileNet_V3_Large_FPN_Weights
    from urllib.parse import urlsplit
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a fresh run directory.')
    train_data, validation = load_split(folder, 'train'), load_split(folder, 'validation')
    train_hashes = {i['sha256'] for i in train_data['images']}
    if train_hashes & {i['sha256'] for i in validation['images']}:
        raise ValueError('Duplicate patch leaks between train and validation.')
    settings = SETTINGS | VARIANTS[variant]
    seed_all(settings['seed'], settings['threads'])
    model = build_model(settings, initialize=True, num_classes=2, anchor_sizes=settings['anchors'])
    optimizer = torch.optim.SGD([p for p in model.parameters() if p.requires_grad], lr=settings['learning_rate'],
                               momentum=.9, weight_decay=settings['weight_decay'])
    output.mkdir(parents=True)
    weight_url = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1.url
    weight_path = Path(torch.hub.get_dir()) / 'checkpoints' / Path(urlsplit(weight_url).path).name
    source_files = [Path(__file__), ROOT / 'cohort.py', ROOT.parent / 'phem/baseline.py',
                    ROOT.parent / 'phem/baseline_data.py', ROOT.parent / 'phem/evaluate.py']
    provenance = {'kind': KIND, 'variant': variant, 'settings': settings, 'categories': CATEGORIES,
                  'review_sha256': digest(REVIEW), 'cases': SPLITS,
                  'dataset_hashes': {split: digest(Path(folder) / f'{split}.json') for split in SPLITS},
                  'versions': {'torch': str(torch.__version__), 'torchvision': str(torchvision.__version__),
                               'python': platform.python_version()},
                  'initialization': {'url': weight_url, 'sha256': digest(weight_path)},
                  'code_sha256': {str(p.relative_to(ROOT.parent)): digest(p) for p in source_files},
                  'model_selection': 'Highest validation AP50, then AP50:95; earliest epoch breaks exact ties.',
                  'limitation': 'Six training, two validation, three test source cases. Patient linkage unverified.'}
    for path in source_files:
        target = output / 'source' / path.relative_to(ROOT.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    write_json(output / 'run.json', provenance)
    loader = torch.utils.data.DataLoader(CocoDataset(Path(folder) / 'train.json', train_data),
                                         batch_size=settings['batch_size'], shuffle=True, num_workers=0,
                                         generator=torch.Generator().manual_seed(settings['seed']),
                                         collate_fn=lambda batch: tuple(zip(*batch)))
    initial = model.roi_heads.box_predictor.cls_score.weight.detach().clone()
    started = time.monotonic()
    best = (-1., -1.)
    history = []
    steps = 0
    for epoch in range(settings['epochs']):
        model.train()
        model.backbone.eval()
        losses = defaultdict(float)
        for batch, (images, targets) in enumerate(loader, 1):
            optimizer.zero_grad(set_to_none=True)
            components = model(list(images), list(targets))
            loss = sum(components.values())
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite training loss.')
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 10, error_if_nonfinite=True)
            optimizer.step()
            steps += 1
            for key, value in components.items():
                losses[key] += float(value.detach())
            if batch % 50 == 0:
                print(f'{variant} epoch {epoch + 1} batch {batch}/{len(loader)}', flush=True)
        predictions = score(model, folder, 'validation', validation)
        measured = metrics(validation, predictions)
        ap50 = measured['metrics']['AP_IoU_050']
        ap = measured['metrics']['AP_IoU_050_095']
        if ap50 is None or ap is None:
            raise ValueError('Validation requires positive labels.')
        history.append({'epoch': epoch + 1, 'losses': {key: value / len(loader) for key, value in losses.items()},
                        'validation_AP50': ap50, 'validation_AP50_95': ap})
        checkpoint = {'model': model.state_dict(), 'optimizer': optimizer.state_dict(), 'epoch': epoch + 1,
                      'provenance': provenance, 'torch_rng': torch.get_rng_state()}
        torch.save(checkpoint, output / 'last.pt')
        if (ap50, ap) > best:
            best = (ap50, ap)
            torch.save(checkpoint, output / 'best.pt')
        write_json(output / 'history.json', history)
        print(f'{variant} epoch {epoch + 1} validation AP50={ap50:.6f} AP50:95={ap:.6f}', flush=True)
    summary = {'kind': KIND, 'variant': variant, 'optimizer_steps': steps, 'elapsed_seconds': time.monotonic() - started,
               'classifier_weights_changed': not torch.equal(initial, model.roi_heads.box_predictor.cls_score.weight.detach()),
               'best_checkpoint_sha256': digest(output / 'best.pt'), 'test_evaluated': False}
    write_json(output / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


def evaluate(folder, output):
    import torch
    from baseline import build_model, seed_all
    from evaluate import metrics
    from failure_report import report, iou
    output = Path(output)
    if (output / 'evaluation.json').exists():
        raise ValueError('Test already evaluated for this run. Preserve its results.')
    checkpoint = torch.load(output / 'best.pt', map_location='cpu', weights_only=True)
    provenance = checkpoint['provenance']
    if provenance['kind'] != KIND or provenance['review_sha256'] != digest(REVIEW):
        raise ValueError('Unexpected experiment provenance.')
    for split in SPLITS:
        if digest(Path(folder) / f'{split}.json') != provenance['dataset_hashes'][split]:
            raise ValueError('Dataset changed after training.')
    data = load_split(folder, 'test')
    other_hashes = {i['sha256'] for split in ('train', 'validation') for i in load_split(folder, split)['images']}
    if other_hashes & {i['sha256'] for i in data['images']}:
        raise ValueError('Duplicate patch leaks into test.')
    settings = provenance['settings']
    seed_all(settings['seed'], settings['threads'])
    model = build_model(settings, num_classes=2, anchor_sizes=settings['anchors'])
    model.load_state_dict(checkpoint['model'], strict=True)
    predictions = score(model, folder, 'test', data)
    path = output / 'test-predictions.json'
    write_json(path, predictions)
    result = metrics(data, predictions)
    predictions_by_image = defaultdict(list)
    for prediction in predictions:
        predictions_by_image[prediction['image_id']].append(prediction)
    best_overlaps = [max((iou(target['bbox'], p['bbox']) for p in predictions_by_image[target['image_id']]), default=0.)
                     for target in data['annotations']]
    result['localization_diagnostics'] = {
        'median_source_width': statistics.median(a['bbox'][2] for a in data['annotations']),
        'median_source_height': statistics.median(a['bbox'][3] for a in data['annotations']),
        'median_predicted_width': statistics.median(p['bbox'][2] for p in predictions) if predictions else None,
        'median_predicted_height': statistics.median(p['bbox'][3] for p in predictions) if predictions else None,
        'largest_target_prediction_iou': max(best_overlaps),
        'targets_with_candidate_iou_050': sum(value >= .5 for value in best_overlaps),
        'scope': 'All returned detections after core filtering, across all scores. Candidate overlap is a localization diagnostic.'}
    result.update({'kind': KIND, 'variant': provenance['variant'], 'epoch': checkpoint['epoch'],
                   'test_cases': SPLITS['test'], 'checkpoint_sha256': digest(output / 'best.pt'),
                   'dataset_sha256': digest(Path(folder) / 'test.json'), 'predictions_sha256': digest(path),
                   'limitation': provenance['limitation'], 'units': '512px contextual tiles; predictions filtered by core center',
                   'evaluation_code_sha256': digest(Path(__file__))})
    shutil.copyfile(Path(__file__), output / 'evaluation-source.py')
    write_json(str(path) + '.provenance.json', {'kind': KIND, 'dataset_sha256': result['dataset_sha256'],
               'prediction_sha256': result['predictions_sha256'], 'checkpoint_sha256': result['checkpoint_sha256']})
    errors = report(Path(folder) / 'test.json', path, output / 'errors', categories=CATEGORIES)
    result['diagnostics_score_050_iou_050'] = errors['counts']
    write_json(output / 'evaluation.json', result)
    print(json.dumps(result, indent=2), flush=True)


def compare(folder, runs):
    manifest = json.loads((Path(folder) / 'manifest.json').read_text())
    results = {}
    for variant in VARIANTS:
        path = Path(runs) / variant
        results[variant] = {name: json.loads((path / filename).read_text()) for name, filename in
                            [('provenance', 'run.json'), ('training', 'summary.json'),
                             ('history', 'history.json'), ('evaluation', 'evaluation.json')]}
        evaluation = results[variant]['evaluation']
        predictions_path = path / 'test-predictions.json'
        if digest(path / 'best.pt') != evaluation['checkpoint_sha256'] or digest(predictions_path) != evaluation['predictions_sha256']:
            raise ValueError('Evaluated checkpoint or predictions changed.')
        predictions = json.loads(predictions_path.read_text())
        results[variant]['score_diagnostics'] = {'maximum_test_score': max((p['score'] for p in predictions), default=None)}
    if results['baseline']['evaluation']['dataset_sha256'] != results['small-cells']['evaluation']['dataset_sha256']:
        raise ValueError('Comparison requires identical held-out data.')
    comparison = {'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'kind': KIND, 'cohort': manifest, 'variants': results,
                  'interpretation': 'Paired cohort comparison of configuration bundles. Resolution, anchor scales and learning rate change together, so isolated causal attribution is unavailable.',
                  'prior_pilot': {'AP50': 0., 'AP50_95': 0., 'cases': [251, 252],
                                  'comparison_limit': 'Different cohort and boundary protocol; prior pilot numbers are contextual only.'}}
    write_json(ROOT / 'reports/cohort-v2-comparison.json', comparison)
    lines = ['# Expanded MIDOG++ experiment results', '',
             'Both configurations used the same six training, two validation and three held-out source cases.', '',
             'At the fixed diagnostic score threshold of 0.5, both models missed all 138 test mitoses.',
             'The revised configuration improved ranked detection AP and localization, while detection quality remains limited.', '',
             '| Configuration | Selected epoch | Test AP50 | Test AP50–95 | Matches at score 0.5 | Unmatched predictions | Missed targets |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for variant, result in results.items():
        evaluation = result['evaluation']
        values = evaluation['metrics']
        counts = evaluation['diagnostics_score_050_iou_050']
        lines.append(f"| {variant} | {evaluation['epoch']} | {values['AP_IoU_050']:.6f} | {values['AP_IoU_050_095']:.6f} | "
                     f"{counts.get('matched_correct_grade', 0)} | {counts.get('unmatched_predictions', 0)} | {counts.get('missed_targets', 0)} |")
    lines += ['', 'AP values are reported on a 0–1 scale. Diagnostic matches use IoU 0.5.', '',
              '| Configuration | Median predicted box width | Median source width | Targets with a candidate at IoU 0.5 |',
              '| --- | --- | --- | --- |']
    for variant, result in results.items():
        diagnostic = result['evaluation']['localization_diagnostics']
        width = diagnostic['median_predicted_width']
        width_text = f'{width:.1f} px' if width is not None else 'No detections'
        lines.append(f"| {variant} | {width_text} | {diagnostic['median_source_width']:.1f} px | {diagnostic['targets_with_candidate_iou_050']} |")
    lines += ['', 'Box-size diagnostics use all returned detections after core filtering, across all scores.',
              'Candidate overlap measures localization opportunities before the diagnostic score threshold.', '',
              'The maximum test scores were ' + ', '.join(
                  f"{variant} {result['score_diagnostics']['maximum_test_score']:.6f}"
                  if result['score_diagnostics']['maximum_test_score'] is not None else f'{variant} no detections'
                  for variant, result in results.items()) + '.',
              'Threshold calibration requires development data and further evaluation on a newly reserved cohort.', '',
              'The earlier three-case pilot recorded AP50 and AP50–95 of 0.00 on different cases and a different tile protocol.',
              'The two rows above provide the direct paired comparison.', '',
              'Resolution, anchor sizes and learning rate change together. The results compare configuration bundles.',
              'The cohort is small and grouping uses source case identifiers. Patient independence remains unverified.', '',
              'See EXPERIMENT.md for source selection, preparation, model selection and Windows commands.',
              'The aggregate JSON preserves source hashes, configurations, epoch histories and measured results.', '']
    (ROOT / 'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({name: result['evaluation']['metrics'] for name, result in results.items()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'train', 'evaluate', 'compare'])
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--variant', choices=list(VARIANTS), default='small-cells')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.output or args.data)
    elif args.command == 'train':
        train(args.data, args.output or RUNS / args.variant, args.variant)
    elif args.command == 'evaluate':
        evaluate(args.data, args.output or RUNS / args.variant)
    else:
        compare(args.data, args.output or RUNS)
