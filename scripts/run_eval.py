#!/usr/bin/env python3
"""Run the 30-question agent evaluation and write the reports."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.call_log import append_log, build_log_entry  # noqa: E402
from agent.clock import read_clock  # noqa: E402
from agent.config import AgentConfig, ConfigError, load_config  # noqa: E402
from agent.cost import MISSING_PRICES_NOTE, estimate_cost, load_pricing, model_prices  # noqa: E402
from agent.factory import build_provider  # noqa: E402
from etl.env import apply_env_file  # noqa: E402
from eval.gold import GoldError, gold_problems, load_gold, load_questions  # noqa: E402
from eval.metrics import summarize  # noqa: E402
from eval.report import build_failures_report, build_summary_report  # noqa: E402
from eval.runner import DRY_RUN_MODEL, EvalRun, dry_run_provider, run_eval  # noqa: E402
from eval.transcripts import secret_values, write_transcript  # noqa: E402

REPORTS_DIR = ROOT / "reports"
DRY_RUN_PRICING = {"models": {DRY_RUN_MODEL: {"input_per_million": 0, "output_per_million": 0}}}


class SetupError(Exception):
    """The run cannot start safely."""


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="scripted fake model; no network, real local database")
    parser.add_argument("--max-cost-usd", type=positive_float,
                        help="abort when spend reaches this; required for live runs")
    parser.add_argument("--repeats", type=positive_int, default=1)
    parser.add_argument("--ids", help="comma-separated question ids to run (default: all)")
    return parser.parse_args(argv)


def select_questions(questions: list[dict], ids: str | None) -> list[dict]:
    if not ids:
        return questions
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    unknown = sorted(set(wanted) - {q["id"] for q in questions})
    if unknown:
        raise SetupError(f"unknown question ids: {', '.join(unknown)}")
    return [q for q in questions if q["id"] in wanted]


def check_dates(questions: list[dict], clock: date | None) -> None:
    if clock is None:
        raise SetupError("replay not started: no simulated clock")
    late = [q["id"] for q in questions if date.fromisoformat(q["as_of"]) > clock]
    if late:
        raise SetupError(f"as_of later than the clock for: {', '.join(late)}")


def live_setup(args: argparse.Namespace, environ) -> tuple[AgentConfig, dict]:
    """Live runs need a cost limit and known prices, so the limit can be enforced."""
    if args.max_cost_usd is None:
        raise SetupError("live runs require --max-cost-usd")
    config = load_config(environ)
    pricing = load_pricing()
    if model_prices(pricing, config.model) is None:
        raise SetupError(f"{MISSING_PRICES_NOTE}; fill in prices for {config.model} "
                         "before a live run")
    return config, pricing


def dry_run_config() -> AgentConfig:
    return AgentConfig("dry-run", DRY_RUN_MODEL, 1024, 30000, 30.0)


def report_paths(run_date: str, dry_run: bool) -> tuple[Path, Path, Path]:
    suffix = f"{'dryrun_' if dry_run else ''}{run_date}"
    return (REPORTS_DIR / f"agent_eval_{suffix}.md",
            REPORTS_DIR / f"agent_eval_failures_{suffix}.md",
            REPORTS_DIR / "transcripts" / suffix)


def write_transcripts(run: EvalRun, directory: Path, secrets: list[str]) -> list[str]:
    notes = []
    for result in run.results:
        path = directory / f"{result['id']}_r{result['repeat']}.json"
        reasons = write_transcript(path, result, secrets)
        if reasons:
            notes.append(f"{path.name}: {'; '.join(reasons)}")
    return notes


def log_live_result(record: dict, outcome, pricing: dict, secrets: list[str]) -> None:
    cost = estimate_cost(pricing, outcome.model, outcome.input_tokens, outcome.output_tokens)
    append_log(build_log_entry(outcome, cost), secrets)
    status = "pass" if record["passed"] else "FAIL"
    print(f"{record['id']} r{record['repeat']}: {status} ({record['duration_s']} s)", flush=True)


def main(argv: list[str] | None = None) -> int:
    apply_env_file(ROOT / ".env", os.environ)
    args = parse_args(argv)
    secrets = secret_values(os.environ)
    try:
        questions = select_questions(load_questions(), args.ids)
        clock = read_clock()
        check_dates(questions, clock)
        gold = load_gold()
        problems = gold_problems(questions, gold, clock)
        if problems:
            raise SetupError("gold is out of date: " + "; ".join(problems))
        if args.dry_run:
            config, pricing = dry_run_config(), DRY_RUN_PRICING
            provider_for = dry_run_provider
            on_result = None
        else:
            config, pricing = live_setup(args, os.environ)
            provider = build_provider(config, os.environ)
            provider_for = lambda _q: provider  # noqa: E731
            on_result = lambda r, o: log_live_result(r, o, pricing, secrets)  # noqa: E731
    except (SetupError, GoldError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    run = run_eval(questions, gold, provider_for=provider_for, config=config, pricing=pricing,
                   max_cost_usd=args.max_cost_usd, repeats=args.repeats, on_result=on_result)

    run_date = datetime.now().date().isoformat()
    summary_path, failures_path, transcript_dir = report_paths(run_date, args.dry_run)
    meta = {
        "run_date": run_date,
        "mode": "dry run (scripted model)" if args.dry_run else "live",
        "model": config.model,
        "repeats": args.repeats,
        "clock_date": clock.isoformat(),
        "max_cost_usd": args.max_cost_usd,
        "aborted": run.aborted,
        "abort_reason": run.abort_reason,
        "transcript_notes": write_transcripts(run, transcript_dir, secrets),
    }
    summary = summarize(run.results)
    REPORTS_DIR.mkdir(exist_ok=True)
    summary_path.write_text(build_summary_report(summary, run.results, meta), encoding="utf-8")
    failures_path.write_text(build_failures_report(run.results, gold, meta), encoding="utf-8")

    accuracy = summary["accuracy"]
    print(f"accuracy {accuracy:.1%}" if accuracy is not None else "no results")
    print(f"spent ${run.spent_usd:.6f}" + (f"; ABORTED: {run.abort_reason}" if run.aborted else ""))
    for path in (summary_path, failures_path, transcript_dir):
        print(f"wrote {path.relative_to(ROOT)}")
    return 2 if run.aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
