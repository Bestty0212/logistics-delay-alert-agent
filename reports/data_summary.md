# Data summary

Counts read from the loaded database by `scripts/data_summary.py` (after `make import`, `make replay` and `make evaluate-risk`).

| Item | Value |
|---|---|
| US order items imported | 24,840 |
| US order items excluded (canceled or suspected fraud) | 1,120 |
| Orders | 8,270 |
| Orders excluded from evaluation | 383 |
| Orders used in evaluation | 7,887 |
| First order date | 2016-04-01 |
| Last order date | 2016-08-25 |
| Destination states | 48 |
| Events: order_placed | 8,270 |
| Events: order_completed | 7,887 |
| Events: sla_due | 7,887 |
| Overdue alerts | 4,551 |
| Risk flags (rule v1) | 2,903 |
| Simulated clock date | 2016-08-31 |
