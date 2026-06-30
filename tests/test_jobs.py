"""
Tests for background job dispatch (Phase 12).

Uses a real Redis test DB (db=1) to avoid colliding with development.
Tests dispatch behavior — not job execution (workers run separately).
"""
import json
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from rq import Queue
from rq.job import Job, JobStatus
from redis import Redis

from src.call_graph.storage import CallGraphDB
from src.auth import set_auth_db

TEST_REDIS_URL = "redis://localhost:6379/1"  # DB 1 — isolated from dev
TEST_QUEUE_NAME = "scopenos-test"

# Skip all Redis-dependent tests when Redis is not reachable.
# In CI, Redis is a sidecar service and these tests run normally.
# Locally, set REDIS_URL=redis://localhost:6379 to run them.
def _redis_available() -> bool:
    try:
        Redis.from_url(TEST_REDIS_URL).ping()
        return True
    except Exception:
        return False

_redis_mark = pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not available — set REDIS_URL=redis://localhost:6379 to run"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def redis_conn():
    """Real Redis connection on test DB. Flushes before each test."""
    r = Redis.from_url(TEST_REDIS_URL)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def test_queue(redis_conn):
    return Queue(TEST_QUEUE_NAME, connection=redis_conn)


# ── Queue module ──────────────────────────────────────────────────────────────

@_redis_mark
def test_get_redis_uses_env_var(monkeypatch):
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    from src.queue import get_redis
    r = get_redis()
    assert r.ping()
    r.close()


@_redis_mark
def test_get_queue_returns_rq_queue(monkeypatch):
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    from src.queue import get_queue
    q = get_queue()
    assert isinstance(q, Queue)


# ── GET /api/jobs/{job_id} ────────────────────────────────────────────────────

@_redis_mark
@_redis_mark
@pytest.mark.asyncio
async def test_jobs_endpoint_returns_queued_status(db, monkeypatch):
    """GET /api/jobs/{id} returns status for a queued job."""
    import httpx
    from fastmcp import FastMCP
    from src.web.routes import register_routes
    from src import queue as queue_mod

    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    fake_redis = Redis.from_url(TEST_REDIS_URL)
    fake_queue = Queue(TEST_QUEUE_NAME, connection=fake_redis)

    # Enqueue a dummy job
    job = fake_queue.enqueue(lambda: None)

    async def get_services():
        class S:
            pass
        s = S()
        s.db = db
        return s

    with patch.object(queue_mod, "get_redis", return_value=fake_redis):
        mcp = FastMCP("test")
        register_routes(mcp, get_services)
        app = mcp.http_app()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/jobs/{job.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["status"] in ("queued", "started", "finished", "failed", "stopped")
    fake_redis.close()


@_redis_mark
@_redis_mark
@pytest.mark.asyncio
async def test_jobs_endpoint_returns_404_for_unknown_job(db, monkeypatch):
    """GET /api/jobs/unknown returns 404."""
    import httpx
    from fastmcp import FastMCP
    from src.web.routes import register_routes
    from src import queue as queue_mod

    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    fake_redis = Redis.from_url(TEST_REDIS_URL)

    async def get_services():
        class S:
            pass
        s = S()
        s.db = db
        return s

    with patch.object(queue_mod, "get_redis", return_value=fake_redis):
        mcp = FastMCP("test")
        register_routes(mcp, get_services)
        app = mcp.http_app()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/jobs/no-such-job-id")

    assert resp.status_code == 404
    fake_redis.close()


# ── Per-user rate limiting (enrich_summaries / reembed_project) ───────────────
# index_project is now synchronous so rate limiting only applies to
# background-job tools: enrich_summaries and reembed_project.


@_redis_mark
@_redis_mark
@pytest.mark.asyncio
async def test_enrich_summaries_returns_job_id(db, redis_conn, monkeypatch):
    """enrich_summaries enqueues a job rather than blocking on LLM calls."""
    set_auth_db(db)
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)

    await db._db.execute(
        "INSERT INTO users (id, email, plan, created_at) VALUES (?, ?, ?, ?)",
        ("u3", "carol@example.com", "paid", "2026-01-01T00:00:00"),
    )
    await db._db.execute(
        "INSERT INTO project_access (user_id, project_id, role) VALUES (?, ?, ?)",
        ("u3", "repo-b", "owner"),
    )

    from src.server import Services
    from src.dependency_fingerprint import DependencyChecker
    from src import queue as queue_mod

    fake_queue = Queue(TEST_QUEUE_NAME, connection=redis_conn)
    fake_svcs = Services(
        db=db, embeddings=MagicMock(), pipeline=MagicMock(),
        decisions=MagicMock(), indexer=MagicMock(),
        contracts=MagicMock(), checker=DependencyChecker(),
    )

    with patch.object(queue_mod, "get_queue", return_value=fake_queue), \
         patch("src.server._get_services", new=AsyncMock(return_value=fake_svcs)), \
         patch("src.tools.indexing.get_current_user", return_value={"id": "u3", "email": "carol@example.com"}):

        from src.server import enrich_summaries
        result = json.loads(await enrich_summaries("repo-b"))

    assert "job_id" in result
    assert result["status"] == "queued"
    assert fake_queue.count == 1


@_redis_mark
@_redis_mark
@pytest.mark.asyncio
async def test_index_changes_runs_synchronously(db, monkeypatch):
    """index_changes must NOT enqueue — it returns a real result immediately."""
    set_auth_db(db)
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)

    await db._db.execute(
        "INSERT INTO users (id, email, plan, created_at) VALUES (?, ?, ?, ?)",
        ("u4", "dave@example.com", "paid", "2026-01-01T00:00:00"),
    )
    await db._db.execute(
        "INSERT INTO project_access (user_id, project_id, role) VALUES (?, ?, ?)",
        ("u4", "repo-c", "owner"),
    )

    from src.server import Services
    from src.dependency_fingerprint import DependencyChecker

    mock_indexer = MagicMock()
    mock_indexer.index_changes = AsyncMock(return_value={"status": "ok", "functions_updated": 3})

    fake_svcs = Services(
        db=db, embeddings=MagicMock(), pipeline=MagicMock(),
        decisions=MagicMock(), indexer=mock_indexer,
        contracts=MagicMock(), checker=DependencyChecker(),
    )

    with patch("src.server._get_services", new=AsyncMock(return_value=fake_svcs)), \
         patch("src.tools.indexing.get_current_user", return_value={"id": "u4", "email": "dave@example.com"}):

        from src.server import index_changes
        result = json.loads(await index_changes(["src/foo.py"], {"src/foo.py": "def f(): pass"}, project_id="repo-c"))

    # Must return real result, not a job envelope
    assert result["status"] == "ok"
    assert "functions_updated" in result
    assert "job_id" not in result


