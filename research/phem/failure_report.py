"""Thresholded error examples; diagnostic greedy matching is separate from COCO AP."""
import argparse
from collections import Counter
import json
from pathlib import Path

from PIL import Image, ImageDraw

from baseline_data import CocoDataset, read_dataset
from evaluate import metrics
from pipeline import digest, write_json


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    intersection = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0


def diagnose(truth, predictions, score_threshold=.5, iou_threshold=.5):
    if not 0 <= score_threshold <= 1 or not 0 < iou_threshold <= 1:
        raise ValueError('Invalid diagnostic score/IoU thresholds.')
    outcomes, confusion, examples = Counter(), Counter(), []
    for image in truth['images']:
        targets = [box for box in truth['annotations'] if box['image_id'] == image['id']]
        candidates = sorted((box for box in predictions if box['image_id'] == image['id'] and box['score'] >= score_threshold), key=lambda box: -box['score'])
        used = set()
        errors = []
        for prediction in candidates:
            options = [(iou(prediction['bbox'], target['bbox']), index) for index, target in enumerate(targets) if index not in used]
            overlap, index = max(options, default=(0, -1))
            if overlap >= iou_threshold and index >= 0:
                used.add(index)
                target = targets[index]
                confusion[(target['category_id'], prediction['category_id'])] += 1
                if target['category_id'] == prediction['category_id']:
                    outcomes['matched_correct_grade'] += 1
                else:
                    outcomes['matched_wrong_grade'] += 1
                    errors.append('wrong_grade')
            else:
                outcomes['unmatched_predictions'] += 1
                errors.append('unmatched_prediction')
        outcomes['missed_targets'] += len(targets) - len(used)
        if len(targets) > len(used):
            errors.append('missed_target')
        if errors:
            examples.append({'image_id': image['id'], 'file_name': image['file_name'], 'errors': sorted(set(errors))})
    return {'score_threshold': score_threshold, 'iou_threshold': iou_threshold,
            'matching': 'Score-ordered, class-agnostic greedy IoU matching for diagnostics only; COCO AP is separate.',
            'counts': dict(outcomes), 'confusion': [{'true_category_id': a, 'predicted_category_id': b, 'count': count} for (a, b), count in sorted(confusion.items())],
            'error_examples': examples}


def report(truth_path, predictions_path, output, categories=None):
    dataset = CocoDataset(truth_path, read_dataset(truth_path, categories=categories))
    predictions = json.loads(Path(predictions_path).read_text())
    provenance = json.loads(Path(str(predictions_path) + '.provenance.json').read_text())
    if provenance['dataset_sha256'] != digest(truth_path) or provenance['prediction_sha256'] != digest(predictions_path):
        raise ValueError('Prediction provenance does not match these files.')
    # Validate boxes/category IDs/scores through the same evaluation input checks.
    metrics(dataset.data, predictions)
    result = diagnose(dataset.data, predictions)
    result['kind'] = provenance['kind']
    result['checkpoint_sha256'] = provenance['checkpoint_sha256']
    output = Path(output)
    if output.exists():
        raise ValueError('Failure report output already exists.')
    output.mkdir(parents=True)
    for item in result['error_examples'][:12]:
        with Image.open(Path(truth_path).parent / item['file_name']) as original:
            image = original.convert('RGB')
        drawing = ImageDraw.Draw(image)
        for boxes, color, prefix in [(dataset.data['annotations'], '#008000', 'SOURCE'), (predictions, '#c00000', 'PRED')]:
            for box in boxes:
                if box['image_id'] != item['image_id'] or (prefix == 'PRED' and box['score'] < result['score_threshold']):
                    continue
                x, y, width, height = box['bbox']
                drawing.rectangle((x, y, x + width, y + height), outline=color, width=2)
                drawing.text((x, y), f'{prefix} {box["category_id"]}', fill=color)
        image.save(output / f'error-{item["image_id"]}.png')
    write_json(output / 'errors.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ground-truth', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = report(args.ground_truth, args.predictions, args.output)
    print(result['kind'])
