"""
Shared fixtures for Scopenos tests.

Two types of fixtures live here:

  db          — real CallGraphDB against the CI test database (TEST_DATABASE_URL).
                Truncates all data before each test so tests are fully isolated.
                Never touches DATABASE_URL (production) or BENCHMARK_DATABASE_URL.

  project_id  — stable, unique project ID for the current test, derived from the
                test class and method name. Prevents tests from sharing project
                namespaces even within the same run.

In-memory helpers:

  _node / _graph — build model objects without a DB connection.
"""
from __future__ import annotations

import os
import re

import pytest
import pytest_asyncio

from src.call_graph.models import GraphData
from src.call_graph.storage import CallGraphDB

# ── Test database fixture ─────────────────────────────────────────────────────

_TEST_DSN = os.getenv("TEST_DATABASE_URL", "")


async def _wipe(pool) -> None:
    """Drop all project schemas and truncate every public table."""
    async with pool.acquire() as conn:
        schemas = await conn.fetch(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN "
            "  ('public','pg_catalog','information_schema','pg_toast') "
            "AND schema_name NOT LIKE 'pg_%'"
        )
        for row in schemas:
            await conn.execute(
                f'DROP SCHEMA IF EXISTS "{row["schema_name"]}" CASCADE'
            )

        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        if tables:
            names = ", ".join(row["tablename"] for row in tables)
            await conn.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture
async def db():
    """Real CallGraphDB connected to TEST_DATABASE_URL.

    Wipes the database before each test — project schemas dropped, all public
    tables truncated. Skips if TEST_DATABASE_URL is not set.

    Never uses DATABASE_URL (the server's production connection string) or
    BENCHMARK_DATABASE_URL (the persistent benchmark index).
    """
    if not _TEST_DSN:
        pytest.skip("TEST_DATABASE_URL not set")

    instance = await CallGraphDB.create(_TEST_DSN)
    await _wipe(instance._pool)
    yield instance
    await instance.close()


@pytest.fixture
def project_id(request) -> str:
    """Stable, unique project ID for the current test.

    Derived from the test class and method name so it is human-readable,
    does not collide with any other test, and is identical on every run
    (so logs and DB rows are traceable back to a specific test).
    """
    cls = request.node.cls.__name__ if request.node.cls else ""
    name = request.node.name
    raw = f"{cls}_{name}" if cls else name
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    return f"t_{slug}"[:60]


# ── In-memory helpers ─────────────────────────────────────────────────────────

def _node(
    node_id: str,
    *,
    type: str = "function",
    summary: str | None = None,
    docstring: str | None = None,
    body_hash: str = "abc123",
    decorators: str = "[]",
) -> dict:
    """Build a minimal node dict, inferring name and module from the dotted ID."""
    parts = node_id.split(".")
    return {
        "id": node_id,
        "name": parts[-1],
        "type": type,
        "module": ".".join(parts[:2]) if len(parts) >= 2 else parts[0],
        "summary": summary,
        "docstring": docstring,
        "body_hash": body_hash,
        "decorators": decorators,
    }


def _graph(
    *,
    project_id: str = "test",
    nodes: list[dict] | None = None,
    edges: list[tuple[str, str]] | None = None,
    caller_counts: dict[str, int] | None = None,
    churn: dict[str, int] | None = None,
    contracts: list[dict] | None = None,
    recent_violation_count: int = 0,
    recent_decisions: list[dict] | None = None,
    prev_snapshot: dict | None = None,
    current_hashes: dict[str, str] | None = None,
    decisions_since: list[dict] | None = None,
) -> GraphData:
    """Build a GraphData with sensible defaults for testing."""
    nodes = nodes or []
    return GraphData(
        project_id=project_id,
        nodes=nodes,
        edges=edges or [],
        caller_counts=caller_counts or {},
        churn=churn or {},
        contracts=contracts or [],
        recent_violation_count=recent_violation_count,
        recent_decisions=recent_decisions or [],
        prev_snapshot=prev_snapshot,
        current_hashes=current_hashes or {n["id"]: n["body_hash"] for n in nodes},
        decisions_since=decisions_since or [],
    )
