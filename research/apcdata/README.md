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
