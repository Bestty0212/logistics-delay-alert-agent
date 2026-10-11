#!/usr/bin/env python3
"""Compute gold answers for eval/questions.jsonl with the owner role; write eval/gold.json."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.db import connect_owner  # noqa: E402
from etl.env import apply_env_file  # noqa: E402
from etl.replay import ReplayNotStartedError, require_clock_date  # noqa: E402
from eval.gold import (  # noqa: E402
    GOLD_PATH,
    GoldError,
    build_gold,
    load_questions,
    read_clock_date,
)


def main() -> int:
    apply_env_file(ROOT / ".env", os.environ)
    try:
        questions = load_questions()
        with connect_owner() as conn:
            conn.read_only = True
            clock = require_clock_date(read_clock_date(conn))
            gold = build_gold(conn, questions, clock)
    except (GoldError, ReplayNotStartedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    GOLD_PATH.write_text(json.dumps(gold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {GOLD_PATH.relative_to(ROOT)}: {len(gold['entries'])} entries, "
          f"clock {gold['clock_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
