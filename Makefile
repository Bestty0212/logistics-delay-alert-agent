PYTHON ?= python3.13
PY := .venv/bin/python
CLOCK_DATE := 2016-08-31
MAX_COST ?= 0.25
Q ?=

.PHONY: help setup up down import replay evaluate-risk summary pipeline test ask docker-ask \
	gold eval logs-summary fixture check-secrets

help:
	@echo "setup          create .venv and install requirements"
	@echo "up / down      start / stop PostgreSQL in Docker"
	@echo "import         load data/DataCoSupplyChainDataset.csv"
	@echo "replay         replay events up to $(CLOCK_DATE)"
	@echo "evaluate-risk  compute risk flags, write reports/risk_eval_v1.md"
	@echo "summary        write reports/data_summary.md"
	@echo "pipeline       import + replay + evaluate-risk + summary"
	@echo "test           run the offline tests (no API key needed)"
	@echo "ask Q=\"...\"    ask the agent one question (needs an API key in .env)"
	@echo "docker-ask     same as ask, inside the app container"
	@echo "gold           rebuild eval/gold.json from the database"
	@echo "eval           live agent evaluation, capped at MAX_COST=$(MAX_COST) USD"
	@echo "logs-summary   summarize logs/agent_calls.jsonl"
	@echo "fixture        regenerate the synthetic CI fixture"
	@echo "check-secrets  scan files, logs, reports and git history for secrets"

setup:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

up:
	docker compose up -d --wait db

down:
	docker compose down

import:
	$(PY) scripts/import_data.py

replay:
	$(PY) scripts/replay_events.py --reset --to $(CLOCK_DATE)

evaluate-risk:
	$(PY) scripts/evaluate_risk.py --expect-orders 7887

summary:
	$(PY) scripts/data_summary.py

pipeline: import replay evaluate-risk summary

test:
	$(PY) -m pytest -q -rs

ask:
	$(PY) scripts/ask.py --verbose $(if $(Q),"$(Q)")

docker-ask:
	docker compose run --rm app python scripts/ask.py --verbose $(if $(Q),"$(Q)")

gold:
	$(PY) scripts/build_gold.py

eval:
	$(PY) scripts/run_eval.py --max-cost-usd $(MAX_COST)

logs-summary:
	$(PY) scripts/summarize_logs.py

fixture:
	$(PY) scripts/make_fixture.py

check-secrets:
	$(PY) scripts/check_secrets.py --git-history
