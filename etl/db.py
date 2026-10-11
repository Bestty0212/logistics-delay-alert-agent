"""Database connection helpers for owner and agent_ro roles."""

from __future__ import annotations

import os

import psycopg


def owner_connect_kwargs(environ: dict[str, str] | None = None) -> dict[str, str | int]:
    env = environ if environ is not None else os.environ
    return {
        "host": env.get("POSTGRES_HOST", "localhost"),
        "port": int(env.get("POSTGRES_PORT", "5432")),
        "dbname": env["POSTGRES_DB"],
        "user": env["POSTGRES_USER"],
        "password": env["POSTGRES_PASSWORD"],
    }


def agent_ro_connect_kwargs(environ: dict[str, str] | None = None) -> dict[str, str | int]:
    env = environ if environ is not None else os.environ
    return {
        "host": env.get("POSTGRES_HOST", "localhost"),
        "port": int(env.get("POSTGRES_PORT", "5432")),
        "dbname": env["POSTGRES_DB"],
        "user": env.get("AGENT_RO_USER", "agent_ro"),
        "password": env["AGENT_RO_PASSWORD"],
    }


def connect_owner(environ: dict[str, str] | None = None) -> psycopg.Connection:
    return psycopg.connect(**owner_connect_kwargs(environ))


def connect_agent_ro(environ: dict[str, str] | None = None) -> psycopg.Connection:
    return psycopg.connect(**agent_ro_connect_kwargs(environ))
