"""Tests for scripts/check_secrets.py. Fake keys are built at runtime so this file stays clean."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_secrets import (
    Finding,
    files_to_scan,
    git_lines,
    main,
    parse_args,
    read_text,
    scan_files,
    scan_git_history,
    scan_line,
    scan_text,
    secret_env_values,
)

FAKE_OPENAI = "sk-" + "A1b2C3d4" * 4
FAKE_ANTHROPIC = "sk-ant-" + "api03-" + "x" * 30


def test_secret_env_values_filters_names_length_and_public_values() -> None:
    env = {
        "POSTGRES_PASSWORD": "real_password",
        "AGENT_RO_PASSWORD": "change_me",
        "DEEPSEEK_API_KEY": "abc",
        "POSTGRES_USER": "logistics_user",
    }
    public = {"AGENT_RO_PASSWORD": "change_me"}
    assert secret_env_values(env, public) == {"POSTGRES_PASSWORD": "real_password"}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (f"key={FAKE_OPENAI}", ["openai-style-key"]),
        (f"key={FAKE_ANTHROPIC}", ["anthropic-key"]),
        ("AKIA" + "ABCDEFGHIJKLMNOP", ["aws-access-key"]),
        ("ghp_" + "a" * 36, ["github-token"]),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", ["private-key-block"]),
        ("api_key = 'sk-ant-test-" + "x" * 30 + "'", []),
        ("nothing to see here", []),
    ],
)
def test_scan_line_patterns(line: str, expected: list[str]) -> None:
    assert scan_line(line, {}) == expected


def test_scan_line_reports_env_value_by_name_only() -> None:
    assert scan_line("password is hunter22!", {"DB_PASSWORD": "hunter22!"}) == [
        "value of DB_PASSWORD from .env"
    ]


def test_scan_text_numbers_lines() -> None:
    findings = scan_text("f.txt", f"ok\nkey {FAKE_OPENAI}\n", {})
    assert findings == [Finding("f.txt", 2, "openai-style-key")]
    assert str(findings[0]) == "f.txt:2: openai-style-key"


def test_read_text_skips_binary(tmp_path: Path) -> None:
    text_file, binary_file = tmp_path / "a.txt", tmp_path / "b.bin"
    text_file.write_text("hello", encoding="utf-8")
    binary_file.write_bytes(b"ab\x00cd")
    assert read_text(text_file) == "hello"
    assert read_text(binary_file) is None


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / ".gitignore").write_text(".env\nlogs/\nignored.txt\n", encoding="utf-8")
    (tmp_path / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_git_lines(repo: Path) -> None:
    assert set(git_lines(["ls-files"], repo)) == {".gitignore", "tracked.py"}


def test_files_to_scan_includes_untracked_and_logs_but_not_env(repo: Path) -> None:
    (repo / "new.py").write_text("", encoding="utf-8")
    (repo / "ignored.txt").write_text("", encoding="utf-8")
    (repo / ".env").write_text("", encoding="utf-8")
    (repo / "logs").mkdir()
    (repo / "logs" / "agent_calls.jsonl").write_text("", encoding="utf-8")
    names = {p.relative_to(repo).as_posix() for p in files_to_scan(repo)}
    assert names == {".gitignore", "tracked.py", "new.py", "logs/agent_calls.jsonl"}


def test_scan_files_counts_and_finds(repo: Path) -> None:
    (repo / "leak.md").write_text(f"token {FAKE_OPENAI}\n", encoding="utf-8")
    findings, scanned = scan_files(files_to_scan(repo), repo, {})
    assert scanned == 3
    assert findings == [Finding("leak.md", 1, "openai-style-key")]


def test_scan_git_history_finds_removed_secret(repo: Path) -> None:
    (repo / "config.py").write_text(f"KEY = '{FAKE_OPENAI}'\n", encoding="utf-8")
    _git(repo, "add", "config.py")
    _git(repo, "commit", "-q", "-m", "oops")
    _git(repo, "rm", "-q", "config.py")
    _git(repo, "commit", "-q", "-m", "remove")
    patterns = [f.pattern for f in scan_git_history(repo, {})]
    assert patterns == ["openai-style-key"] * 2  # the adding and the removing diff


def test_parse_args() -> None:
    assert parse_args([]).git_history is False
    assert parse_args(["--git-history"]).git_history is True


def test_main_passes_clean_repo(repo: Path, capsys) -> None:
    assert main(["--git-history"], root=repo) == 0
    assert "secret scan passed" in capsys.readouterr().out


def test_main_fails_on_env_value_in_report(repo: Path, capsys) -> None:
    (repo / ".env").write_text("DEEPSEEK_API_KEY=very-private-value\n", encoding="utf-8")
    (repo / ".env.example").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    (repo / "logs").mkdir()
    (repo / "logs" / "run.log").write_text("used very-private-value\n", encoding="utf-8")
    assert main([], root=repo) == 1
    out = capsys.readouterr().out
    assert "logs/run.log:1: value of DEEPSEEK_API_KEY from .env" in out
    assert "very-private-value" not in out
