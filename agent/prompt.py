"""Load the system prompt and fill in the simulated as-of date."""

from __future__ import annotations

from datetime import date
from pathlib import Path

PROMPT_PATH = Path(__file__).with_name("system_prompt.md")
AS_OF_PLACEHOLDER = "{as_of}"


def build_system_prompt(as_of: date, path: Path = PROMPT_PATH) -> str:
    template = path.read_text(encoding="utf-8")
    return template.replace(AS_OF_PLACEHOLDER, as_of.isoformat())
