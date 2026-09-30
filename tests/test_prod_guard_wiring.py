"""The prod guard sits in front of every write path to Postgres.

reload_postgres.py (DROP/COPY, defaults to localhost:15432) and
app/seed_benchmarks.py (DELETE/INSERT/UPDATE) both target a local port that is
a `fly proxy` tunnel to production when one is open. These tests fake a flyctl
listener and assert nothing connects.
"""

import importlib.util
import pathlib
import sys

import psycopg2
import pytest

import prod_guard

ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture
def fly_tunnel(monkeypatch):
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setattr(prod_guard, "_listener", lambda port: "flyctl")

    def _no_connect(*a, **k):
        raise AssertionError("connect ran past the prod guard")

    monkeypatch.setattr(psycopg2, "connect", _no_connect)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reload_postgres_refuses_fly_tunnel(fly_tunnel, monkeypatch, tmp_path):
    # The module disables itself at import with sys.exit(1); neuter that to load it.
    monkeypatch.setattr(sys, "exit", lambda *a: None)
    mod = _load(ROOT / "reload_postgres.py", "reload_postgres_under_test")
    sqlite_file = tmp_path / "src.db"
    sqlite_file.touch()
    monkeypatch.setattr(mod, "SQLITE_PATH", str(sqlite_file))
    monkeypatch.setattr(mod, "PG_DSN", "postgres://localhost:15432/cinderhaven")
    with pytest.raises(prod_guard.ProdDatabaseError):
        mod.main()


def test_seed_benchmarks_refuses_fly_tunnel(fly_tunnel, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u@localhost:5432/cinderhaven")
    mod = _load(ROOT / "app" / "seed_benchmarks.py", "seed_benchmarks_under_test")
    with pytest.raises(prod_guard.ProdDatabaseError):
        mod.main()
