# MIDOG++ three-case engineering experiment

## Completed run on November 4, 2026

All three image downloads passed their published length and MD5 checks.
The training case yielded 130 tiles with 140 mitosis labels. The two evaluation
cases yielded 260 tiles with 72 labels. The fixed epoch completed 65 optimizer
steps, changed classifier weights, and saved and reloaded the checkpoint.
Training plus evaluation took approximately 66 seconds on this machine.

Held-out COCO AP at IoU 0.50 and AP averaged over IoU 0.50–0.95 were both 0.00.
At score 0.5 and IoU 0.5, all 72 targets were missed and five predictions were
unmatched. Across all scores, the model produced 428 detections. Median predicted
box dimensions were approximately 471 by 453 pixels, compared with 50 by 50
pixels for source labels. The largest target/prediction IoU was approximately
0.024. These observations identify a localization-scale failure in this run.

Visual sample checks show converted source boxes aligned with source images.
Insufficient adaptation of generic-object initialization to small mitotic figures
is a hypothesis to investigate. Further development should investigate anchor
scales, image resolution and a larger training cohort using a training/validation
partition. Reserve additional untouched cases for final evaluation.

Aggregate metrics, provenance and diagnostics are saved in
`reports/pilot-result.json`. Local error overlays are under
`runs/midogpp-pilot/errors/`. The source code used for training is snapshotted
alongside the checkpoint. Twelve existing research tests, one new category-map
regression test and six MIDOG import tests passed during this work.

The pilot uses canine lymphosarcoma source case 250 for training and cases
251–252 for evaluation, following the authors' `datasets_xvalidation.csv`.
Each selected image and annotation record specifies CC0. The annotation JSON
also embeds CC0. The source review records exact file checksums and license URLs.

The detector is Torchvision Faster R-CNN MobileNetV3 Large FPN initialized with
COCO_V1 weights and a replacement two-output classifier for background and mitosis.
The backbone is frozen. Training runs on CPU with seed 42, two threads, batch size
two and SGD learning rate 0.001 for one fixed epoch. The saved final checkpoint
is reloaded before evaluation. Evaluation uses the shared pycocotools bbox evaluator.

Images are tiled on a deterministic 512-pixel nonoverlapping grid. All tiles,
including empty tiles, enter their source case's split. Tiles are padded at the
right and bottom edges. Model input is resized to 256 pixels. Source boxes use
corner coordinates and are assigned once by center, clipped to their tile.
Hard-negative labels are retained as metadata and treated as detector background.
Boundary fragments of objects centered in adjacent tiles may remain visible.
This is a limitation of this initial tile-based experiment.

The cohort contains one training case and two evaluation cases. Patient linkage
is unverified. These counts and the input downsampling limit interpretation of
the measured performance. This pilot establishes execution on real histology
data. A larger reserved cohort is required for subsequent research evaluation.
Once these cases have been used for development, reserve different cases for
the future final evaluation.

## Windows PowerShell

Run from the project directory with the research environment installed.

```powershell
Set-Location 'C:\Users\User\Documents\Codex\vetinsight'
.\research\.venv\Scripts\python.exe research\midog\pilot.py fetch
.\research\.venv\Scripts\python.exe research\midog\pilot.py prepare
.\research\.venv\Scripts\python.exe research\midog\pilot.py train
.\research\.venv\Scripts\python.exe research\midog\errors.py
```

The default dataset directory is `research/midog/derived/midogpp-pilot`.
The run directory is `research/midog/runs/midogpp-pilot`. Preparation and training
require fresh output directories. Use `--output` to preserve previous runs when
repeating an experiment. Downloads reuse only files that pass their published
length and MD5 checks.

The dataset includes `label-review.jpg` for visual box checks. The run contains
the checkpoint, source and code hashes, configuration, held-out predictions,
evaluation metrics and training summary. Source images, patches and model files
are ignored by Git and excluded from the production Docker build.
