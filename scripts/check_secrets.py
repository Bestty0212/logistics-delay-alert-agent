#!/usr/bin/env python3
"""Fail if repository files, logs/, reports/ or git history contain key-like strings or .env secrets.

Scanned: files tracked by git, untracked files git does not ignore, and everything under
logs/ and reports/. With --git-history, every commit's diff (`git log -p --all`) as well.
Findings print the file, line and pattern name, never the matched value.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.env import load_env_file  # noqa: E402

SECRET_NAME_WORDS = ("KEY", "PASSWORD", "SECRET", "TOKEN")
MIN_SECRET_LENGTH = 6
MAX_FILE_BYTES = 5_000_000
SCANNED_DIRS = ("logs", "reports")

KEY_PATTERNS = {
    "anthropic-key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai-style-key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "private-key-block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

# Fake keys used by the offline tests; anything else that looks like a key fails.
ALLOWED_PREFIXES = ("sk-ant-test-",)


@dataclass(frozen=True)
class Finding:
    location: str
    line: int
    pattern: str

    def __str__(self) -> str:
        return f"{self.location}:{self.line}: {self.pattern}"


def secret_env_values(env: dict[str, str], public: dict[str, str]) -> dict[str, str]:
    """name -> value for secret-looking variables; values also in .env.example are public."""
    public_values = set(public.values())
    return {
        name: value
        for name, value in env.items()
        if any(word in name.upper() for word in SECRET_NAME_WORDS)
        and len(value) >= MIN_SECRET_LENGTH
        and value not in public_values
    }


def scan_line(line: str, secrets: dict[str, str]) -> list[str]:
    """Names of the patterns found in one line."""
    found = [
        name
        for name, pattern in KEY_PATTERNS.items()
        if any(not m.group(0).startswith(ALLOWED_PREFIXES) for m in pattern.finditer(line))
    ]
    found += [f"value of {name} from .env" for name, value in secrets.items() if value in line]
    return found


def scan_text(location: str, text: str, secrets: dict[str, str]) -> list[Finding]:
    return [
        Finding(location, number, pattern)
        for number, line in enumerate(text.splitlines(), 1)
        for pattern in scan_line(line, secrets)
    ]


def read_text(path: Path) -> str | None:
    """File text, or None for binary or very large files."""
    if path.stat().st_size > MAX_FILE_BYTES:
        return None
    data = path.read_bytes()
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")


def git_lines(args: list[str], root: Path) -> list[str]:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


def files_to_scan(root: Path) -> list[Path]:
    names = set(git_lines(["ls-files"], root))
    names |= set(git_lines(["ls-files", "--others", "--exclude-standard"], root))
    paths = {root / name for name in names}
    for directory in SCANNED_DIRS:
        base = root / directory
        if base.is_dir():
            paths |= {p for p in base.rglob("*") if p.is_file()}
    return sorted(p for p in paths if p.is_file() and p.name != ".env")


def scan_files(paths: Iterable[Path], root: Path, secrets: dict[str, str]) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    scanned = 0
    for path in paths:
        text = read_text(path)
        if text is None:
            continue
        scanned += 1
        findings += scan_text(str(path.relative_to(root)), text, secrets)
    return findings, scanned


def scan_git_history(root: Path, secrets: dict[str, str]) -> list[Finding]:
    result = subprocess.run(["git", "log", "-p", "--all", "--no-color"], cwd=root,
                            capture_output=True, text=True, errors="replace", check=True)
    return scan_text("git history", result.stdout, secrets)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-history", action="store_true", help="also scan every commit diff")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    args = parse_args(argv)
    secrets = secret_env_values(load_env_file(root / ".env"), load_env_file(root / ".env.example"))
    findings, scanned = scan_files(files_to_scan(root), root, secrets)
    if args.git_history:
        findings += scan_git_history(root, secrets)
    for finding in findings:
        print(finding)
    if findings:
        print(f"secret scan FAILED: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    history = " and git history" if args.git_history else ""
    print(f"secret scan passed: {scanned} files{history}, {len(secrets)} .env secret value(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
