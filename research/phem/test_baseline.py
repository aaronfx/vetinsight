import json
from pathlib import Path
import tempfile
import unittest

from baseline_data import generate, read_dataset, validate_splits
from failure_report import diagnose, iou


class BaselineTests(unittest.TestCase):
    def test_explicit_single_class_mapping_preserves_default_five_grade_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = generate(Path(directory) / 'fixture')
            path = root / 'train.json'
            data = json.loads(path.read_text())
            categories = [{'id': 1, 'name': 'mitotic figure'}]
            data['categories'] = categories
            for annotation in data['annotations']:
                annotation['category_id'] = 1
            path.write_text(json.dumps(data))
            self.assertEqual(read_dataset(path, categories=categories)['categories'], categories)
            with self.assertRaises(ValueError):
                read_dataset(path)
            data['annotations'][0]['category_id'] = 2
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                read_dataset(path, categories=categories)

    def test_real_optimizer_checkpoint_reload_and_reproducible_cpu_weights(self):
        import torch
        from baseline import ROOT, MARKER, config, predict, train
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = generate(root / 'fixture')
            paths = {split: data / f'{split}.json' for split in ('train', 'validation', 'test')}
            settings = config(ROOT / 'configs/synthetic.json')
            for name in ('first', 'second'):
                result = train(paths, settings, root / name, software_check=True)
                self.assertTrue(result['classifier_weights_changed'])
                self.assertEqual(result['optimizer_steps'], 1)
                self.assertFalse(result['test_evaluated'])
                self.assertEqual(result['kind'], MARKER)
            first = torch.load(root / 'first/best.pt', weights_only=True, map_location='cpu')
            second = torch.load(root / 'second/best.pt', weights_only=True, map_location='cpu')
            for name, tensor in first['model'].items():
                self.assertTrue(torch.equal(tensor, second['model'][name]), name)
            a = predict(root / 'first/best.pt', paths['test'], root / 'a.json')
            b = predict(root / 'first/best.pt', paths['test'], root / 'b.json')
            self.assertEqual(a, b)
            with self.assertRaises(ValueError):
                predict(root / 'first/best.pt', paths['test'], root / 'a.json')

    def test_fixture_seed_hash_validation_and_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = generate(root / 'first'), generate(root / 'second')
            for split in ('train', 'validation', 'test'):
                self.assertEqual((first / f'{split}.json').read_bytes(), (second / f'{split}.json').read_bytes())
            paths = {split: first / f'{split}.json' for split in ('train', 'validation', 'test')}
            validate_splits(paths, True)
            with self.assertRaises(ValueError):
                validate_splits(paths, False)
            data = json.loads(paths['validation'].read_text())
            data['images'][0]['patient_group'] = 'synthetic-group-1'
            paths['validation'].write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                validate_splits(paths, True)
            changed = first / 'images/synthetic-1.png'
            changed.write_bytes(b'changed fixture')
            with self.assertRaises(ValueError):
                read_dataset(paths['train'])

    def test_smoke_real_data_not_synthetic_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = generate(Path(directory) / 'fixture')
            paths = {split: root / f'{split}.json' for split in ('train', 'validation', 'test')}
            data = json.loads(paths['train'].read_text())
            data['info']['dataset_kind'] = 'real_cytology'
            paths['train'].write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                validate_splits(paths, True)
            data['images'][0]['file_name'] = '../outside.png'
            paths['train'].write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                read_dataset(paths['train'])

    def test_diagnostic_matching_counts_wrong_grades_duplicates_and_misses(self):
        truth = {'images': [{'id': 1, 'file_name': 'fixture.png'}], 'annotations': [
            {'image_id': 1, 'category_id': 1, 'bbox': [0, 0, 10, 10]},
            {'image_id': 1, 'category_id': 2, 'bbox': [20, 20, 10, 10]}]}
        predictions = [{'image_id': 1, 'category_id': 3, 'bbox': [0, 0, 10, 10], 'score': .9},
                       {'image_id': 1, 'category_id': 1, 'bbox': [0, 0, 10, 10], 'score': .8}]
        result = diagnose(truth, predictions)
        self.assertEqual(result['counts'], {'matched_wrong_grade': 1, 'unmatched_predictions': 1, 'missed_targets': 1})
        self.assertEqual(iou([0, 0, 10, 10], [0, 0, 10, 10]), 1)


if __name__ == '__main__':
    unittest.main()
