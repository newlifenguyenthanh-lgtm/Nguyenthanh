"""PostgreSQL integration support. Enabled when PAACC_TEST_PG_URL is set, e.g.
PAACC_TEST_PG_URL=postgresql+psycopg://paacc_test:paacc_test@localhost:5432/paacc_test"""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

PG_URL = os.environ.get("PAACC_TEST_PG_URL", "")
requires_pg = pytest.mark.skipif(not PG_URL, reason="PAACC_TEST_PG_URL not set (PostgreSQL integration tests)")
BACKEND = Path(__file__).resolve().parents[1]


def alembic_cfg() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def fresh_pg_engine(monkeypatch):
    """Drop everything, run ALL Alembic migrations from scratch, return an engine."""
    engine = create_engine(PG_URL)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setenv("PAACC_DATABASE_URL", PG_URL)
    command.upgrade(alembic_cfg(), "head")
    return engine
