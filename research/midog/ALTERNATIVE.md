# Verified alternative: selected MIDOG++ canine files

On November 4, 2026, the author-linked MIDOG++ Figshare collection was inspected
directly through its public API. This is a distinct release from MIDOG 2022 PNG.
The collection contains 506 records: 503 image records and three associated
annotation/split records. This review verifies only the selected records below.

| File | Figshare article | Published terms |
| --- | --- | --- |
| MIDOG++.json | 23531121 | CC0 |
| 250.tiff | 22690570 | CC0 |
| 251.tiff | 22690606 | CC0 |
| 252.tiff | 22690573 | CC0 |

The JSON's embedded license also specifies CC0, matching its host record. The
selected images are labeled canine lymphosarcoma in the annotation
metadata. File sizes, download URLs, MD5 checksums and license URLs are recorded
in `reports/midogpp-source-review.json`. The downloaded annotation file passed
its published MD5 check. The first image download, training and evaluation run
completed on November 4, 2026. See [PILOT.md](PILOT.md) for measured results.

Sources:
- Authors: https://github.com/DeepMicroscopy/MIDOGpp
- Collection: https://doi.org/10.6084/m9.figshare.c.6615571
- Annotations: https://api.figshare.com/v2/articles/23531121
- Image records: https://api.figshare.com/v2/articles/22690570 ,
  https://api.figshare.com/v2/articles/22690606 ,
  https://api.figshare.com/v2/articles/22690573

## Experiment scope

Proceed with these specifically verified files without depending on a reply to
the older release's clarification email. Retain attribution and cite the paper.
Do not change the unresolved MIDOG 2022 or P-Hem rights records.

MIDOG++ numbering differs from MIDOG 2022: never infer tumor type from the
older release's numeric ranges. Use the newer JSON's `tumor_type` and its
own split metadata when implementing the importer.

Next: checksum-verified download of the three images (389,332,710 bytes total),
visual inspection of converted boxes, deterministic patches, and a one-positive-
class detector engineering pilot. Three cases are insufficient for a credible
final research result. Expand the cohort after verifying each additional image's
record, reserve untouched cases before development, and establish patient linkage
where available. Report limitations explicitly where it is unavailable.

This is histology mitosis detection. Cytology performance and diagnosis are not
established by this experiment. P-Hem remains a separate future experiment.
