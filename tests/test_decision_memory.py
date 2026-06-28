"""
Tests for the decision memory layer (src/decision_memory/memory.py).

Decision memory is how agents record WHY code is the way it is. It also
powers the suppression logic in check_performance() — decisions with
type='Performance' suppress findings for linked functions.

Three behaviors under test:
  _reasoning_text  — pure function that formats the embedding text
  log_decision     — writes structured record + embedding (embedding mocked)
  get_decision_history  — reads decisions linked to a function
"""
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from src.decision_memory.memory import DecisionMemory, _reasoning_text
from src.call_graph.storage import CallGraphDB
from src.call_graph.parser import FunctionNode


def _node(node_id: str) -> FunctionNode:
    parts = node_id.split(".")
    return FunctionNode(
        id=node_id, name=parts[-1],
        file=f"/project/{parts[0]}.py",
        module=".".join(parts[:2]) if len(parts) >= 2 else parts[0],
        type="function", signature=f"def {parts[-1]}():",
        body="pass", docstring="", body_hash="abc", is_external=False,
    )


# ── _reasoning_text: pure function ───────────────────────────────────────────

class TestReasoningText:
    """
    _reasoning_text formats the text that gets embedded for semantic search.
    It must include all sections present and omit absent ones.
    """

    def test_type_and_description_always_present(self):
        text = _reasoning_text("Architectural", "Chose asyncpg over psycopg2", "", "", [])
        assert "Architectural" in text
        assert "Chose asyncpg over psycopg2" in text

    def test_rejected_alternatives_included_when_present(self):
        text = _reasoning_text("Design", "Used SQLite", "Tried Postgres", "", [])
        assert "Tried Postgres" in text

    def test_rejected_alternatives_omitted_when_empty(self):
        text = _reasoning_text("Design", "Used SQLite", "", "", [])
        assert "rejected" not in text.lower()

    def test_trigger_included_when_present(self):
        text = _reasoning_text("Patch", "Added timeout", "", "CVE-2024-001", [])
        assert "CVE-2024-001" in text

    def test_trigger_omitted_when_empty(self):
        text = _reasoning_text("Patch", "Added timeout", "", "", [])
        assert "triggered" not in text.lower()

    def test_linked_function_ids_included(self):
        text = _reasoning_text("Implementation", "Used asyncio", "", "",
                                ["src.db.connect", "src.db.query"])
        assert "src.db.connect" in text
        assert "src.db.query" in text

    def test_empty_function_ids_omitted(self):
        text = _reasoning_text("Implementation", "Used asyncio", "", "", [])
        assert "Governs:" not in text

    def test_all_fields_present_all_sections_appear(self):
        text = _reasoning_text(
            "Architectural", "Chose X", "Rejected Y", "ticket-123",
            ["src.mod.fn"]
        )
        assert "Architectural" in text
        assert "Chose X" in text
        assert "Rejected Y" in text
        assert "ticket-123" in text
        assert "src.mod.fn" in text


# ── log_decision + get_decision_history ──────────────────────────────────────

@pytest_asyncio.fixture
async def memory(db: CallGraphDB):
    """DecisionMemory with mocked embedding store (no API key needed)."""
    embeddings = MagicMock()
    embeddings.upsert_decision_embedding = AsyncMock()
    embeddings.delete_decision_embedding = AsyncMock()
    return DecisionMemory(db, embeddings)


class TestLogDecision:
    @pytest.mark.asyncio
    async def test_log_returns_decision_id_and_timestamp(self, memory: DecisionMemory):
        result = await memory.log_decision(
            type="Implementation",
            description="Chose asyncpg",
            project_id="proj",
        )
        assert "decision_id" in result
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_decision_id_is_uuid(self, memory: DecisionMemory):
        result = await memory.log_decision(
            type="Implementation", description="Did X", project_id="proj"
        )
        # Should parse as UUID without error
        uuid.UUID(result["decision_id"])

    @pytest.mark.asyncio
    async def test_embedding_is_called_once(self, memory: DecisionMemory):
        await memory.log_decision(
            type="Patch", description="Fixed bug", project_id="proj"
        )
        memory._embeddings.upsert_decision_embedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_embedding_receives_reasoning_text(self, memory: DecisionMemory):
        await memory.log_decision(
            type="Architectural",
            description="Moved to microservices",
            rejected_alternatives="Monolith",
            project_id="proj",
        )
        call_args = memory._embeddings.upsert_decision_embedding.call_args
        reasoning = call_args[0][1]  # second positional arg
        assert "Moved to microservices" in reasoning
        assert "Monolith" in reasoning

    @pytest.mark.asyncio
    async def test_logged_decision_visible_in_history(self, memory: DecisionMemory, db: CallGraphDB, project_id: str):
        await db.upsert_project("proj", "proj", "/project")
        await db.upsert_nodes([_node("src.cache.get")], "proj")
        await memory.log_decision(
            type="Design",
            description="Added caching layer",
            linked_function_ids=["src.cache.get"],
            project_id="proj",
        )
        history = await memory.get_decision_history("src.cache.get", "proj")
        assert len(history) >= 1
        descriptions = [h["description"] for h in history]
        assert "Added caching layer" in descriptions

    @pytest.mark.asyncio
    async def test_multiple_decisions_all_linked(self, memory: DecisionMemory, db: CallGraphDB, project_id: str):
        await db.upsert_project("proj", "proj", "/project")
        await db.upsert_nodes([_node("src.mod.fn")], "proj")
        for desc in ["First decision", "Second decision"]:
            await memory.log_decision(
                type="Implementation",
                description=desc,
                linked_function_ids=["src.mod.fn"],
                project_id="proj",
            )
        history = await memory.get_decision_history("src.mod.fn", "proj")
        descriptions = {h["description"] for h in history}
        assert "First decision" in descriptions
        assert "Second decision" in descriptions


class TestGetDecisionHistory:
    @pytest.mark.asyncio
    async def test_empty_history_for_unlinked_function(self, memory: DecisionMemory):
        history = await memory.get_decision_history("src.mod.no_decisions", "proj")
        assert history == []

    @pytest.mark.asyncio
    async def test_scoped_to_project(self, memory: DecisionMemory, db: CallGraphDB, project_id: str):
        """Decisions logged for proj_a must not appear when querying proj_b."""
        await db.upsert_project("proj_a", "proj_a", "/project")
        await db.upsert_project("proj_b", "proj_b", "/project")
        await db.upsert_nodes([_node("src.mod.fn")], "proj_a")
        await memory.log_decision(
            type="Patch",
            description="Only for proj_a",
            linked_function_ids=["src.mod.fn"],
            project_id="proj_a",
        )
        history = await memory.get_decision_history("src.mod.fn", "proj_b")
        assert history == []

    @pytest.mark.asyncio
    async def test_history_includes_type_and_description(self, memory: DecisionMemory, db: CallGraphDB, project_id: str):
        await db.upsert_project("proj", "proj", "/project")
        await db.upsert_nodes([_node("src.cmd.handle")], "proj")
        await memory.log_decision(
            type="Architectural",
            description="Switched to CQRS",
            linked_function_ids=["src.cmd.handle"],
            project_id="proj",
        )
        history = await memory.get_decision_history("src.cmd.handle", "proj")
        assert len(history) == 1
        assert history[0]["type"] == "Architectural"
        assert history[0]["description"] == "Switched to CQRS"
