"""
Tests for schema object extraction and cardinality labeling (src/schema_objects.py).

Public interfaces under test:
  - _KNOWN_CARDINALITY dict
  - SchemaObject dataclass
  - _class_description(class_name, methods, docstring, cardinality) → str
"""
import pytest
from src.schema_objects import (
    SchemaObject,
    _class_description,
    _KNOWN_CARDINALITY,
)


# ── Known cardinality table ───────────────────────────────────────────────────

class TestKnownCardinality:
    """Python type cardinality facts baked into _KNOWN_CARDINALITY must stay correct."""

    def test_python_list_is_high(self):
        assert _KNOWN_CARDINALITY["list"] == "HIGH"

    def test_python_dict_is_high(self):
        assert _KNOWN_CARDINALITY["dict"] == "HIGH"

    def test_python_set_is_high(self):
        assert _KNOWN_CARDINALITY["set"] == "HIGH"

    def test_python_str_is_scalar(self):
        assert _KNOWN_CARDINALITY["str"] == "SCALAR"

    def test_python_bool_is_scalar(self):
        assert _KNOWN_CARDINALITY["bool"] == "SCALAR"

    def test_python_int_is_scalar(self):
        assert _KNOWN_CARDINALITY["int"] == "SCALAR"


# ── Class description text ────────────────────────────────────────────────────

class TestClassDescription:
    """_class_description produces embedding-ready text for a Python class."""

    def test_contains_class_name(self):
        text = _class_description("CallGraphDB", ["create", "get_callers"], "", "LOW")
        assert "CallGraphDB" in text

    def test_contains_cardinality(self):
        text = _class_description("FunctionNode", [], "", "MEDIUM")
        assert "MEDIUM" in text

    def test_contains_method_names(self):
        text = _class_description("Indexer", ["index_project", "index_changes"], "", "LOW")
        assert "index_project" in text
        assert "index_changes" in text

    def test_docstring_included_when_present(self):
        doc = "Manages the call graph database connection pool."
        text = _class_description("CallGraphDB", [], doc, "LOW")
        assert "Manages" in text

    def test_empty_methods_no_crash(self):
        text = _class_description("MyClass", [], "", "SCALAR")
        assert "MyClass" in text

    def test_long_docstring_truncated(self):
        long_doc = "x" * 500
        text = _class_description("MyClass", [], long_doc, "MEDIUM")
        assert len(text) < 1000


# ── SchemaObject dataclass ────────────────────────────────────────────────────

class TestSchemaObject:
    def test_construction_with_required_fields(self):
        obj = SchemaObject(
            name="Indexer",
            source="python_class",
            project_id="scopenos",
            cardinality="LOW",
            description="Python class: Indexer",
        )
        assert obj.name == "Indexer"
        assert obj.cardinality == "LOW"
        assert obj.embedding is None

    def test_references_default_empty(self):
        obj = SchemaObject(
            name="CallGraphDB", source="python_class", project_id="test",
            cardinality="LOW", description="manages DB",
        )
        assert obj.references == []
        assert obj.referenced_by == []

    def test_embedding_can_be_set(self):
        obj = SchemaObject(
            name="Indexer", source="python_class", project_id="test",
            cardinality="LOW", description="indexer",
        )
        obj.embedding = [0.1, 0.2, 0.3]
        assert obj.embedding == [0.1, 0.2, 0.3]
