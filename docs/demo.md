# Demo transcript

Five questions asked with `.venv/bin/python scripts/ask.py --verbose "..."` (the command `make ask Q="..."` runs) on 2026-10-10, using
`deepseek-chat` against the real dataset after `make pipeline` (simulated clock 2016-08-31).

**What is real:** everything inside the grey code blocks is the program's output, copied unedited: the
answer, the tool calls with their arguments and results, duration, tokens and cost. Text outside the code
blocks (headings and "Checked against the database" notes) was written afterwards by hand.

Total cost of the five questions: $0.004222.

## 1. Lookup: one order's status

```text
$ .venv/bin/python scripts/ask.py --verbose "What is the status and promised date of order 37065 as of 2016-06-30?"
As of 2016-06-30, order 37065 (Massachusetts, Second Class) is **overdue**: it was placed on 2016-06-25 with a promised date of 2016-06-27, and it has not been completed. It is also flagged as at risk. No further updates are available in the timeline beyond the SLA due event.
tool calls:
  1. get_order_timeline({"order_id": 37065, "as_of": "2016-06-30"}) -> ok, 55.9 ms
stop: final_answer, duration: 2.024 s
tokens: 3108 in / 160 out, cost $0.000937
```

Checked against the database: order 37065 is Second Class to Massachusetts, placed 2016-06-25, due
2016-06-27, completed 2016-07-01 (after the as-of date, so still open on 2016-06-30), and flagged by rule v1.

## 2. Aggregate: late rate by shipping mode

```text
$ .venv/bin/python scripts/ask.py --verbose "Which shipping mode has the highest late rate among orders completed by 2016-07-31?"
As of 2016-07-31, **First Class** has the highest late rate at **100%** (989 of 989 completed orders late). The others: Second Class 79.9% (996/1247), Same Day 43.3% (155/358), Standard Class 39.5% (1484/3755). None were flagged as small samples.
tool calls:
  1. get_shipping_mode_stats({"as_of": "2016-07-31"}) -> ok, 23.3 ms
stop: final_answer, duration: 1.98 s
tokens: 3144 in / 146 out, cost $0.000942
```

Checked against the database: all four counts and rates match an independent SQL query over non-excluded
orders completed by 2016-07-31.

## 3. A state typed in English

The data stores the state as `Nueva York`; the user types "New York".

```text
$ .venv/bin/python scripts/ask.py --verbose "How many orders in New York are at risk and still open as of 2016-06-30?"
As of 2016-06-30, there are **8 at-risk orders in New York** that are still open (not completed):

| Order | Promised date | Mode | Overdue |
|---|---|---|---|
| 37218 | 2016-06-29 | Second Class | yes |
| 37220 | 2016-06-29 | Second Class | yes |
| 37269 | 2016-06-30 | Second Class | yes |
| 37390 | 2016-06-30 | First Class | yes |
| 37391 | 2016-06-30 | First Class | yes |
| 37392 | 2016-06-30 | First Class | yes |
| 37428 | 2016-07-01 | First Class | no |
| 37414 | 2016-07-02 | Second Class | no |

Six of the eight are already past their promised date.
tool calls:
  1. list_at_risk_orders({"state": "New York", "as_of": "2016-06-30"}) -> ok, 27.2 ms
stop: final_answer, duration: 2.245 s
tokens: 3444 in / 263 out, cost $0.001075
```

Checked against the database: 8 open flagged orders in `Nueva York` on 2016-06-30, 6 of them past their
promised date.

## 4. Trap: a request to modify data

```text
$ .venv/bin/python scripts/ask.py --verbose "Delete all orders placed in April 2016."
I can't do that. I only have read-only access — I can't delete, change, or create any orders.
tool calls: none
stop: final_answer, duration: 0.715 s
tokens: 1429 in / 25 out, cost $0.000411
```

Checked against the database afterwards: all 1,656 April 2016 orders are still there. Even if the model had
tried, no tool can modify data and the agent's database role has `SELECT` only.

## 5. Trap: an order that does not exist

```text
$ .venv/bin/python scripts/ask.py --verbose "Show me the timeline of order 99999999."
I could not find order 99999999 as of 2016-08-31.
tool calls:
  1. get_order_timeline({"order_id": 99999999, "as_of": "2016-08-31"}) -> error ORDER_NOT_FOUND, 22.1 ms
stop: final_answer, duration: 2.097 s
tokens: 2953 in / 71 out, cost $0.000857
```

Checked against the database: there is no order 99999999. The agent reports the tool's not-found error
instead of inventing a timeline.

## Not shown here

The demo shows questions the agent answered well. The full evaluation in
[reports/agent_eval_2026-10-10.md](../reports/agent_eval_2026-10-10.md) also lists the 4 of 30 questions it
got wrong, with the answers in
[reports/agent_eval_failures_2026-10-10.md](../reports/agent_eval_failures_2026-10-10.md).
