"""
Tests for POST /api/signup endpoint.

The email sender is injected so tests verify it's called correctly
without sending real mail. A missing email body returns 400.
An existing user gets a new key issued (idempotent).
"""
import pytest
import pytest_asyncio
import httpx

from src.call_graph.storage import CallGraphDB
from src.auth import set_auth_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _wire_auth(db):
    """Wire the shared db fixture into the auth module for signup tests."""
    set_auth_db(db)


def make_app(db, email_sender):
    """Minimal ASGI app with only the signup route registered."""
    from fastmcp import FastMCP
    from src.web.routes import register_routes

    async def get_services():
        class FakeServices:
            pass
        svc = FakeServices()
        svc.db = db
        return svc

    mcp = FastMCP("test")
    register_routes(mcp, get_services, email_sender=email_sender)
    return mcp.http_app()


async def _post(app, path, json):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=json)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_signup_creates_user_and_sends_key(db):
    sent = []

    async def capture_email(to, api_key):
        sent.append({"to": to, "api_key": api_key})

    app = make_app(db, email_sender=capture_email)
    resp = await _post(app, "/api/signup", {"email": "alice@example.com"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(sent) == 1
    assert sent[0]["to"] == "alice@example.com"
    assert sent[0]["api_key"]


@pytest.mark.asyncio
async def test_signup_user_persisted_in_db(db):
    async def noop_email(to, api_key):
        pass

    app = make_app(db, email_sender=noop_email)
    await _post(app, "/api/signup", {"email": "bob@example.com"})

    async with db._db.execute("SELECT email FROM users WHERE email = ?", ("bob@example.com",)) as cur:
        row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_signup_missing_email_returns_400(db):
    async def noop_email(to, api_key):
        pass

    app = make_app(db, email_sender=noop_email)
    resp = await _post(app, "/api/signup", {})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_signup_existing_user_issues_new_key(db):
    sent = []

    async def capture_email(to, api_key):
        sent.append(api_key)

    await db.create_user("carol@example.com")
    app = make_app(db, email_sender=capture_email)
    await _post(app, "/api/signup", {"email": "carol@example.com"})
    await _post(app, "/api/signup", {"email": "carol@example.com"})

    assert len(sent) == 2
    assert sent[0] != sent[1]
