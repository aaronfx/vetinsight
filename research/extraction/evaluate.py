"""Score record extraction on the synthetic records. Uses the app's own extraction code (backend/app/extraction.py).

Modes:
  --simulate perfect   a pretend model that copies the known answers (checks the scoring and the verification pipeline)
  --simulate sloppy    a pretend model that makes realistic mistakes (checks that the safeguards catch them)
  (neither)            a REAL model call per record. Needs ANTHROPIC_API_KEY and --yes. This spends money (cents).
Simulations are not model results. Only a real run says anything about a model's accuracy.
"""
import argparse, copy, json, os, pathlib, random, re, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
from pypdf import PdfReader
from app import extraction, labs

LAB_KEYS = ('analyte', 'name_as_written', 'value', 'qualifier', 'unit', 'range_low', 'range_high', 'range_unit', 'sample_note', 'quote')


def record_text(path):
    pages = []
    for number, page in enumerate(PdfReader(str(path)).pages, 1):
        text = page.extract_text() or ''
        pages.append({'page_number': number, 'text': text, 'status': 'extracted' if text.strip() else 'ocr_required'})
    return extraction.record_text(pages)


def field(value=None, quote=None):
    return {'value': value, 'quote': quote}


def perfect_raw(rec):
    raw = {name: field(rec['fields'][name], rec['field_quotes'][name]) if rec['fields'][name] else field() for name in extraction.SIMPLE_FIELDS}
    raw['medications'] = [field(m['value'], m['quote']) for m in rec['medications']]
    raw['lab_results'] = [{key: lab[key] for key in LAB_KEYS} for lab in rec['labs']]
    return raw


def sloppy_raw(rec, rng):
    """Realistic model mistakes: obeys an injected instruction, drops labs, misreads digits and units, invents ranges."""
    raw = copy.deepcopy(perfect_raw(rec))
    if 'prompt-injection' in rec['tags']:
        raw['species'] = field('Cat', 'Species: Cat')
    kept = []
    for lab in raw['lab_results']:
        roll = rng.random()
        if roll < 0.12:
            continue  # lab result missed
        if roll < 0.22 and lab['value'] is not None:
            lab['value'] = round(lab['value'] * rng.choice([0.5, 2, 1.1]), 2)  # misread digits; quote unchanged
        elif roll < 0.30:
            lab['unit'] = 'mmol/L'  # wrong unit
        elif roll < 0.40 and lab['range_low'] is None:
            lab['range_low'], lab['range_high'] = 30, 60  # invents a range that is not printed
        kept.append(lab)
    raw['lab_results'] = kept
    if rng.random() < 0.2 and raw['age']['value']:
        raw['age'] = field('7 years', raw['age']['quote'])  # a wrong value sitting under a real quote
    return raw


def norm(text):
    return re.sub(r'[^a-z0-9.]+', ' ', str(text or '').lower()).strip()


def new_counts():
    return dict(fields={n: dict(total=0, correct=0, missed=0, wrong=0, wrong_flagged=0, wrong_but_looks_verified=0, null_total=0,
                                null_ok=0, invented=0) for n in extraction.SIMPLE_FIELDS},
                labs=dict(gold=0, found=0, unit_ok=0, range_ok=0, flag_ok=0, missed_abnormal=0, wrong_abnormal=0, extra_labs=0,
                          extra_abnormal=0, gold_abnormal=0, gold_not_judged=0, not_judged_correct=0))


def score(rec, result, counts):
    for name, gold in rec['fields'].items():
        got, c = result['fields'][name], counts['fields'][name]
        if gold is None:
            c['null_total'] += 1
            c['null_ok' if got['value'] is None else 'invented'] += 1
            continue
        c['total'] += 1
        if got['value'] is not None and (norm(got['value']) == norm(gold) or norm(gold) in norm(got['value'])):
            c['correct'] += 1
        elif got['value'] is None:
            c['missed'] += 1
        else:
            c['wrong'] += 1
            flagged = got['found_in_record'] is False or got['value_in_quote'] is False  # the app shows a warning badge
            c['wrong_flagged'] += flagged
            c['wrong_but_looks_verified'] += not flagged
    remaining, lab = list(result['lab_results']), counts['labs']
    for gold in rec['labs']:
        lab['gold'] += 1
        abnormal = gold['expected_flag'] in ('low', 'high')
        lab['gold_abnormal'] += abnormal
        lab['gold_not_judged'] += gold['expected_flag'] == 'not_judged'
        match = next((l for l in remaining if l['analyte'] == gold['analyte'] and l['value'] is not None and abs(l['value'] - gold['value']) < 1e-6), None)
        if match is None:
            lab['missed_abnormal'] += abnormal
            continue
        remaining.remove(match)
        lab['found'] += 1
        lab['unit_ok'] += labs.normalise_unit(match['unit']) == labs.normalise_unit(gold['unit'])
        lab['range_ok'] += (match['range_low'], match['range_high']) == (gold['range_low'], gold['range_high'])
        lab['flag_ok'] += match['flag'] == gold['expected_flag']
        lab['not_judged_correct'] += gold['expected_flag'] == 'not_judged' and match['flag'] == 'not_judged'
        lab['missed_abnormal'] += abnormal and match['flag'] != gold['expected_flag']
        lab['wrong_abnormal'] += match['flag'] in ('low', 'high') and match['flag'] != gold['expected_flag']
    lab['extra_labs'] += len(remaining)
    lab['extra_abnormal'] += sum(1 for l in remaining if l['flag'] in ('low', 'high'))


def summarise(counts):
    f, l = counts['fields'], counts['labs']
    total = sum(c['total'] for c in f.values()); correct = sum(c['correct'] for c in f.values())
    nulls = sum(c['null_total'] for c in f.values())
    return dict(
        fields=dict(gold_values=total, correct=correct, accuracy=round(correct / max(total, 1), 3),
                    wrong_values=sum(c['wrong'] for c in f.values()),
                    wrong_and_flagged_with_a_warning=sum(c['wrong_flagged'] for c in f.values()),
                    wrong_but_looks_verified=sum(c['wrong_but_looks_verified'] for c in f.values()),
                    empty_fields=nulls, invented_for_empty=sum(c['invented'] for c in f.values()),
                    per_field={n: f"{c['correct']}/{c['total']}" for n, c in f.items()}),
        labs=dict(gold_results=l['gold'], found=l['found'], recall=round(l['found'] / max(l['gold'], 1), 3),
                  unit_correct=l['unit_ok'], range_correct=l['range_ok'], flag_correct=l['flag_ok'],
                  flag_accuracy=round(l['flag_ok'] / max(l['gold'], 1), 3),
                  gold_abnormal=l['gold_abnormal'], missed_abnormal=l['missed_abnormal'],
                  wrong_low_or_high_flags=l['wrong_abnormal'], extra_results_not_in_gold=l['extra_labs'],
                  extra_results_flagged_low_or_high=l['extra_abnormal']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--simulate', choices=['perfect', 'sloppy'])
    ap.add_argument('--records', default=str(HERE / 'synthetic'))
    ap.add_argument('--model', default=None, help='sets VETINSIGHT_EXTRACTION_MODEL for this run')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--yes', action='store_true', help='confirm a real, paid model run')
    ap.add_argument('--out', default=None, help='report JSON path')
    args = ap.parse_args()
    if args.model:
        os.environ['VETINSIGHT_EXTRACTION_MODEL'] = args.model
    gold = json.loads((pathlib.Path(args.records) / 'gold.json').read_text())['records'][: args.limit]
    if not args.simulate:
        if not extraction.available():
            raise SystemExit(f'Not available: {extraction.unavailable_reason()}')
        if not args.yes:
            raise SystemExit(f'This will make {len(gold)} paid calls to {extraction.model_name()}. Re-run with --yes to confirm.')
    rng, counts, usage = random.Random(7), new_counts(), dict(input_tokens=0, output_tokens=0)
    failures = 0
    for rec in gold:
        text = record_text(pathlib.Path(args.records) / 'records' / rec['file'])
        if args.simulate == 'perfect':
            raw = perfect_raw(rec)
        elif args.simulate == 'sloppy':
            raw = sloppy_raw(rec, rng)
        else:
            try:
                raw, used = extraction.call_model(text)
                usage['input_tokens'] += used['input_tokens']; usage['output_tokens'] += used['output_tokens']
            except extraction.UserError as exc:
                failures += 1
                print(f'{rec["id"]}: {exc}')
                continue
        score(rec, extraction.build_result(raw, text), counts)
    report = dict(mode=f'SIMULATION ({args.simulate}) - not a model result' if args.simulate else f'real model: {extraction.model_name()}',
                  records=len(gold), failed_records=failures, usage=None if args.simulate else usage, summary=summarise(counts))
    print(json.dumps(report, indent=2))
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
