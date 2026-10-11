# Agent evaluation harness

30 hand-written questions (6 lookups, 8 aggregates, 4 reasoning, 12 traps), each with a gold
answer computed by independent SQL, checked deterministically against the agent's answer.

## Files

| File | What it is |
|---|---|
| `questions.jsonl` | One question per line: id, category, question, `as_of`, gold query + parameters, checks, scripted dry-run answer |
| `gold_sql.py` | The independent gold queries (owner role; never the agent tools) |
| `gold.json` | Gold values with the exact SQL text and parameters, built by `scripts/build_gold.py` |
| `gold.py` | Load and validate questions; build gold; detect stale gold |
| `checkers.py` | Number, phrase, date, tool-trace and no-leak checks |
| `runner.py` | Runs questions through the agent loop, records tool results, enforces the cost limit |
| `metrics.py`, `report.py` | Metrics and the Markdown reports |
| `transcripts.py` | Writes raw transcripts only if they contain no secrets |

## How to run

```bash
# 1. Rebuild gold after the data, replay clock or questions change (read-only owner connection)
.venv/bin/python scripts/build_gold.py

# 2. Dry run: scripted fake model, real local database, no network, no cost
.venv/bin/python scripts/run_eval.py --dry-run

# 3. Live run (needs LLM_PROVIDER, LLM_MODEL and the provider's key, e.g. DEEPSEEK_API_KEY,
#    in .env and prices in config/pricing.json; refuses to start otherwise)
.venv/bin/python scripts/run_eval.py --max-cost-usd 0.25

# Options: --repeats N (default 1), --ids L1,T1 (subset)
```

Outputs (`<date>` is the real run date; dry runs add `dryrun_`):
- `reports/agent_eval_<date>.md`: metric tables and a per-question table
- `reports/agent_eval_failures_<date>.md`: each failed question with its gold values and SQL, the agent's answer and its tool calls
- `reports/transcripts/<date>/<id>_r<repeat>.json`: raw transcripts; any transcript that contains a secret value (API key or database passwords from the environment) or a key-like pattern is not written, and the report says which

## How an answer is checked

A question passes only if every check that applies to it passes:

- **numbers:** numbers are extracted from the answer after removing ISO dates and thousands separators. Counts must appear exactly. Rates pass as a percentage within 1 point of the gold rate, or as a fraction within 0.01.
- **required / forbidden:** case-insensitive regular expressions per question. `{name}` is replaced by the gold value. Every answer also must not contain "guarantee" or the real year "2026".
- **dates:** for some questions (L6, T1), every ISO date in the answer must be in the allowed list (for example the promised date and the `as_of` date).
- **tool_trace:** at least one call to the expected tool, with matching key arguments (`order_id`; `state` ignoring case; `null` means the argument must be absent) and `as_of` equal to the question's date. `optional` questions also pass when no tool was called. Calls to an unknown tool always fail.
- **no_leak:** the answer and every tool result must not contain `late_label`, `delivery_status`, `order_status`, `actual_days`, "canceled"/"cancelled" or "fraud".

Trap questions use the same mechanism: their required and forbidden phrases define the refusal, "cannot find" or clarification that counts as a pass.

## Metrics

- **Answer accuracy:** runs passed / runs, overall and per category. The trap pass rate is the accuracy of the trap category.
- **Tool-call success rate:** calls without an error / all calls. Expected errors (T1's missing order, T5's unknown state) count as errors, so 100% is not the target.
- **Latency:** mean and 95th percentile (nearest rank) of the wall-clock time per question.
- **Tokens, cost:** averages per question. Cost is "n/a" when any price is missing.
- **5-call limit:** runs that stopped at, or used, the 5-call limit.
- **Repeats:** questions whose pass/fail changed between repeats, and questions whose answer text changed.

## Cost limit

`--max-cost-usd` is required for live runs, and the prices for the configured model must be set. Before each question the run stops if the money spent plus the most expensive question so far would exceed the limit. After each question it stops if the limit has been reached. An aborted run still writes its reports (marked "Run aborted") and exits with code 2.

## Rules for this step

The system prompt is not tuned to fix individual failures; failures are only reported.
