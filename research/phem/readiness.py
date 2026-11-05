"""Validate explicit veterinary patient splits. Never infer patients from filenames."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from pipeline import ROOT, digest, write_json

FIELDS = ['slide', 'patient_group', 'split', 'grouping_evidence']
SPLITS = ('train', 'validation', 'test')


def make_template(audit, path):
    path = Path(path)
    if path.exists():
        raise ValueError('Template already exists; refusing to overwrite grouping work.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for item in audit['slides']:
            if item['species'] != 'human':
                writer.writerow({'slide': item['slide']})


def check(audit, grouping_path, rights):
    blockers, warnings = [], []
    expected = {item['slide']: item for item in audit['slides'] if item['species'] != 'human'}
    rows = {}
    patients = defaultdict(set)
    counts = {split: Counter() for split in SPLITS}
    split_patients = {split: set() for split in SPLITS}
    with Path(grouping_path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('Grouping map must contain exactly: ' + ', '.join(FIELDS))
        for row in reader:
            name = row['slide']
            if name not in expected or name in rows:
                raise ValueError('Unknown, human, or repeated slide in grouping map: ' + name)
            rows[name] = row
            patient, split, evidence = (row[field].strip() for field in FIELDS[1:])
            if not patient or split not in SPLITS or not evidence:
                blockers.append('Missing verified patient group/split/evidence: ' + name)
                continue
            patients[patient].add(split)
            split_patients[split].add(patient)
            counts[split].update({str(grade): value for grade, value in expected[name]['grades'].items()})
    for name in sorted(expected.keys() - rows.keys()):
        blockers.append('Missing slide from grouping map: ' + name)
    for patient, splits in patients.items():
        if len(splits) > 1:
            blockers.append('Patient crosses dataset splits: ' + patient)
    for split in SPLITS:
        if not split_patients[split]:
            blockers.append('No independently grouped patients assigned to ' + split)
        elif len(split_patients[split]) < 5:
            warnings.append('Fewer than five patient groups in ' + split + '; uncertainty will be high.')
        for grade in range(5):
            if not counts[split][str(grade)]:
                blockers.append(f'No grade {grade} labels in {split}; five-grade evaluation is incomplete.')
    if rights.get('status') != 'confirmed' or not rights.get('evidence') or not rights.get('permitted_use'):
        blockers.append('Image license/permission has not been confirmed with evidence and permitted use.')
    if rights.get('annotation_source_sha256') != audit['source_sha256']:
        blockers.append('Rights/review record is not bound to the audited annotation source hash.')
    return {'ready_for_experiment': not blockers, 'blockers': blockers, 'warnings': warnings,
            'annotation_source_sha256': audit['source_sha256'], 'grouping_sha256': digest(grouping_path),
            'patient_groups_by_split': {split: len(groups) for split, groups in split_patients.items()},
            'annotations_by_split_and_grade': {split: dict(counts[split]) for split in SPLITS},
            'evidence_status': 'Grouping and rights evidence is operator-supplied; code validates completeness and consistency, not external authenticity.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', action='store_true')
    parser.add_argument('--audit', type=Path, default=ROOT / 'reports/annotation-audit.json')
    parser.add_argument('--groups', type=Path, default=ROOT / 'patient-groups.csv')
    parser.add_argument('--rights', type=Path, default=ROOT / 'rights-review.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/training-readiness.json')
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding='utf-8'))
    if args.template:
        make_template(audit, args.groups)
        print('Created blank veterinary grouping map. Do not infer patient IDs.')
    else:
        result = check(audit, args.groups, json.loads(args.rights.read_text(encoding='utf-8')))
        write_json(args.output, result)
        print('READY' if result['ready_for_experiment'] else f'NOT READY: {len(result["blockers"])} unresolved checks. See {args.output}')
        return 0 if result['ready_for_experiment'] else 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
