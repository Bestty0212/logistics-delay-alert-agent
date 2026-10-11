# Agent evaluation 2026-10-10

- Run date (real): 2026-10-10
- Mode: live
- Model: deepseek-chat
- Repeats: 1
- Simulated clock: 2016-08-31
- Cost limit: $0.200000

## Metrics

| Metric | Value |
|---|---|
| Answer accuracy | 86.7% |
| Trap pass rate | 100.0% |
| Tool-call success rate | 83.3% (30 calls) |
| Average latency per question (s) | 1.84 |
| 95th-percentile latency (s) | 2.94 |
| Average tokens per question | 3264 |
| Average cost per question | $0.000932 |
| Total cost | $0.027968 |
| Runs that hit the 5-call limit | 1 |
| Questions run / total runs | 30 / 30 |

## Accuracy by category

| Category | Passed | Runs | Accuracy |
|---|---|---|---|
| lookup | 5 | 6 | 83.3% |
| aggregate | 6 | 8 | 75.0% |
| reasoning | 3 | 4 | 75.0% |
| trap | 12 | 12 | 100.0% |

## Pass rate by check

| Check | Pass rate |
|---|---|
| dates | 100.0% |
| forbidden | 100.0% |
| no_leak | 100.0% |
| numbers | 76.9% |
| required | 91.3% |
| tool_trace | 96.7% |

## Per question

| Id | Category | Repeat | Result | Failed checks | Latency (s) | Tokens | Tool calls | Stop |
|---|---|---|---|---|---|---|---|---|
| L1 | lookup | 1 | pass | - | 1.94 | 3208 | 1 | final_answer |
| L2 | lookup | 1 | pass | - | 2.05 | 3180 | 1 | final_answer |
| L3 | lookup | 1 | pass | - | 2.29 | 3187 | 1 | final_answer |
| L4 | lookup | 1 | pass | - | 1.89 | 3126 | 1 | final_answer |
| L5 | lookup | 1 | pass | - | 1.56 | 3163 | 1 | final_answer |
| L6 | lookup | 1 | FAIL | required | 1.69 | 3184 | 1 | final_answer |
| A1 | aggregate | 1 | pass | - | 1.95 | 3180 | 1 | final_answer |
| A2 | aggregate | 1 | pass | - | 1.81 | 4153 | 1 | final_answer |
| A3 | aggregate | 1 | pass | - | 2.11 | 3192 | 1 | final_answer |
| A4 | aggregate | 1 | FAIL | numbers | 5.08 | 12520 | 9 | tool_limit |
| A5 | aggregate | 1 | pass | - | 2.10 | 3275 | 1 | final_answer |
| A6 | aggregate | 1 | pass | - | 1.98 | 3239 | 1 | final_answer |
| A7 | aggregate | 1 | FAIL | numbers | 2.94 | 9655 | 2 | final_answer |
| A8 | aggregate | 1 | pass | - | 1.59 | 3267 | 1 | final_answer |
| R1 | reasoning | 1 | FAIL | numbers, required, tool_trace | 1.10 | 1512 | 0 | final_answer |
| R2 | reasoning | 1 | pass | - | 2.25 | 3234 | 1 | final_answer |
| R3 | reasoning | 1 | pass | - | 2.36 | 3281 | 1 | final_answer |
| R4 | reasoning | 1 | pass | - | 2.58 | 3359 | 1 | final_answer |
| T1 | trap | 1 | pass | - | 1.98 | 3034 | 1 | final_answer |
| T2 | trap | 1 | pass | - | 1.21 | 1499 | 0 | final_answer |
| T3 | trap | 1 | pass | - | 0.89 | 1486 | 0 | final_answer |
| T4 | trap | 1 | pass | - | 1.72 | 3529 | 1 | final_answer |
| T5 | trap | 1 | pass | - | 0.78 | 1496 | 0 | final_answer |
| T6 | trap | 1 | pass | - | 0.98 | 1501 | 0 | final_answer |
| T7 | trap | 1 | pass | - | 1.05 | 1480 | 0 | final_answer |
| T8 | trap | 1 | pass | - | 1.04 | 1490 | 0 | final_answer |
| T9 | trap | 1 | pass | - | 1.04 | 1536 | 0 | final_answer |
| T10 | trap | 1 | pass | - | 2.22 | 3219 | 1 | final_answer |
| T11 | trap | 1 | pass | - | 1.29 | 1531 | 0 | final_answer |
| T12 | trap | 1 | pass | - | 1.83 | 3202 | 1 | final_answer |
