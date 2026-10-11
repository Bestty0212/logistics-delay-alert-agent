"""Load questions, compute gold answers with independent SQL, and check gold is current."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from eval.gold_sql import QUERIES

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "questions.jsonl"
GOLD_PATH = EVAL_DIR / "gold.json"

CATEGORIES = ("lookup", "aggregate", "reasoning", "trap")
REQUIRED_KEYS = ("id", "category", "question", "as_of", "gold", "checks", "dry_run")


class GoldError(Exception):
    """Questions or gold answers are missing, malformed or out of date."""


def validate_question(question: dict) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in question]
    if missing:
        raise GoldError(f"question {question.get('id')}: missing keys {missing}")
    if question["category"] not in CATEGORIES:
        raise GoldError(f"question {question['id']}: unknown category {question['category']}")
    date.fromisoformat(question["as_of"])
    query = question["gold"].get("query")
    if query is not None and query not in QUERIES:
        raise GoldError(f"question {question['id']}: unknown gold query {query}")


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    for question in questions:
        validate_question(question)
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise GoldError("duplicate question ids")
    return questions


def to_jsonable(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def gold_params(question: dict) -> dict:
    """Query parameters; as_of comes from the question when the query uses it."""
    params = dict(question["gold"].get("params", {}))
    if "%(as_of)s" in QUERIES[question["gold"]["query"]]:
        params["as_of"] = date.fromisoformat(question["as_of"])
    return params


def run_gold_query(conn: psycopg.Connection, sql: str, params: dict) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def read_clock_date(conn: psycopg.Connection) -> date | None:
    rows = run_gold_query(conn, QUERIES["clock_date"], {})
    return rows[0]["clock_date"] if rows else None


def compute_gold_entry(conn: psycopg.Connection, question: dict) -> dict:
    entry = {"question": question["question"], "as_of": question["as_of"]}
    query = question["gold"].get("query")
    if query is None:
        return {**entry, "query": None, "sql": None, "params": {}, "values": {},
                "note": question["gold"].get("note", "no database answer needed")}
    params = gold_params(question)
    rows = run_gold_query(conn, QUERIES[query], params)
    if len(rows) > 1:
        raise GoldError(f"gold query {query} returned {len(rows)} rows for {question['id']}")
    values = {k: to_jsonable(v) for k, v in rows[0].items()} if rows else {}
    return {
        **entry,
        "query": query,
        "sql": " ".join(QUERIES[query].split()),
        "params": {k: to_jsonable(v) for k, v in params.items()},
        "values": values,
        "row_count": len(rows),
    }


def build_gold(conn: psycopg.Connection, questions: list[dict], clock_date: date | None) -> dict:
    return {
        "computed_with": "owner role, independent SQL in eval/gold_sql.py",
        "clock_date": clock_date.isoformat() if clock_date else None,
        "entries": {q["id"]: compute_gold_entry(conn, q) for q in questions},
    }


def load_gold(path: Path = GOLD_PATH) -> dict:
    if not path.is_file():
        raise GoldError(f"{path.name} not found; run scripts/build_gold.py")
    return json.loads(path.read_text(encoding="utf-8"))


def gold_problems(questions: list[dict], gold: dict, clock_date: date | None) -> list[str]:
    """Reasons the gold file cannot be used for these questions (empty if it can)."""
    problems = []
    expected_clock = clock_date.isoformat() if clock_date else None
    if gold.get("clock_date") != expected_clock:
        problems.append(
            f"gold was built at clock {gold.get('clock_date')}, clock is now {expected_clock}"
        )
    entries = gold.get("entries", {})
    for question in questions:
        entry = entries.get(question["id"])
        if entry is None:
            problems.append(f"{question['id']}: no gold entry")
        elif entry.get("question") != question["question"] or entry.get("as_of") != question["as_of"]:
            problems.append(f"{question['id']}: question or as_of changed since gold was built")
    return problems
