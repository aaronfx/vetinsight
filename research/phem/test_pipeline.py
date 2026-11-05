import csv
from pathlib import Path
import tempfile
import unittest
import sqlite3
from contextlib import closing

from pipeline import annotations, audit, clipped_box


class PipelineTests(unittest.TestCase):
    def fixture(self, root, rows):
        target = root / 'input.csv'
        with target.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, delimiter=';', fieldnames=['unique_identifier', 'species', 'image_name', 'grade', 'vector', 'version'])
            writer.writeheader()
            for uid, grade, vector in rows:
                writer.writerow(dict(unique_identifier=uid, species='Cat', image_name='one.svs', grade=grade, vector=vector, version='Density'))
        return target

    def test_audit_preserves_grades_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.fixture(root, [('a', 0, "{'x1':1,'y1':2,'x2':4,'y2':6}"), ('b', 4, "{'x1':4,'y1':5,'x2':8,'y2':10}")])
            result = audit(path, root / 'report.json')
            self.assertEqual(result['total_annotations'], 2)
            self.assertEqual(result['annotations_by_grade'], {0: 1, 4: 1})
            self.assertEqual(result['total_slides'], 1)
            self.assertEqual(len(result['source_sha256']), 64)
            self.assertIn('UNVERIFIED', result['patient_grouping'])

    def test_duplicate_id_and_invalid_boxes_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for rows in [[('a', 0, "{'x1':1,'y1':2,'x2':0,'y2':6}")],
                         [('a', 8, "{'x1':1,'y1':2,'x2':4,'y2':6}")],
                         [('a', 0, "__import__('os').getcwd()")],
                         [('a', 0, "{'x1':1,'y1':2,'x2':4,'y2':6}")] * 2]:
                with self.assertRaises((ValueError, SyntaxError)):
                    list(annotations(self.fixture(root, rows)))

    def test_patch_translation_and_boundary_clipping(self):
        self.assertEqual(clipped_box([110, 220, 150, 270], 100, 200, 100, 100), [10, 20, 40, 50])
        self.assertEqual(clipped_box([90, 190, 110, 220], 100, 200, 100, 100), [0, 0, 10, 20])
        self.assertIsNone(clipped_box([0, 0, 10, 10], 100, 200, 100, 100))

    def test_sqlite_source_uses_class_names_and_two_corners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'annotations.sqlite'
            (root / 'images_meta_data.csv').write_text('file;species\none.svs;Feline\n')
            with closing(sqlite3.connect(path)) as db:
                db.executescript('''CREATE TABLE Annotations(uid,slide,agreedClass,deleted);
                    CREATE TABLE Slides(uid,filename);
                    CREATE TABLE Classes(uid,name);
                    CREATE TABLE Annotations_coordinates(uid,annoId,slide,coordinateX,coordinateY);
                    INSERT INTO Annotations VALUES(1,1,5,0);
                    INSERT INTO Slides VALUES(1,'one.svs');
                    INSERT INTO Classes VALUES(5,'4');
                    INSERT INTO Annotations_coordinates VALUES(1,1,1,10,20),(2,1,1,30,50);''')
            rows = list(annotations(path))
            self.assertEqual(rows, [{'id': 'sqlite-1', 'species': 'feline', 'slide': 'one.svs', 'grade': 4, 'box': [10, 20, 30, 50]}])
            self.assertEqual(list(annotations(path, 'missing.svs')), [])
            with closing(sqlite3.connect(path)) as db:
                db.execute('DELETE FROM Annotations_coordinates WHERE uid=2')
                db.commit()
            with self.assertRaises(ValueError):
                list(annotations(path))


if __name__ == '__main__':
    unittest.main()
