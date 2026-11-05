# P-Hem research data pilot

This is an offline data-readiness milestone for VetInsight, separate from the deployed application. It performs no training, automatic diagnosis, API calls or production writes. Images/annotations remain local and are excluded from Git and the Railway Docker build.

The separate [baseline training pipeline](TRAINING.md) now supports training/inference and has passed synthetic software checks. No real cytology data has been used for model training.

## Sources and permission status

- Marzahl et al. (2022), *Inter-species cell detection – datasets on pulmonary hemosiderophages in equine, human and feline specimens*, Scientific Data 9, 269: https://doi.org/10.1038/s41597-022-01389-0
- Author repository: https://github.com/ChristianMarzahl/EIPH_WSI/tree/master/SDATA
- Author-linked image collection: https://figshare.com/s/d48f0520b4fa164043b5
- `sources.json` records exact retrieved URLs, file sizes and SHA-256 hashes. Upstream URLs may change; download fails rather than accepting changed bytes. The authors' notebooks are downloaded as provenance only, never executed. Pickle files are not loaded.

The upstream repository's software/documentation is MIT licensed. **The separate license for slide pixels is still unverified.** The shared Figshare page returned an empty body and public metadata search did not locate the collection. The API file-download URL returned the 238 MB Aperio slide, rather than a metadata record. It has been retained locally for inspection. Do not infer image permission from the software or publication license. Do not publish image patches/weights or commence training until the image terms are established with the record or authors. No permission request has been sent.

## Verified data findings (2 November 2026)

| Finding | Observed result |
|---|---|
| Original CSV | 297,383 rows; 297,353 unique IDs |
| CSV coordinate defect | 61 rows contain malformed/truncated representations; 31 unique IDs affected |
| Duplicate CSV IDs | 25 IDs appear more than once |
| Author-provided SQLite | 297,322 annotations across 74 slides |
| SQLite species | 55 equine, 7 feline, 12 human slides |
| Selected veterinary slide | `BAL_Cat_Turnbull blue_1.svs`, 238,290,853 bytes |
| Selected slide dimensions | 32,399 × 32,362 level-0 pixels |
| Selected slide SQLite labels | 3,465 annotations |
| Smoke export | 8 patches of 1024 × 1024 pixels, 106 intersecting source boxes |

The strict CSV importer stops on malformed vectors/duplicate IDs. The pilot uses the author's SQLite as a separately identified source, not a repair of the CSV. The discrepancy of 61 records remains an unresolved provenance issue. The SQLite is opened read-only with trusted schema disabled; geometry must have exactly two corners. Grades come from the class names, not their internal database IDs.

Reports are in `reports/annotation-audit.json` and `reports/csv-quality.json`. The original sources are unmodified. The patch manifest records all source/image hashes and level-0 origins. Every box intersecting a patch is retained, clipped to patch boundaries, and marked when truncated. Classes use COCO IDs 1–5 mapped explicitly to source grades 0–4. These boxes locate the dataset's target macrophages/hemosiderophages, not every cell visible in the image.

No patient-independent split exists. Metadata does not provide a verified patient map; paired stains/specimens can belong to the same animal. Filenames/specimen numbers must not be assumed to be patient IDs. All pilot patches are tagged `smoke_only` and kept in a single source-slide group. This annotation-centred sample is biased and cannot estimate model performance. This feline slide also does not cover all five grades.

## Exact PowerShell commands

From the project root, create the isolated research environment (this checkout uses Python 3.14):

```powershell
Set-Location 'C:\Users\User\Documents\Codex\vetinsight'
py -m venv research/.venv
.\research\.venv\Scripts\python.exe -m pip install -r research/requirements.txt
```

Re-fetch/verify annotation/provenance files (about 92 MB total), with an optional single 238 MB slide for local inspection:

```powershell
.\research\.venv\Scripts\python.exe research/phem/fetch.py
.\research\.venv\Scripts\python.exe research/phem/fetch.py --include-smoke-slide
```

Audit both representations and prepare a fresh patch run:

```powershell
.\research\.venv\Scripts\python.exe research/phem/pipeline.py csv-quality
.\research\.venv\Scripts\python.exe research/phem/pipeline.py audit
.\research\.venv\Scripts\python.exe research/phem/pipeline.py patches --slide 'research/phem/raw/BAL_Cat_Turnbull blue_1.svs' --output research/phem/derived/my-smoke-run --limit 8
.\research\.venv\Scripts\python.exe -m unittest discover -s research/phem -p test_pipeline.py -v
```

Use a new output directory each run. Open `source-labels-contact-sheet.png` inside that directory for visual QA. Labels are author-supplied annotations, never model predictions. The export contains COCO `annotations.json`, PNG patches and `manifest.json`; nothing is uploaded to VetInsight automatically.

## Validation and next research milestone

Four unit tests pass: source/class mapping, provenance counts, invalid input/duplicate rejection, and coordinate translation/boundary clipping. Two independent real-slide patch runs produced identical PNG checksums and identical COCO annotations. The contact sheet was visually inspected for label alignment; clinical label correctness has not been independently adjudicated. Research dependency checks passed. These are import checks, not precision/recall or diagnostic metrics.

Before training:

1. Resolve image licensing and the CSV/SQLite discrepancy; record the usable source/version.
2. Obtain an authoritative patient/specimen grouping map. Fix train/validation/test groups before extracting training patches.
3. Select a veterinary subset with adequate coverage of the intended grades. Count independent animals and class frequencies; the current one-slide subset cannot support generalization claims.
4. Define a baseline and a held-out protocol. Record detection metrics and per-grade confusion/errors without tuning on the test set. Later integrate only the evaluated model, with versioned weights and explicit research-only outputs.

An OpenAI API key is not required for this cytology data work. Clinical-record LLM extraction is a separate workstream and remains awaiting a provider/credential decision.

## Continuation: reconciliation, split review and evaluation

The exact multiset comparison in `reconcile.py` establishes that **all 297,322 valid CSV boxes and grades match the SQLite**, with no extra usable rows in either representation. The difference is confined to the 61 malformed CSV rows. This resolves usable-format consistency; it does not establish biological label accuracy or recover those rows. See `reports/source-reconciliation.json`.

`patient-groups.csv` contains 62 veterinary slide names with deliberately blank patient groups, splits and evidence. Human slides are excluded. Fill this from an authoritative mapping, not filename guesses. `rights-review.json` records image-use evidence and permitted use once obtained. `readiness.py` checks completeness, repeated/unknown slide rows, cross-split patient leakage, all five grades in each split, and the source annotation hash. It reports missing data explicitly and exits 2 while incomplete. Evidence remains operator-supplied; a passing check does not itself prove legal permission, patient independence or statistically adequate sample size.

```powershell
.\research\.venv\Scripts\python.exe research/phem/reconcile.py
.\research\.venv\Scripts\python.exe research/phem/readiness.py
.\research\.venv\Scripts\python.exe -m unittest discover -s research/phem -p test_*.py -v
```

`evaluate.py` uses official pycocotools bounding-box evaluation (https://github.com/cocodataset/cocoapi). It reports standard AP/AR and per-grade AP. Missing categories/areas are null, not fabricated scores. Pixel boxes, IDs and confidence scores are validated. The protocol records the default 100-detection cap per image; whole-slide evaluation will need a separately specified cap/aggregation protocol for crowded slides. Real evaluation requires a ready experiment record, model ID, source hash and patient-grouped test images. Smoke data can only run in explicit `--software-check` mode, whose output is prominently labelled as software testing. COCO result predictions must be JSON objects with `image_id`, `category_id`, `bbox` (pixel xywh), and `score`.

Example for a future real held-out test set (not runnable with the current smoke-only patches):

```powershell
.\research\.venv\Scripts\python.exe research/phem/evaluate.py --ground-truth test-annotations.json --predictions model-predictions.json --readiness research/phem/reports/training-readiness.json --model-id 'baseline-checkpoint-sha256' --output research/phem/runs/test-evaluation.json
```

Eight research tests now pass, including synthetic perfect/empty/wrong-class evaluator cases, bad prediction rejection, patient leakage, missing permissions, absent grade coverage and rejection of smoke data as real model evaluation. These synthetic checks have no meaning as veterinary accuracy. No real predictions, model metrics or weights have been produced.

The remaining external questions are recorded in [author-questions.md](author-questions.md). Following explicit user instruction, the inquiry was sent to the corresponding author through connected Gmail (message/thread `1a19c7482fdb413b`, confirmed SENT). A reply remains pending. Until the required evidence is obtained, the actual readiness report remains NOT READY and the public app remains unchanged.
