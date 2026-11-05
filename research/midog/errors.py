"""Produce error overlays for a completed MIDOG++ pilot checkpoint."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'phem'))
from failure_report import report
from pipeline import digest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'derived/midogpp-pilot')
    parser.add_argument('--run', type=Path, default=ROOT / 'runs/midogpp-pilot')
    args = parser.parse_args()
    truth = args.data / 'test.json'
    predictions = args.run / 'test-predictions.json'
    checkpoint = args.run / 'last.pt'
    evaluation = json.loads((args.run / 'evaluation.json').read_text())
    if digest(checkpoint) != evaluation['checkpoint_sha256']:
        raise ValueError('Checkpoint differs from evaluated checkpoint.')
    write_json(str(predictions) + '.provenance.json', {
        'kind': evaluation['kind'], 'dataset_sha256': digest(truth),
        'prediction_sha256': digest(predictions), 'checkpoint_sha256': digest(checkpoint)})
    result = report(truth, predictions, args.run / 'errors', categories=[{'id': 1, 'name': 'mitotic figure'}])
    print(json.dumps(result['counts'], indent=2))


if __name__ == '__main__':
    main()
