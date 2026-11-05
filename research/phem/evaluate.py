"""COCO bounding-box evaluation. Smoke runs are software checks, not model evidence."""
import argparse
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path

from pipeline import digest, write_json


def metrics(ground_truth, predictions):
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    images = {item['id']: item for item in ground_truth['images']}
    categories = {item['id']: item['name'] for item in ground_truth['categories']}
    if not images or len(images) != len(ground_truth['images']) or not categories or len(categories) != len(ground_truth['categories']):
        raise ValueError('Missing or duplicate image/category IDs.')
    ids = set()
    for item in ground_truth['annotations']:
        if item['id'] in ids:
            raise ValueError('Repeated ground-truth annotation ID.')
        ids.add(item['id'])
    for item in ground_truth['annotations'] + predictions:
        if item['image_id'] not in images or item['category_id'] not in categories:
            raise ValueError('Unknown image/category in boxes.')
        box = item['bbox']
        if len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            raise ValueError('Boxes must be finite pixel xywh values.')
        x, y, width, height = box
        image = images[item['image_id']]
        if min(x, y) < 0 or width <= 0 or height <= 0 or x + width > image['width'] or y + height > image['height']:
            raise ValueError('Box is outside its image or has no area.')
    for item in predictions:
        if type(item.get('score')) not in (int, float) or not math.isfinite(item['score']) or not 0 <= item['score'] <= 1:
            raise ValueError('Prediction scores must be finite numbers in [0,1].')
    with redirect_stdout(io.StringIO()):
        truth = COCO()
        truth.dataset = {**ground_truth, 'info': ground_truth.get('info', {})}
        truth.createIndex()
        if predictions:
            detected = truth.loadRes(predictions)
        else:
            detected = COCO()
            detected.dataset = {'images': list(images.values()), 'categories': ground_truth['categories'], 'annotations': []}
            detected.createIndex()
        evaluation = COCOeval(truth, detected, 'bbox')
        evaluation.evaluate()
        evaluation.accumulate()
        evaluation.summarize()
    names = ('AP_IoU_050_095', 'AP_IoU_050', 'AP_IoU_075', 'AP_small', 'AP_medium', 'AP_large',
             'AR_max1', 'AR_max10', 'AR_max100', 'AR_small', 'AR_medium', 'AR_large')
    values = {name: float(value) if value >= 0 else None for name, value in zip(names, evaluation.stats)}
    per_category = {}
    for index, category_id in enumerate(evaluation.params.catIds):
        precision = evaluation.eval['precision'][:, :, index, 0, -1]
        valid = precision[precision >= 0]
        per_category[categories[category_id]] = float(valid.mean()) if valid.size else None
    return {'metrics': values, 'AP_by_category': per_category,
            'image_count': len(images), 'ground_truth_box_count': len(ground_truth['annotations']),
            'prediction_count': len(predictions),
            'protocol': 'pycocotools bbox defaults: IoU 0.50:0.05:0.95, maxDets [1,10,100]. Absent categories/areas are null, not zero.'}


def run(truth_path, predictions_path, output, software_check=False, model_id=None, readiness=None):
    ground_truth = json.loads(Path(truth_path).read_text(encoding='utf-8'))
    predictions = json.loads(Path(predictions_path).read_text(encoding='utf-8'))
    if not isinstance(predictions, list):
        raise ValueError('Predictions must be a COCO results list.')
    if not software_check:
        if not readiness or not readiness.get('ready_for_experiment') or not model_id:
            raise ValueError('Real evaluation requires a ready experiment record and model identifier.')
        if ground_truth.get('info', {}).get('annotation_source_sha256') != readiness.get('annotation_source_sha256'):
            raise ValueError('Ground truth must be bound to the reviewed annotation source hash.')
        if not ground_truth['images'] or any(item.get('split') != 'test' or not item.get('patient_group') for item in ground_truth['images']):
            raise ValueError('Real evaluation requires patient-grouped test images; smoke patches are ineligible.')
    result = metrics(ground_truth, predictions)
    result.update({'evaluation_kind': 'SOFTWARE_CHECK_NOT_MODEL_PERFORMANCE' if software_check else 'held_out_test',
                   'model_id': model_id, 'ground_truth_sha256': digest(truth_path),
                   'predictions_sha256': digest(predictions_path)})
    write_json(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ground-truth', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--software-check', action='store_true')
    parser.add_argument('--model-id')
    parser.add_argument('--readiness', type=Path)
    args = parser.parse_args()
    readiness = json.loads(args.readiness.read_text()) if args.readiness else None
    result = run(args.ground_truth, args.predictions, args.output, args.software_check, args.model_id, readiness)
    print(result['evaluation_kind'])
