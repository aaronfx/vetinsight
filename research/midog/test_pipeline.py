import copy
import json
from pathlib import Path
import tempfile
import unittest

from pipeline import convert, require_rights, xywh


class ImportTests(unittest.TestCase):
    def fixture(self):
        return {'categories': [{'id': 1, 'name': 'mitotic figure'}, {'id': 2, 'name': 'not mitotic figure'}],
                'images': [{'id': 250, 'file_name': '250.png', 'width': 100, 'height': 100}],
                'annotations': [{'id': 1, 'image_id': 250, 'category_id': 1, 'bbox': [10, 20, 60, 70]},
                                {'id': 2, 'image_id': 250, 'category_id': 2, 'bbox': [30, -6, 80, 44]}]}

    def test_corners_are_not_widths(self):
        self.assertEqual(xywh([4336, 346, 4386, 396], 6447, 4835), ([4336, 346, 50, 50], False))

    def test_negatives_are_not_positive_labels(self):
        data, clipped = convert(self.fixture(), [250])
        self.assertEqual(len(data['annotations']), 1)
        self.assertEqual(len(data['hard_negatives']), 1)
        self.assertEqual(data['hard_negatives'][0]['bbox'], [30, 0, 50, 44])
        self.assertEqual(clipped, 1)

    def test_reject_invalid_boxes(self):
        for box in ([0, 0, float('nan'), 3], [5, 5, 2, 2], [101, 0, 110, 20], [1, 2, 3]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                xywh(box, 100, 100)

    def test_reject_wrong_domains_and_schema(self):
        for ids in ([], [250, 250], [1], [999]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                convert(self.fixture(), ids)
        data = self.fixture()
        data['categories'][0]['name'] = 'unexpected'
        with self.assertRaises(ValueError):
            convert(data, [250])

    def test_reject_duplicate_annotations(self):
        data = self.fixture()
        data['annotations'].append(copy.deepcopy(data['annotations'][0]))
        with self.assertRaises(ValueError):
            convert(data, [250])

    def test_rights_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rights.json'
            for value in ({}, {'status': 'verified', 'image_preparation_permitted': True, 'evidence': ''},
                          {'status': 'unresolved', 'image_preparation_permitted': True, 'evidence': 'conflict'}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    require_rights(path)
            path.write_text(json.dumps({'status': 'verified', 'image_preparation_permitted': True,
                                        'evidence': 'TEST FIXTURE ONLY'}))
            require_rights(path)


if __name__ == '__main__':
    unittest.main()
