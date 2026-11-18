# Baseline training and inference

The first detector baseline is Torchvision's `fasterrcnn_mobilenet_v3_large_fpn`, with a six-output head (background plus source grades 0–4). Real experiments initialize from the explicit `COCO_V1` generic-object weights, replace the original classifier, freeze the backbone and train the region-proposal network/box head. This is a baseline for future evaluation, not a validated cytology model. Architecture reference: https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.detection.fasterrcnn_mobilenet_v3_large_fpn.html

## What has actually been verified

- CPU PyTorch 2.15.0+cpu and Torchvision 0.29.2+cpu import and execute on this checkout's Python 3.14. No CUDA device was available; GPU execution has not been checked.
- Twelve research tests pass. An end-to-end test performs two actual, seeded synthetic training runs, verifies an optimizer step changes classifier weights, loads checkpoints using `weights_only=True`, compares all resulting model tensors for exact equality, and checks repeated predictions match.
- Both random initialization and official COCO-pretrained initialization completed one optimizer step on generated geometry fixtures. Reload/inference/COCO evaluation and an error-example image were generated successfully. The pretrained model's FrozenBatchNorm architecture is restored without downloading the initializer during checkpoint inference.
- The synthetic fixture has two training images, one validation image and one test image, each with five generated ellipse boxes. These are **not cells**. Outputs carry `SYNTHETIC_SOFTWARE_CHECK_NOT_VETERINARY_PERFORMANCE`. Synthetic metrics are only checks that the software runs; none establish detection or diagnostic accuracy.
- No P-Hem images were used for training. The deployed Railway application has not been changed by this research work.

## Install the separate CPU training environment

From Windows PowerShell:

```powershell
# run from the repository root
.\research\.venv\Scripts\python.exe -m pip install -r research/requirements-training.txt
.\research\.venv\Scripts\python.exe -m pip check
```

The research virtual environment is created as documented in README.md. The training requirements pin the tested CPU builds; GPU training would require a separately tested compatible environment. Do not install these dependencies in the FastAPI environment or Railway image. The official pretrained initializer is about 74 MB and cached under ignored `research/phem/runs/model-cache/`. Models, raw data, generated images and run artifacts are ignored by Git and excluded from the Docker build.

## Reproduce the synthetic software check

Use fresh output directories; existing fixture/run/prediction files are not overwritten.

```powershell
.\research\.venv\Scripts\python.exe research/phem/baseline.py synthetic --output research/phem/derived/my-synthetic-fixture
.\research\.venv\Scripts\python.exe research/phem/baseline.py train --data research/phem/derived/my-synthetic-fixture --config research/phem/configs/synthetic.json --output research/phem/runs/my-synthetic-run --software-check
.\research\.venv\Scripts\python.exe research/phem/baseline.py predict --checkpoint research/phem/runs/my-synthetic-run/best.pt --data research/phem/derived/my-synthetic-fixture/test.json --output research/phem/runs/my-synthetic-run/test-predictions.json
.\research\.venv\Scripts\python.exe research/phem/evaluate.py --ground-truth research/phem/derived/my-synthetic-fixture/test.json --predictions research/phem/runs/my-synthetic-run/test-predictions.json --output research/phem/runs/my-synthetic-run/test-software-evaluation.json --software-check
.\research\.venv\Scripts\python.exe research/phem/failure_report.py --ground-truth research/phem/derived/my-synthetic-fixture/test.json --predictions research/phem/runs/my-synthetic-run/test-predictions.json --output research/phem/runs/my-synthetic-run/errors
.\research\.venv\Scripts\python.exe -m unittest discover -s research/phem -p test_*.py -v
```

To exercise pretrained initialization on synthetic fixtures, copy `configs/synthetic.json` to a local run config and set `pretrained` to true, keeping `--software-check`. This only tests the initializer/training path; a pretrained generic-object backbone is not an evaluated cell detector.

## Run outputs and reproducibility

`run.json` records settings, category mapping, Python/Torch/Torchvision versions, code hashes, source dataset hashes, and image hashes. A pretrained run also records the initializer URL and SHA-256. `history.json` records training loss and validation AP per epoch, tagged with the run kind. `last.pt` and `best.pt` contain model state, optimizer state, epoch and provenance; the best checkpoint is selected by validation AP only, keeping the earliest epoch on ties. Training never evaluates the test set. Checkpoints support inference; automatic training resume is not implemented.

Seeds are explicit, deterministic Torch algorithms are enabled, and data loading uses zero worker subprocesses with a seeded shuffle generator. Exact reproducibility was tested on the same CPU/software environment; it is not guaranteed across hardware/library versions. Nonfinite loss/gradients stop training. Keep checkpoints from trusted sources even when using the restricted loader.

Inference outputs COCO result boxes in original image pixel `xywh`, scores and the unchanged category IDs 1–5. A sidecar binds the predictions to dataset/checkpoint hashes. Synthetic checkpoints cannot be applied to real data through this CLI. `failure_report.py` creates thresholded missed-target, unmatched-prediction and wrong-grade counts, a confusion table and up to 12 overlays. Its class-agnostic greedy diagnostic matching is explicitly separate from standard COCO AP; thresholds are fixed at score 0.5 / IoU 0.5 for this first report implementation.

## Real-data training contract (pending)

Real training does not accept `--software-check`. It recomputes `readiness.check` against the source audit, rights review and patient grouping file before loading the dataset. It will currently refuse to run because the external evidence remains pending.

The data directory must contain `train.json`, `validation.json` and `test.json` with:

- Exactly the category mapping generated in `baseline_data.CATEGORIES`; actual patch labels for every grade in each split.
- `info.annotation_source_sha256` bound to the reviewed source annotation hash.
- For every image: integer ID, relative filename, width/height, SHA-256, `source_slide`, `patient_group` and exact `split` (`train`, `validation`, `test`). Patient and split must match the approved slide map.
- Valid non-crowd COCO boxes. Paths must remain inside the dataset directory; decoded image dimensions and bytes must match metadata.

The loader rejects patients, slides and byte-identical images crossing splits. It does not detect differently encoded near-duplicate images or establish the truth of a supplied patient map; those require data review. Test metadata is read for leakage checks, but test predictions/metrics are not used to choose checkpoints.

The future real-data command is:

```powershell
.\research\.venv\Scripts\python.exe research/phem/baseline.py train --data research/phem/derived/approved-patches --config research/phem/configs/baseline.json --output research/phem/runs/baseline-001
```

The approved multi-slide patch dataset does not exist yet. Preparation remains dependent on verified image rights, patient grouping and label/source review. The current eight P-Hem smoke patches are ineligible. They have no test partition, and were selected around annotated cells rather than representative areas. Class imbalance, stain variation, small independent patient counts and crowded-slide detection limits must be addressed in the experiment design before claiming generalization.

The baseline uses fixed learning rate/SGD, no augmentation or scheduler, and a frozen generic-object backbone. These choices make the first experiment inspectable; they are not asserted to be optimal. Later comparisons should be planned and selected on validation data without repeatedly tuning on the test set.
