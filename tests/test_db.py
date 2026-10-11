"""Unit tests for database connection helpers."""

from __future__ import annotations

from etl.db import agent_ro_connect_kwargs, owner_connect_kwargs


def test_owner_connect_kwargs() -> None:
    env = {
        "POSTGRES_HOST": "dbhost",
        "POSTGRES_PORT": "6543",
        "POSTGRES_DB": "mydb",
        "POSTGRES_USER": "owner",
        "POSTGRES_PASSWORD": "secret",
    }
    assert owner_connect_kwargs(env) == {
        "host": "dbhost",
        "port": 6543,
        "dbname": "mydb",
        "user": "owner",
        "password": "secret",
    }


def test_agent_ro_connect_kwargs_defaults_user() -> None:
    env = {
        "POSTGRES_DB": "mydb",
        "AGENT_RO_PASSWORD": "ro-secret",
    }
    kwargs = agent_ro_connect_kwargs(env)
    assert kwargs["user"] == "agent_ro"
    assert kwargs["password"] == "ro-secret"
    assert kwargs["host"] == "localhost"
    assert kwargs["port"] == 5432
