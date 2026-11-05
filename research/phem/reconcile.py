"""Compare valid CSV geometries to author SQLite using exact multiset equality."""
import ast
from collections import Counter
import csv
from pathlib import Path

from pipeline import ROOT, annotations, digest, write_json


def key(slide, grade, box):
    return (slide, grade, *box)


def reconcile(csv_path, sqlite_path):
    valid, invalid = Counter(), []
    with Path(csv_path).open(encoding='utf-8-sig', newline='') as stream:
        for line, row in enumerate(csv.DictReader(stream, delimiter=';'), 2):
            try:
                if len(row['vector']) > 500:
                    raise ValueError('oversized/truncated vector')
                vector = ast.literal_eval(row['vector'])
                if not isinstance(vector, dict) or set(vector) != {'x1', 'y1', 'x2', 'y2'}:
                    raise ValueError('unexpected vector')
                box = [vector[field] for field in ('x1', 'y1', 'x2', 'y2')]
                valid[key(row['image_name'], int(row['grade']), box)] += 1
            except (ValueError, SyntaxError):
                invalid.append({'line': line, 'id': row['unique_identifier'], 'slide': row['image_name']})
    sqlite_rows = Counter(key(row['slide'], row['grade'], row['box']) for row in annotations(sqlite_path))
    csv_only, sqlite_only = valid - sqlite_rows, sqlite_rows - valid
    return {'csv_sha256': digest(csv_path), 'sqlite_sha256': digest(sqlite_path),
            'comparison': 'Exact (slide, grade, x1, y1, x2, y2) multiset comparison; no ID inference.',
            'valid_csv_rows': sum(valid.values()), 'sqlite_rows': sum(sqlite_rows.values()),
            'valid_csv_rows_missing_from_sqlite': sum(csv_only.values()),
            'sqlite_rows_missing_from_valid_csv': sum(sqlite_only.values()),
            'all_valid_geometries_and_grades_match': not csv_only and not sqlite_only,
            'malformed_csv_rows': len(invalid), 'malformed_records': invalid,
            'limitation': 'Equality of usable representations is not independent validation of biological labels or recovery of malformed records.'}


if __name__ == '__main__':
    result = reconcile(ROOT / 'metadata/SDATA_Final_Annotations.csv', ROOT / 'metadata/SDATA_Final_Annotations.sqlite')
    write_json(ROOT / 'reports/source-reconciliation.json', result)
    print({key: value for key, value in result.items() if key != 'malformed_records'})
