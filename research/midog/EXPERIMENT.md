# Expanded canine histology experiment

This experiment compares two detector configurations on a pinned MIDOG++ cohort.
Every selected image record and the annotation record specifies CC0. The source
review preserves record URLs, published sizes, checksums and case assignments.

| Partition | Source cases | Selection |
| --- | --- | --- |
| Training | 250, 254, 255, 258, 259, 260 | Author training cases |
| Validation | 261, 263 | Author training cases reserved for model selection |
| Test | 253, 256, 257 | Author test cases reserved before model development |

Case 262 was skipped when its collection preview metadata did not resolve to
the author notebook's file identifier. Case 263 was selected by source availability
before training. Previously inspected pilot test cases 251 and 252 are excluded.
Grouping uses source case/ROI identifiers. Patient linkage remains unverified.

## Image preparation

All 448-pixel grid cores enter their source case partition, including empty
cores. Each core has 32 pixels of context on every side, yielding 512-pixel
model inputs. A source box belongs to exactly one core according to its center.
The context preserves its full box, including at internal core boundaries.
At source image edges, boxes remain clipped to valid source pixels and input
padding supplies the missing image context. Label totals must match source totals.

The dataset retains annotated hard negatives separately. They act as detector
background. The detector has one positive class, mitotic figure. Image SHA256
checks, source checksum checks and cross-partition duplicate-patch checks guard
input integrity. Predictions are retained only when their centers lie inside
their tile's valid core. Context objects can appear unlabeled near tile margins.

## Configurations

| Setting | Baseline | Small cells |
| --- | --- | --- |
| Detector | Faster R-CNN MobileNetV3 Large FPN | Same architecture |
| Initialization | Torchvision COCO_V1 | Same initializer |
| Input resolution | 256 × 256 | 512 × 512 |
| Anchor sizes on each FPN level | 32, 64, 128, 256, 512 | 16, 24, 32, 48, 64 |
| SGD learning rate | 0.001 | 0.005 |
| Epochs | 3 | 3 |
| Batch size | 2 | 2 |
| Backbone | Frozen | Frozen |
| Seed | 42 | 42 |
| Candidate boxes per tile | 32 | 32 |

Anchor counts and tensor shapes match the pretrained RPN head. The revised
configuration changes a bundle of resolution, anchor scales and learning rate.
Its comparison cannot isolate the effect of an individual change.

Each variant selects the highest validation AP50 checkpoint, then AP averaged
over IoU 0.50–0.95 to break a tie. Exact ties keep the earliest epoch.
Both variants finish training before either final test evaluation is inspected.
Evaluation reloads the selected checkpoint and verifies the dataset hashes.
Each run's test evaluation can be written once. The outputs include actual COCO
metrics, misses and unmatched predictions at score 0.5 and IoU 0.5, and overlays.

The initial expanded-cohort runs stopped on a nonfinite ROI loss. The MobileNet
wrapper defaults to a 0.05 RPN proposal threshold. After negative-only batches,
all proposals could be removed, leaving an empty classification input. Both
completed configurations set the proposal threshold to zero. A regression check
forces low proposal scores and empty targets, then verifies finite losses and
backpropagation. Failed runs are preserved under `runs/cohort-v2`.
The stable 100-proposal runs under `runs/cohort-v2-r1` were interrupted before
validation to reduce CPU cost. Training tiles contain at most four labeled
mitoses. Both completed configurations use a common 32-proposal budget under
`runs/cohort-v2-r2`.

The first three-case pilot used different data and boundary handling. Its zero
AP provides historical context. The paired expanded-cohort runs provide the
direct configuration comparison.

## Windows PowerShell commands

Run after installing the research environment described in `../phem/TRAINING.md`.
The pinned review already exists in this checkout. `pin` deliberately refuses
to overwrite that cohort definition.

```powershell
# run from the repository root
.\research\.venv\Scripts\python.exe research\midog\cohort.py fetch
.\research\.venv\Scripts\python.exe research\midog\experiment.py prepare
.\research\.venv\Scripts\python.exe research\midog\experiment.py train --variant baseline
.\research\.venv\Scripts\python.exe research\midog\experiment.py train --variant small-cells
.\research\.venv\Scripts\python.exe research\midog\experiment.py evaluate --variant baseline
.\research\.venv\Scripts\python.exe research\midog\experiment.py evaluate --variant small-cells
.\research\.venv\Scripts\python.exe research\midog\experiment.py compare
.\research\.venv\Scripts\python.exe research\midog\check_experiment.py -v
.\research\.venv\Scripts\python.exe -m unittest discover -s research\phem -p 'test_*.py' -v
.\research\.venv\Scripts\python.exe -m unittest discover -s research\midog -p 'test_*.py' -v
```

Preparation and training require fresh output directories. Use `--output` and
`--data` for subsequent immutable experiments. Downloads reuse verified files.
Default patches and model artifacts live in ignored `derived/cohort-v2` and
`runs/cohort-v2-r2` directories. The aggregate comparison is written to
`reports/cohort-v2-comparison.json`. Code snapshots, source and model hashes,
settings, dependency versions and epoch histories accompany the checkpoints.

The dataset is described by Aubreville, Wilm, Stathonikos and colleagues in
*A comprehensive multi-domain dataset for mitotic figure detection*, Scientific
Data 10, 484 (2023). The source files are distributed through the authors'
MIDOG++ Figshare collection.

[Dataset paper](https://doi.org/10.1038/s41597-023-02327-4)
[Author repository](https://github.com/DeepMicroscopy/MIDOGpp)
[Figshare collection](https://doi.org/10.6084/m9.figshare.c.6615571)
