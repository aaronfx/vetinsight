# VetInsight

**AI-assisted veterinary case review: cytology cell detection and clinical-record extraction, evaluated honestly.**

Built by Aaron Benjamin Akwu, DVM, as an independent research project (2026).

**Demo video (2 min):** https://youtu.be/UCH08Gyb9-c

VetInsight is a working web app that tests whether AI can help with two everyday diagnostic jobs: reading cytology images and pulling structured data out of clinical records. Every model output is a suggestion that a person reviews. Nothing is saved as a finding until someone accepts it.

> This is a research prototype, not a diagnostic tool. All data in this repository is public (licensed below) or synthetic. No real patient data is included.

## What it does

### 1. Cell detection, classification and nucleus marking (computer vision)

- **Model:** a COCO-pretrained Faster R-CNN (MobileNetV3-FPN, PyTorch/torchvision), fine-tuned on APCData: 425 Pap-stained cytology fields with 3,619 expert-labelled cells in six Bethesda classes.
- **Evaluation:** smear-grouped train/validation/test splits, so images from the same smear never appear on both sides of the split.
- **Held-out test result (61 images):** cell-finding AP50 **0.675**; per-class AP50 0.83 for negative (NILM) cells and 0.03–0.25 for the rare abnormal classes, which have small test counts (for example HSIL n=8, SCC n=7). The app shows these limits next to every result.
- **Nucleus marking:** a classical colour-based method (NumPy + Pillow) marks the nucleus inside each detected cell and estimates the nucleus-to-cytoplasm ratio. On 476 held-out expert nucleus points, the marked nucleus contained the point for 74% of cells using expert boxes and 70% using detector boxes. N:C ratios are not yet validated against outlines.
- **Important limit:** APCData is human cervical cytology. This shows the method; it is not a veterinary result.

Code: [`research/apcdata/`](research/apcdata/) (training and evaluation), [`backend/app/analysis.py`](backend/app/analysis.py), [`backend/app/nuclei.py`](backend/app/nuclei.py).

### 2. Language-model extraction from clinical records (LLM)

- Claude (Haiku) extracts patient details, medications and lab results from a PDF record using a strict JSON schema. Every value must come with the **exact passage** it was taken from.
- The server **rejects any passage that is not found in the record**, and ignores a reference range that is not inside the quoted line.
- **Plain code, not the model,** compares each lab value with the reference range printed in that same record (with exact unit conversions). Where no range is printed, the value is marked "not judged" instead of guessed.
- **Test set:** 30 synthetic records with known answers and deliberate traps (a hidden instruction to change the species, unit variants, missing ranges, values with < and >).
- **Result with Claude Haiku 5.5:** 240/240 field values, 172/172 lab values with correct units and ranges, 172/172 lab flags correct, **0 wrong LOW/HIGH flags**. These are synthetic results; real veterinary records with patient-grouped evaluation are the next step.

Code: [`backend/app/extraction.py`](backend/app/extraction.py), [`backend/app/labs.py`](backend/app/labs.py), [`research/extraction/`](research/extraction/) (synthetic records, gold answers, evaluation script).

### 3. Negative results and data provenance

- Audited licensing and patient grouping for two public veterinary datasets: P-Hem (feline/equine BAL cytology) and MIDOG++ (canine histology).
- A case-grouped mitosis-detection baseline on MIDOG++ did **not** work (test AP50 0.09). It is reported, not hidden: [`research/midog/`](research/midog/), [`research/phem/`](research/phem/).

## The app

- **Backend:** FastAPI, SQLite or PostgreSQL, session sign-in with admin and member roles, audit log.
- **Frontend:** React + TypeScript (Vite): case library, record viewer, cytology workspace with model suggestions and manual review, COCO annotation export, dataset-split management.
- **Tests:** 91 backend and 34 frontend automated tests.
- **Deployment:** Docker on Railway.

## Run it locally

Requires Python 3.11+ and Node.js.

```powershell
# backend
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt -r backend/requirements-analysis.txt
cd backend; .venv/Scripts/python -m uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend; npm install; npm run dev
```

Open http://localhost:5173. The record-extraction feature stays off unless `ANTHROPIC_API_KEY` is set as a server environment variable (see [`backend/.env.example`](backend/.env.example)). Full setup, API and deployment notes: [`docs/development.md`](docs/development.md).

## Data and licences

- **APCData** (cervical cytology): Cuña Cabrera P., Pachiarotti V. E., Guerra R. Mendeley Data, V1, 2024. DOI [10.17632/ytd568rh3p.1](https://doi.org/10.17632/ytd568rh3p.1). Licence CC BY 4.0. Raw images are not committed; the scripts download and verify them.
- **MIDOG++** (canine histology): example tiles in `frontend/public/assets/research/` come from the CC0 release. Please cite the MIDOG++ paper (Aubreville et al., *Scientific Data*, 2023).
- **Synthetic records and cases** in `research/` and `test-assets/` were generated for this project and contain no real patients.

## Contact

Aaron Benjamin Akwu, DVM · linkedin.com/in/aaron-akwu-809356414
