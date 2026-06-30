"""
Schema object extraction and embedding for performance analysis.

A "schema object" is a Python class whose cardinality matters for performance
reasoning. Each object is embedded as a structured description that captures:
  - What it represents
  - What methods it has
  - Its cardinality class: SCALAR | LOW | MEDIUM | HIGH | UNBOUNDED

When two HIGH/UNBOUNDED objects both appear in a nested call pattern, the
pattern has O(n²) or worse potential and is flagged with high confidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .call_graph.storage import CallGraphDB
    from .embeddings.embedder import EmbeddingStore

# ── Cardinality heuristics ────────────────────────────────────────────────────

# Cardinality for well-known Python types
_KNOWN_CARDINALITY: dict[str, str] = {
    "list":  "HIGH",
    "dict":  "HIGH",
    "set":   "HIGH",
    "tuple": "MEDIUM",
    "str":   "SCALAR",
    "int":   "SCALAR",
    "bool":  "SCALAR",
    "None":  "SCALAR",
}


# ── SchemaObject ─────────────────────────────────────────────────────────────

@dataclass
class SchemaObject:
    name: str                    # class name
    source: str                  # always "python_class"
    project_id: str
    cardinality: str             # SCALAR | LOW | MEDIUM | HIGH | UNBOUNDED
    description: str             # structured text for embedding
    references: list[str] = field(default_factory=list)
    referenced_by: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


def _class_description(
    class_name: str,
    methods: list[str],
    docstring: str,
    cardinality: str,
) -> str:
    parts = [
        f"Python class: {class_name}",
        f"Cardinality: {cardinality}",
    ]
    if docstring:
        parts.append(f"Purpose: {docstring[:200]}")
    if methods:
        parts.append(f"Methods: {', '.join(methods[:15])}")
    return "\n".join(parts)


# ── Extraction ────────────────────────────────────────────────────────────────

async def extract_python_class_objects(db: "CallGraphDB", project_id: str) -> list[SchemaObject]:
    """Build SchemaObjects for Python classes indexed in the call graph."""
    class_rows = await db.get_class_nodes(project_id)
    fn_rows = await db.get_function_nodes_light(project_id)

    # Group method names by their class id prefix (module.ClassName.method → module.ClassName)
    class_methods: dict[str, list[str]] = {}
    for fn in fn_rows:
        parts = fn["id"].split(".")
        if len(parts) >= 2:
            parent = ".".join(parts[:-1])
            class_methods.setdefault(parent, []).append(fn["name"])

    objects = []
    for cls in class_rows:
        methods = class_methods.get(cls["id"], [])
        cardinality = _KNOWN_CARDINALITY.get(cls["name"], "MEDIUM")
        desc = _class_description(cls["name"], methods, cls["docstring"] or "", cardinality)
        objects.append(SchemaObject(
            name=cls["name"],
            source="python_class",
            project_id=project_id,
            cardinality=cardinality,
            description=desc,
        ))
    return objects


# ── Embedding + storage ───────────────────────────────────────────────────────

async def embed_and_store_schema_objects(
    objects: list[SchemaObject],
    embeddings: "EmbeddingStore",
    db: "CallGraphDB",
    project_id: str,
) -> int:
    """Embed all objects and upsert into schema_object_embeddings table."""
    if not objects:
        return 0

    texts = [o.description for o in objects]
    vecs = await embeddings._embed_batch(texts)

    rows = []
    for obj, vec in zip(objects, vecs):
        obj.embedding = vec
        rows.append((
            project_id,
            obj.name,
            obj.source,
            obj.cardinality,
            obj.description,
            json.dumps(obj.references),
            json.dumps(obj.referenced_by),
            vec,
        ))

    await db.upsert_schema_objects(rows)
    return len(objects)


async def load_schema_objects(db: "CallGraphDB", project_id: str) -> list[SchemaObject]:
    """Load previously embedded schema objects for a project."""
    rows = await db.load_schema_objects(project_id)
    return [
        SchemaObject(
            name=r["name"],
            source=r["source"],
            project_id=project_id,
            cardinality=r["cardinality"],
            description=r["description"],
            references=json.loads(r["refs"]),
            referenced_by=json.loads(r["refs_in"]),
            embedding=list(r["embedding"]) if r["embedding"] is not None else None,
        )
        for r in rows
    ]


# ── Main entry point ──────────────────────────────────────────────────────────

async def index_schema_objects(
    db: "CallGraphDB",
    embeddings: "EmbeddingStore",
    project_id: str,
) -> dict:
    """
    Extract, embed, and store Python class schema objects for a project.
    Called automatically by index_changes after each index run.
    """
    objects = await extract_python_class_objects(db, project_id)
    count = await embed_and_store_schema_objects(objects, embeddings, db, project_id)
    return {
        "project_id": project_id,
        "python_classes": count,
        "total": count,
    }
