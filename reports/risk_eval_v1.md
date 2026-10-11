# Risk rule v1 evaluation (order level)

Rule v1: flag an order as high risk when its shipping mode's training late rate is above 0.50. Ground truth: `late_label`, non-excluded orders only.

## Data split (non-excluded orders)

- Training period 2016-04-01 to 2016-06-30: 4875 orders
- Test period 2016-07-01 to 2016-08-25: 3012 orders
- Total: 7887

## Training late rate per shipping mode

| Shipping mode | Training orders | Late rate | Flagged |
|---|---|---|---|
| First Class | 744 | 100.0% | yes |
| Same Day | 261 | 46.0% | no |
| Second Class | 1003 | 80.5% | yes |
| Standard Class | 2867 | 40.6% | no |

Flagged modes: First Class, Second Class.

Same Day's training late rate (46.0%) is close to the 50% threshold, and the result changes at a 0.45 threshold; this is shown, not tuned.

## In-sample: training period (April–June)

These numbers use the same orders the rates were computed from, so they are in-sample and optimistic. They are NOT an evaluation. Only the July–August test period below is a real evaluation.

| Predictor | TP | FP | FN | TN | Precision (95% CI) | Recall (95% CI) | Accuracy |
|---|---|---|---|---|---|---|---|
| rule_v1 | 1551 | 196 | 1284 | 1844 | 88.8% [87.2%, 90.2%] | 54.7% [52.9%, 56.5%] | 69.6% |
| always_late | 2835 | 2040 | 0 | 0 | 58.2% [56.8%, 59.5%] | 100.0% [99.9%, 100.0%] | 58.2% |
| never_late | 0 | 0 | 2835 | 2040 | n/a | 0.0% [0.0%, 0.1%] | 41.8% |

## Test period evaluation (July–August) — the real evaluation

| Predictor | TP | FP | FN | TN | Precision (95% CI) | Recall (95% CI) | Accuracy |
|---|---|---|---|---|---|---|---|
| rule_v1 | 918 | 117 | 798 | 1179 | 88.7% [86.6%, 90.5%] | 53.5% [51.1%, 55.8%] | 69.6% |
| always_late | 1716 | 1296 | 0 | 0 | 57.0% [55.2%, 58.7%] | 100.0% [99.8%, 100.0%] | 57.0% |
| never_late | 0 | 0 | 1716 | 1296 | n/a | 0.0% [0.0%, 0.2%] | 43.0% |

## Test period by shipping mode

| Shipping mode | Orders | Late rate | Flagged | Late orders missed |
|---|---|---|---|---|
| First Class | 475 | 100.0% | yes | 0 |
| Same Day | 175 | 46.3% | no | 81 |
| Second Class | 560 | 79.1% | yes | 0 |
| Standard Class | 1802 | 39.8% | no | 717 |

## Threshold sensitivity (report only; the rule stays at 0.50)

| Threshold | Flagged modes | Precision | Recall | Accuracy |
|---|---|---|---|---|
| 0.45 | First Class, Same Day, Second Class | 82.6% | 58.2% | 69.2% |
| 0.50 | First Class, Second Class | 88.7% | 53.5% | 69.6% |
| 0.55 | First Class, Second Class | 88.7% | 53.5% | 69.6% |

## Flags written

- `risk_flags` rows with rule_version = 'v1': 2903 (of which 121 belong to excluded orders; they are flagged because exclusion is unknown at order time, but never evaluated).
- Flags are written for all dates at once with flag_date = order_date. Any "as of now" reader must filter flag_date <= the simulated clock date.

## Limitations

This is one dataset covering about five months of 2016 US orders. The rule mirrors the dataset's scheduling pattern (for example, First Class always takes 2 days against a 1-day promise), so it reflects how the data was generated rather than real carrier behavior, and the results should not be read as real-world delivery performance. The test period is short and August is partial.
