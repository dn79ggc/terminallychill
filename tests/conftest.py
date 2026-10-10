import os
from pathlib import Path

import psycopg
import pytest

SQL_001 = (Path(__file__).resolve().parents[1] / "sql" / "001_schema.sql").read_text(encoding="utf-8")


@pytest.fixture
def db_url(monkeypatch):
    """Needs a throwaway Postgres: set TEST_DATABASE_URL. Skipped otherwise. The flights table is wiped."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS flights")
        conn.execute(SQL_001)
    monkeypatch.setenv("DATABASE_URL", url)
    return url
