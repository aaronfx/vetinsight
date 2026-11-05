import csv
import tempfile
from pathlib import Path
import unittest

from evaluate import metrics, run
from readiness import FIELDS, check


class ExperimentTests(unittest.TestCase):
    def dataset(self):
        return {'images': [{'id': 1, 'width': 100, 'height': 100}],
                'categories': [{'id': 1, 'name': 'grade_0'}, {'id': 2, 'name': 'grade_4'}],
                'annotations': [{'id': 1, 'image_id': 1, 'category_id': 1, 'bbox': [10, 10, 20, 20], 'area': 400, 'iscrowd': 0}]}

    def test_coco_evaluator_perfect_empty_wrong_class(self):
        # Entirely synthetic fixtures verify evaluator behavior, never clinical accuracy.
        prediction = {'image_id': 1, 'category_id': 1, 'bbox': [10, 10, 20, 20], 'score': .9}
        result = metrics(self.dataset(), [prediction])
        self.assertAlmostEqual(result['metrics']['AP_IoU_050_095'], 1)
        self.assertIsNone(result['AP_by_category']['grade_4'])
        self.assertEqual(metrics(self.dataset(), [])['metrics']['AP_IoU_050_095'], 0)
        self.assertEqual(metrics(self.dataset(), [{**prediction, 'category_id': 2}])['metrics']['AR_max100'], 0)

    def test_invalid_predictions_rejected(self):
        for change in [{'score': float('nan')}, {'bbox': [90, 90, 20, 20]}, {'image_id': 999}, {'category_id': 99}]:
            prediction = {'image_id': 1, 'category_id': 1, 'bbox': [10, 10, 20, 20], 'score': .9}
            with self.assertRaises(ValueError):
                metrics(self.dataset(), [{**prediction, **change}])

    def test_smoke_data_cannot_be_reported_as_real_evaluation(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'truth.json').write_text(json.dumps(self.dataset()))
            (root / 'predictions.json').write_text('[]')
            with self.assertRaises(ValueError):
                run(root / 'truth.json', root / 'predictions.json', root / 'out.json')
            result = run(root / 'truth.json', root / 'predictions.json', root / 'out.json', software_check=True)
            self.assertEqual(result['evaluation_kind'], 'SOFTWARE_CHECK_NOT_MODEL_PERFORMANCE')

    def test_patient_leakage_missing_permission_and_class_coverage(self):
        audit = {'source_sha256': 'fixture-hash', 'slides': [
            {'slide': f'{split}.svs', 'species': 'feline', 'grades': {str(i): 3 for i in range(5)}}
            for split in ('train', 'validation', 'test')]}
        rights = {'status': 'confirmed', 'evidence': 'synthetic test fixture', 'permitted_use': 'fixture only', 'annotation_source_sha256': 'fixture-hash'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'groups.csv'
            def save(leak=False):
                with path.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS)
                    writer.writeheader()
                    for index, split in enumerate(('train', 'validation', 'test')):
                        writer.writerow({'slide': f'{split}.svs', 'patient_group': 'same' if leak else str(index), 'split': split, 'grouping_evidence': 'synthetic fixture'})
            save()
            self.assertTrue(check(audit, path, rights)['ready_for_experiment'])
            save(leak=True)
            self.assertFalse(check(audit, path, rights)['ready_for_experiment'])
            save()
            self.assertFalse(check(audit, path, {})['ready_for_experiment'])
            audit['slides'][2]['grades'].pop('4')
            self.assertFalse(check(audit, path, rights)['ready_for_experiment'])


if __name__ == '__main__':
    unittest.main()
