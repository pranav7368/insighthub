import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("IH_OFFLINE", "1")  # tests never hit the network
os.environ.setdefault("IH_RATELIMIT_ENABLED", "0")  # off by default; the rate-limit test opts in
os.environ.setdefault("IH_DB_POOL", "0")  # each test uses its own monkeypatched DB target
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import db  # noqa: E402


@pytest.fixture()
def con():
    import duckdb

    connection = duckdb.connect(":memory:")
    connection.execute(db.SCHEMA)
    yield connection
    connection.close()


@pytest.fixture()
def workspace(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'Tenant A')")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_b', 'Tenant B')")
    return "ws_a"
