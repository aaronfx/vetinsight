# MIDOG backup experiment: canine histology

The expanded eleven-case experiment is documented in [EXPERIMENT.md](EXPERIMENT.md).
Its paired held-out metrics, localization measurements and limitations are in
[RESULTS.md](RESULTS.md). Baseline AP50 was 0.000398 and revised AP50 was 0.094443.
At the fixed score threshold of 0.5, both models missed all 138 test mitoses.

Update November 4, 2026: a distinct MIDOG++ release now provides a verified
alternative for selected canine files. See [ALTERNATIVE.md](ALTERNATIVE.md)
and `reports/midogpp-source-review.json`. The restrictions below still apply
to the older MIDOG 2022 PNG release.

This is an offline alternative to P-Hem, not a deployed VetInsight feature.
The scientific task is **mitotic figure detection in canine histology tissue**.
It does not establish performance on cytology smears, diagnose cancer, or replace
the pending P-Hem permissions/patient-grouping request.

## Verified source

- Organizers' domain mapping: https://midog.deepmicroscopy.org/2022/download-dataset
- PNG release: https://zenodo.org/records/6547151
- Annotation file: `MIDOG2022_training_png.json`, MD5
  `83002a6cc8c9a1de890fd6b7fcc04686`.
- Cases 151–194: canine lung carcinoma; 195–249: canine lymphoma;
  250–299: canine mast cell tumor. IDs identify source cases/ROIs; they are
  not evidence of independent patients.

The source JSON calls its format COCO, but its boxes are **x1,y1,x2,y2**.
The importer converts to COCO x,y,width,height, clips border boxes, and reports
the number clipped. Category 1 is the only detector target. Category 2 denotes
annotated hard negatives and is retained separately, never relabeled as mitosis.
It does not represent exhaustive annotation of every nonmitotic cell.

## Current restriction

The Zenodo record specifies **CC BY 4.0**, while the embedded annotation license
specifies **CC BY-NC-ND 2.0**. Applicability is unresolved. No images have been
downloaded for this experiment, no detector trained, and no source images or
annotations are checked into this repository. `prepare` fails until documented
image-preparation terms are recorded in `rights-review.json`. This review is
specific to this release; a repository's software license is not image-use evidence.

The authors' newer MIDOG++ repository was also inspected:
https://github.com/DeepMicroscopy/MIDOGpp . Its setup notebook lists individual
Figshare downloads. The inspected Figshare article 22691092 contains only
`400.tiff`; its CC0 metadata must not be generalized to all images. No upstream
notebook, pickle, or training code was executed.

## Windows PowerShell commands

Run from the repository root, using the existing research
virtual environment (separate from the backend environment):

```powershell
.\research\.venv\Scripts\python.exe research\midog\pipeline.py fetch-metadata
.\research\.venv\Scripts\python.exe research\midog\pipeline.py audit
.\research\.venv\Scripts\python.exe -m unittest discover -s research\midog -p "test_*.py" -v
```

After applicable terms are verified, obtain only the selected images from the
record, verify their published checksums, put them in the ignored `raw` directory,
and run:

```powershell
.\research\.venv\Scripts\python.exe research\midog\pipeline.py prepare --cases 250 251 252
```

Preparation checks source checksum, schema, case selection, image dimensions,
and records image SHA256 hashes. Its output is a full-ROI annotation manifest,
not a trained model or patch dataset. Local metadata and derived output are
ignored by Git and excluded from the production Docker image.

## Next experiment

1. Resolve image-use terms with evidence; keep training permission separately explicit.
2. Download a bounded canine subset and visually inspect converted boxes.
3. Define case-grouped train/validation/test splits before patch extraction.
   Establish patient linkage where possible and disclose remaining independence limits.
4. Adapt the detector to one positive class plus background, retaining hard-negative
   examples. P-Hem's five-grade head must not be reused unchanged.
5. Run a small CPU engineering pilot, then evaluate on untouched held-out cases.
   Report actual AP/recall and failure examples with sample counts and limitations.

Do not combine MIDOG and P-Hem evaluation results: these are different tasks,
stains, species distributions, and specimen types.
