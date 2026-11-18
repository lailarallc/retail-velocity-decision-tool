"""The prod guard sits in front of every write path to Postgres.

app/seed_benchmarks.py (DELETE/INSERT/UPDATE) targets a local port that is a
`fly proxy` tunnel to production when one is open. This test fakes a flyctl
listener and asserts nothing connects. (The legacy reload_postgres.py and its
test were deleted 2026-11-17; see DECISIONS.md.)
"""

import importlib.util
import pathlib

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


def test_seed_benchmarks_refuses_fly_tunnel(fly_tunnel, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u@localhost:5432/cinderhaven")
    mod = _load(ROOT / "app" / "seed_benchmarks.py", "seed_benchmarks_under_test")
    with pytest.raises(prod_guard.ProdDatabaseError):
        mod.main()
