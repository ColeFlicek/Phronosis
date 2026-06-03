from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..call_graph.storage import CallGraphDB
from ..embeddings.embedder import EmbeddingStore

# Separate vector index from Layer 2 (function_embeddings) so the two search
# spaces don't bleed into each other. Same dimension — same model handles both.
_CREATE_INDEX = """
CREATE VECTOR INDEX decision_embeddings IF NOT EXISTS
FOR (n:Decision)
ON (n.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: $dim,
    `vector.similarity_function`: 'cosine'
  }
}
"""

_UPSERT = """
MERGE (n:Decision {id: $id})
SET n.type        = $type,
    n.description = $description,
    n.created_at  = $created_at,
    n.embedding   = $embedding
"""

_QUERY = """
CALL db.index.vector.queryNodes('decision_embeddings', $top_k, $embedding)
YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC
"""

_DELETE = """
MATCH (n:Decision {id: $id}) DETACH DELETE n
"""


class DecisionMemory:
    """
    Layer 3 — decision reasoning storage.

    Structured data (full decision record, function linkage, parent chain)
    lives in SQLite. Semantic search over decision *reasoning* uses the same
    embedding model as Layer 2 but a completely separate neo4j vector index.

    No Graphiti, no secondary LLM calls — just the embedding provider already
    configured for the rest of the system.
    """

    def __init__(self, db: CallGraphDB, embeddings: EmbeddingStore) -> None:
        self._db = db
        self._embeddings = embeddings

    @classmethod
    async def create(cls, db: CallGraphDB, embeddings: EmbeddingStore) -> "DecisionMemory":
        obj = cls(db, embeddings)
        await obj.init()
        return obj

    async def init(self) -> None:
        async with self._embeddings._driver.session() as session:
            await session.run(_CREATE_INDEX, dim=self._embeddings._dim)

    async def close(self) -> None:
        pass  # driver is owned by EmbeddingStore; do not close it here

    # ── MCP tools ──────────────────────────────────────────────────────────

    async def log_decision(
        self,
        type: str,
        description: str,
        rejected_alternatives: str = "",
        trigger: str = "",
        linked_function_ids: list[str] | None = None,
        parent_decision_id: str | None = None,
    ) -> dict[str, str]:
        decision_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # ── Structured record → SQLite ──────────────────────────────────────
        await self._db.insert_decision({
            "id": decision_id,
            "type": type,
            "description": description,
            "rejected_alternatives": rejected_alternatives,
            "trigger": trigger,
            "parent_decision_id": parent_decision_id,
            "created_at": now,
        })
        if linked_function_ids:
            await self._db.insert_decision_functions(decision_id, linked_function_ids)

        # ── Reasoning embedding → neo4j ─────────────────────────────────────
        embed_text = _reasoning_text(
            type, description, rejected_alternatives, trigger, linked_function_ids or []
        )
        embedding = await self._embeddings.embed(embed_text)
        async with self._embeddings._driver.session() as session:
            await session.run(
                _UPSERT,
                id=decision_id,
                type=type,
                description=description,
                created_at=now,
                embedding=embedding,
            )

        return {"decision_id": decision_id, "created_at": now}

    async def get_decision_history(self, function_name: str) -> list[dict[str, Any]]:
        """All decisions linked to a function, ordered chronologically."""
        return await self._db.get_decisions_for_function(function_name)

    async def query_decisions(self, query_text: str, top_k: int = 10) -> list[dict[str, Any]]:
        """
        Semantic search over decision reasoning. Returns decisions whose
        intent, context, or rejected alternatives are similar to the query —
        useful for finding prior thinking relevant to a new change.
        """
        embedding = await self._embeddings.embed(query_text)
        async with self._embeddings._driver.session() as session:
            result = await session.run(_QUERY, embedding=embedding, top_k=top_k)
            hits = [dict(r) async for r in result]

        if not hits:
            return []

        # Hydrate full records from SQLite, attach similarity score
        records = []
        for hit in hits:
            async with self._db._db.execute(
                "SELECT * FROM decisions WHERE id=?", (hit["id"],)
            ) as cur:
                row = await cur.fetchone()
            if row:
                rec = dict(row)
                rec["score"] = round(hit["score"], 4)
                records.append(rec)
        return records


# ── Helpers ────────────────────────────────────────────────────────────────────

def _reasoning_text(
    type: str,
    description: str,
    rejected_alternatives: str,
    trigger: str,
    linked_function_ids: list[str],
) -> str:
    """
    Build the text that gets embedded for a decision.

    Deliberately structured around reasoning and intent rather than code shape:
    what was decided, why, what was considered and rejected, and what caused
    the decision. This keeps Layer 3 semantically distinct from Layer 2
    (which embeds code bodies and signatures).
    """
    parts = [
        f"Decision type: {type}",
        f"What was decided: {description}",
    ]
    if rejected_alternatives:
        parts.append(f"What was rejected: {rejected_alternatives}")
    if trigger:
        parts.append(f"What triggered this: {trigger}")
    if linked_function_ids:
        parts.append(f"Governs: {', '.join(linked_function_ids)}")
    return "\n".join(parts)
