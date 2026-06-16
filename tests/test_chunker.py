"""
Tests for the embedding chunker (src/embeddings/chunker.py).

prepare_embed_text() determines the text that gets embedded for every function.
It controls semantic search quality: the order of sections, what's included
when a docstring is absent, how long bodies are truncated.

All tests are pure function calls — no DB, no async, no fixtures.
"""
import pytest
from src.embeddings.chunker import FunctionChunk, prepare_embed_text, extract_chunks


def _chunk(
    *,
    id: str = "src.mod.fn",
    name: str = "fn",
    file: str = "/project/src/mod.py",
    module: str = "src.mod",
    type: str = "function",
    signature: str = "def fn():",
    docstring: str = "",
    leading_comment: str = "",
    body: str = "",
    summary: str = "",
) -> FunctionChunk:
    return FunctionChunk(
        id=id, name=name, file=file, module=module, type=type,
        signature=signature, docstring=docstring,
        leading_comment=leading_comment, body=body,
        embed_text="", summary=summary,
    )


# ── prepare_embed_text: required sections ─────────────────────────────────────

class TestPrepareEmbedTextRequired:
    def test_function_id_always_present(self):
        text = prepare_embed_text(_chunk(id="src.api.create_user"))
        assert "src.api.create_user" in text

    def test_signature_always_present(self):
        text = prepare_embed_text(_chunk(signature="def create_user(name: str) -> User:"))
        assert "def create_user" in text

    def test_empty_chunk_still_produces_output(self):
        text = prepare_embed_text(_chunk())
        assert len(text) > 0


# ── prepare_embed_text: docstring priority ────────────────────────────────────

class TestDocstringPriority:
    """
    Docstring is the highest-quality signal for semantic search.
    When present it should appear and the leading_comment should not.
    """

    def test_docstring_included_when_present(self):
        text = prepare_embed_text(_chunk(docstring="Validate a user's email address."))
        assert "Validate a user" in text

    def test_docstring_labeled_correctly(self):
        text = prepare_embed_text(_chunk(docstring="Does something."))
        assert "Docstring:" in text

    def test_leading_comment_used_when_no_docstring(self):
        text = prepare_embed_text(_chunk(leading_comment="Queries the users table."))
        assert "Queries the users table." in text

    def test_leading_comment_labeled_as_comment(self):
        text = prepare_embed_text(_chunk(leading_comment="Queries the users table."))
        assert "Comment:" in text

    def test_docstring_takes_priority_over_leading_comment(self):
        """When both are present, docstring is used and comment is excluded."""
        text = prepare_embed_text(_chunk(
            docstring="Primary description.",
            leading_comment="Secondary comment.",
        ))
        assert "Primary description." in text
        assert "Secondary comment." not in text

    def test_no_docstring_and_no_comment_omits_both_sections(self):
        text = prepare_embed_text(_chunk(docstring="", leading_comment=""))
        assert "Docstring:" not in text
        assert "Comment:" not in text


# ── prepare_embed_text: summary section ──────────────────────────────────────

class TestSummarySection:
    """
    LLM-generated summaries are written after enrichment. When present
    they improve embedding quality for functions with poor docstrings.
    """

    def test_summary_included_when_present(self):
        text = prepare_embed_text(_chunk(summary="Creates a new user account."))
        assert "Creates a new user account." in text

    def test_summary_labeled_correctly(self):
        text = prepare_embed_text(_chunk(summary="Does X."))
        assert "Summary:" in text

    def test_no_summary_omits_section(self):
        text = prepare_embed_text(_chunk(summary=""))
        assert "Summary:" not in text

    def test_summary_appears_after_docstring(self):
        text = prepare_embed_text(_chunk(
            docstring="Short description.",
            summary="Longer LLM summary.",
        ))
        doc_pos = text.index("Short description.")
        sum_pos = text.index("Longer LLM summary.")
        assert sum_pos > doc_pos


# ── prepare_embed_text: body section ─────────────────────────────────────────

class TestBodySection:
    def test_body_included_when_present(self):
        text = prepare_embed_text(_chunk(body="return x + 1"))
        assert "return x + 1" in text

    def test_body_labeled_correctly(self):
        text = prepare_embed_text(_chunk(body="pass"))
        assert "Body:" in text

    def test_no_body_omits_section(self):
        text = prepare_embed_text(_chunk(body=""))
        assert "Body:" not in text

    def test_body_truncated_at_2000_chars(self):
        long_body = "x = 1\n" * 500  # >2000 chars
        text = prepare_embed_text(_chunk(body=long_body))
        # The body section should be present but truncated
        body_start = text.index("Body:")
        body_section = text[body_start:]
        assert len(body_section) < len(long_body)

    def test_short_body_not_truncated(self):
        short = "return x"
        text = prepare_embed_text(_chunk(body=short))
        assert "return x" in text


# ── prepare_embed_text: section ordering ─────────────────────────────────────

class TestSectionOrdering:
    """
    Order: Function ID → Signature → Docstring/Comment → Summary → Body.
    This ordering places the highest-quality signals first, matching the
    token budget behavior of embedding models.
    """

    def test_signature_comes_before_body(self):
        text = prepare_embed_text(_chunk(
            signature="def fn():", body="return 42"
        ))
        sig_pos = text.index("def fn():")
        body_pos = text.index("return 42")
        assert sig_pos < body_pos

    def test_id_comes_before_signature(self):
        text = prepare_embed_text(_chunk(
            id="src.mod.fn", signature="def fn():"
        ))
        id_pos = text.index("src.mod.fn")
        sig_pos = text.index("def fn():")
        assert id_pos < sig_pos


# ── extract_chunks ────────────────────────────────────────────────────────────

class TestExtractChunks:
    """
    extract_chunks(file_path, content) is the bridge between the parser layer
    and the embedding layer. It must produce one FunctionChunk per function node.
    """

    def test_returns_chunks_for_all_functions(self):
        src = """\
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b
"""
        chunks = extract_chunks("/project/src/math.py", src, project_root="/project")
        names = {c.name for c in chunks}
        assert "add" in names
        assert "multiply" in names

    def test_chunk_has_embed_text_field(self):
        chunks = extract_chunks("/project/src/mod.py", "def fn(): pass",
                                project_root="/project")
        for chunk in chunks:
            assert hasattr(chunk, "embed_text")

    def test_empty_file_returns_no_chunks(self):
        chunks = extract_chunks("/project/src/mod.py", "", project_root="/project")
        assert chunks == []

    def test_chunk_id_matches_parser_node_id(self):
        chunks = extract_chunks("/project/src/utils.py", "def helper(): pass",
                                project_root="/project")
        assert len(chunks) == 1
        assert chunks[0].id == "src.utils.helper"

    def test_class_with_method_produces_multiple_chunks(self):
        src = """\
class Calculator:
    def add(self, a, b):
        return a + b
"""
        chunks = extract_chunks("/project/src/calc.py", src, project_root="/project")
        # class node + method node
        assert len(chunks) >= 2
