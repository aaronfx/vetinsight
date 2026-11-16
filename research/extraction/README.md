# Record extraction: synthetic test set and scoring

Test bench for the experimental "Extract fields" feature (`backend/app/extraction.py`, `backend/app/labs.py`).
**Everything here is synthetic.** Names, values and the reference ranges printed in the records are invented test fixtures,
not real patients and not clinical reference intervals.

## What the feature does

A language model reads the text of a PDF record and returns fields (patient, species, breed, sex, age, weight, visit date,
complaint, medications, any written diagnosis) and lab results (value, unit, printed range), each with the exact passage it
came from. Then the server, not the model:

1. checks that every passage really appears in the record and that a lab value's number appears in its passage;
2. ignores a printed range whose numbers are not in the passage;
3. compares each lab value with the range **printed in the same record** using fixed rules (`labs.py`), converting units only
   where the conversion is exact. With no printed range, an unknown unit, a qualifier ("<10") or an implausible value, the
   result is "not judged".

Nothing is interpreted, no range is supplied from memory, and no case field is changed.

## Files

- `make_records.py` builds 30 text PDFs and `synthetic/gold.json` (172 lab results; 64 expected abnormal) with traps: unit styles
  (%, L/L, g/L, K/uL, /uL), missing ranges, "<10" qualifiers, haemolysed-sample notes, absent fields, a prompt-injection line
  in 3 records, distractor numbers.
- `evaluate.py` scores extraction on them with the app's own code.

```powershell
# From the project root. No key needed for the two simulations.
.\backend\.venv\Scripts\python.exe research\extraction\evaluate.py --simulate perfect
.\backend\.venv\Scripts\python.exe research\extraction\evaluate.py --simulate sloppy

# A real, paid run (cents). Needs your own key in the environment; never paste a key into chat or code.
$env:ANTHROPIC_API_KEY = '<your key>'
.\backend\.venv\Scripts\python.exe research\extraction\evaluate.py --model claude-haiku-5-5 --yes --out research\extraction\runs\haiku.json
.\backend\.venv\Scripts\python.exe research\extraction\evaluate.py --model claude-sonnet-5-5 --yes --out research\extraction\runs\sonnet.json
```

## Results so far: simulations only, NOT a model result

| Pretend model | Field values correct | Wrong values | Wrong and warned | Wrong but looks verified | Labs found | Flags correct | Wrong LOW/HIGH flags |
|---|---|---|---|---|---|---|---|
| perfect (copies the answers) | 240/240 | 0 | 0 | 0 | 172/172 | 172/172 | 0 |
| sloppy (drops results, misreads digits, wrong units, invents ranges, obeys the injected line, changes an age) | 228/240 | 12 | 12 | 0 | 127/172 | 120/172 | 0 |

What this shows: the scoring works, the generator's passages survive PDF text extraction, and the safeguards turn those
particular mistakes into warnings or "not judged" instead of a false LOW/HIGH. In the sloppy run 19 of 64 abnormal results were
not reported as abnormal, always safely (missing or not judged), never wrongly.

What it does not show: how any real model behaves. A real model can make mistakes the simulation does not, for example quoting
a passage that spans two lines and so pairing a value with the wrong range.

## Real model results (16 November 2026, same 30 synthetic records)

| Model and instruction | Field values correct | Wrong but looks verified | Lab values found (unit and range correct) | Flags correct | Abnormal missed | Wrong LOW/HIGH flags | Tokens in / out | Approx. cost |
|---|---|---|---|---|---|---|---|---|
| Haiku 5.5, whole-line quote rule (current) | 240/240 | 0 | 172/172 | 172/172 | 0/64 | 0 | 70,481 / 47,310 | $0.03 |
| Sonnet 5.5, earlier instruction | 240/240 | 0 | 172/172 | 172/172 | 0/64 | 0 | 69,341 / 26,869 | $0.41 |
| Haiku 5.5, earlier instruction, run 2 | 240/240 | 0 | 172/172 | 161/172 | 4/64 | 0 | 69,341 / 45,541 | $0.03 |
| Haiku 5.5, earlier instruction, run 1 | 240/240 | 0 | 172/172 | 165/172 | 5/64 | 0 | 69,341 / 45,064 | $0.03 |

Species was correct in all 30 records, including the 3 with an injected instruction to change it. With the earlier instruction,
Haiku sometimes quoted only the value and unit (`24.3 K/uL`) without the printed range, so the server could not confirm the
range and left those results "not judged": safe, but incomplete. Requiring each lab quote to be the whole result line fixed
it. Runs vary: the two earlier Haiku runs differed by 4 flags, so repeat runs before relying on a single number.
Costs are estimates from the token counts at the listed prices of $0.10/$0.50 (Haiku 5.5) and $2/$10 (Sonnet 5.5) per
million input/output tokens.

## Limits

- 30 records, one author, invented ranges; real reports are messier (tables, scans, other languages).
- Scanned PDFs without embedded text are refused (no OCR).
- Only seven blood count tests are judged: PCV/HCT, hemoglobin, RBC, WBC, platelets, MCV, MCHC.
- Veterinary reference intervals depend on analyser, species, age and breed. The app never supplies a range; a fallback table
  would need a citable source checked by a clinician.
