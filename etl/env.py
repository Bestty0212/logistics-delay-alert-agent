"""Minimal .env loader (no third-party dotenv dependency)."""

from __future__ import annotations

from pathlib import Path


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from a .env file into a dict (does not modify os.environ)."""
    env_path = Path(path)
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        values[key] = value
    return values


def apply_env_file(path: str | Path, environ: dict[str, str]) -> None:
    """Set keys from .env into environ only when the key is not already set."""
    for key, value in load_env_file(path).items():
        environ.setdefault(key, value)
