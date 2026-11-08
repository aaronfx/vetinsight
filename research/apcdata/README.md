# APCData cervical cytology cells (detection + classification demo data)

Downloaded 7 November 2026 for the VetInsight cell detection/classification demo.

- Source: https://data.mendeley.com/datasets/ytd568rh3p (Version 1, published 20 June 2024)
- DOI: 10.17632/ytd568rh3p.1
- Authors: Pablo Cuña Cabrera, Virginia Eva Pachiarotti, Rodrigo Guerra
- Licence: CC BY 4.0, as stated on the dataset page. Attribute the authors when using or showing results.
- Download: `https://data.mendeley.com/public-api/zip/ytd568rh3p/download/1`
- File: `raw/apcdata.zip`, 228,921,013 bytes
- SHA-256: `1E6ECC2DE07CF31C03CD5C4D5FDDBDA16DF01D1277DD05A627BB7F775D4D607A`

## Verified after download

Zip integrity test passed. 425 field images (2048 x 1532, 40x, liquid-based Pap smears), 425 YOLO label
files with 3,619 boxes. Counts match the dataset page exactly:

| Class | Boxes |
|---|---|
| NILM | 2,114 |
| ASC-US | 333 |
| ASC-H | 182 |
| LSIL | 444 |
| HSIL | 421 |
| SCC | 125 |

YOLO line format: `class x_center y_center width height` (normalised). `classes.txt` order: NILM, ASCUS, ASCH,
LSIL, HSIL, SCC. A second set (`APCData_points`) has nucleus point labels with Bethesda class.

## Limitations to state in any write-up

- Human cervical cytology. It is not veterinary data, and the page does not say "human" explicitly.
- No patient identifiers are given, so images from the same smear/patient may share a split. Do not claim
  patient-independent evaluation unless a grouping is established.
- Strong class imbalance. Boxes cover the annotated cells, not necessarily every cell in each field.
- Images and derived files are git-ignored. Do not commit them.

## Nucleus marking (classical, not a trained model)

`backend/app/nuclei.py` marks the nucleus inside each detected cell box with a colour-based method (NumPy + Pillow):
the cell body is separated from the slide background, then the nucleus is the darkest compact region inside it. When
the body cannot be separated, only the nucleus is searched for and no N:C ratio is given. N:C is nucleus area divided by
cytoplasm area (cell area minus nucleus area).

`validate_nuclei.py` checks it against the APCData nucleus **centre points** (3,579 points, same images). Parameters were
tuned on the first 60 training images only; the numbers below are from the held-out test split (61 images, 476 labelled
nuclei):

| Boxes used | Cells with a nucleus marked | Marked nucleus contains the expert point | Median centre error |
|---|---|---|---|
| Expert cell boxes (isolates the nucleus step) | 86% | 74% of all cells (86% of marked) | 17 px |
| Detector boxes at score 0.5 (full pipeline) | 91% of covered cells | 70% of covered cells (77% of marked) | 26 px |

The detector at score 0.5 covers only 279 of the 476 labelled cells, so the second row describes the cells it found.

Limits to state with any use of these results:

- There are no nucleus **outlines** in APCData, so nucleus area and the N:C ratio are not validated, only the location.
- On a drawn test cell with a known ratio the method recovered it within 50%, and the synthetic field gave plausible values.
  Real fields are harder: in crowded or overlapping clusters it can mark the wrong structure (a cytoplasm fold was marked
  as a large nucleus, N:C 0.34, in one inspected test image) and the detector itself finds few cells in such clusters.
- 5 to 10% of marks sit on a neighbouring nucleus or other dark structure (90th-percentile error is about 100 px).
- Human cervical data only. No veterinary validation. Measurements are for human review, never diagnoses.
