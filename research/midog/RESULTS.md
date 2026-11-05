# Expanded MIDOG++ experiment results

Both configurations used the same six training, two validation and three held-out source cases.

At the fixed diagnostic score threshold of 0.5, both models missed all 138 test mitoses.
The revised configuration improved ranked detection AP and localization, while detection quality remains limited.

| Configuration | Selected epoch | Test AP50 | Test AP50–95 | Matches at score 0.5 | Unmatched predictions | Missed targets |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 2 | 0.000398 | 0.000089 | 0 | 0 | 138 |
| small-cells | 3 | 0.094443 | 0.040252 | 0 | 0 | 138 |

AP values are reported on a 0–1 scale. Diagnostic matches use IoU 0.5.

| Configuration | Median predicted box width | Median source width | Targets with a candidate at IoU 0.5 |
| --- | --- | --- | --- |
| baseline | 50.6 px | 50.0 px | 20 |
| small-cells | 48.6 px | 50.0 px | 79 |

Box-size diagnostics use all returned detections after core filtering, across all scores.
Candidate overlap measures localization opportunities before the diagnostic score threshold.

The maximum test scores were baseline 0.113643, small-cells 0.483170.
Threshold calibration requires development data and further evaluation on a newly reserved cohort.

The earlier three-case pilot recorded AP50 and AP50–95 of 0.00 on different cases and a different tile protocol.
The two rows above provide the direct paired comparison.

Resolution, anchor sizes and learning rate change together. The results compare configuration bundles.
The cohort is small and grouping uses source case identifiers. Patient independence remains unverified.

See EXPERIMENT.md for source selection, preparation, model selection and Windows commands.
The aggregate JSON preserves source hashes, configurations, epoch histories and measured results.
