"""
Tests for the tree-sitter call graph parser (src/call_graph/parser.py).

The parser is the foundational layer — every call graph, every get_callers
result, every impact radius analysis starts here. It has no direct tests.
When it produces wrong output the failure is silent: the call graph is
empty or incomplete, and queries return nothing.

All tests are pure function calls — no DB, no async, no fixtures.
Uses parse_file() as the single public entry point, asserting on
the shape and content of the returned (nodes, edges) pair.
"""
import pytest
from src.call_graph.parser import TreeSitterParser, FunctionNode, CallEdge

_parser = TreeSitterParser()
_ROOT = "/project"


def parse(content: str, path: str = "src/mod.py", root: str = _ROOT) -> tuple:
    """Parse content, using absolute paths so module derivation is deterministic.

    Passes '/project/src/mod.py' with root='/project' → module='src.mod'.
    Callers provide relative paths like 'src/mod.py'; we prepend the root.
    """
    abs_path = path if path.startswith("/") else f"{root}/{path}"
    return _parser.parse_file(abs_path, content, project_root=root)


# ── Tracer bullet ─────────────────────────────────────────────────────────────

class TestTracerBullet:
    def test_simple_function_produces_one_node(self):
        nodes, _ = parse("def hello(): pass")
        names = [n.name for n in nodes]
        assert "hello" in names

    def test_function_call_produces_edge(self):
        _, edges = parse("def greet():\n    hello()")
        callee_names = [e.callee_name for e in edges]
        assert "hello" in callee_names


# ── Module and node ID format ─────────────────────────────────────────────────

class TestNodeIdFormat:
    """
    Node IDs must follow the dotted module-path format that storage.py and
    get_callers() rely on for JOIN operations. Wrong format → silent empty results.
    """

    def test_top_level_function_id_is_module_dot_name(self):
        nodes, _ = parse("def my_func(): pass", path="src/utils.py")
        fn = next(n for n in nodes if n.name == "my_func")
        assert fn.id == "src.utils.my_func"

    def test_class_id_is_module_dot_classname(self):
        nodes, _ = parse("class MyClass: pass", path="src/models.py")
        cls = next(n for n in nodes if n.type == "class")
        assert cls.id == "src.models.MyClass"

    def test_method_id_is_module_dot_class_dot_method(self):
        nodes, _ = parse(
            "class A:\n    def method(self): pass",
            path="src/service.py",
        )
        method = next(n for n in nodes if n.name == "A.method")
        assert method.id == "src.service.A.method"

    def test_nested_path_produces_correct_module(self):
        nodes, _ = parse("def fn(): pass", path="src/api/handlers.py")
        fn = next(n for n in nodes if n.name == "fn")
        assert fn.id == "src.api.handlers.fn"
        assert fn.module == "src.api.handlers"

    def test_id_does_not_contain_file_extension(self):
        nodes, _ = parse("def fn(): pass", path="src/mod.py")
        fn = next(n for n in nodes if n.name == "fn")
        assert ".py" not in fn.id


# ── Class and method extraction ───────────────────────────────────────────────

class TestClassAndMethodExtraction:
    """
    A class with N methods must produce N+1 nodes (class + methods).
    Methods must have type='method' and the class must have type='class'.
    """

    def test_class_produces_class_node(self):
        nodes, _ = parse("class Foo:\n    pass")
        types = [n.type for n in nodes]
        assert "class" in types

    def test_class_node_name_is_class_name(self):
        nodes, _ = parse("class Calculator:\n    pass")
        cls = next(n for n in nodes if n.type == "class")
        assert cls.name == "Calculator"

    def test_method_produces_method_node(self):
        nodes, _ = parse("class C:\n    def method(self): pass")
        types = [n.type for n in nodes]
        assert "method" in types

    def test_class_with_two_methods_produces_three_nodes(self):
        src = """\
class MyClass:
    def method_a(self): pass
    def method_b(self): pass
"""
        nodes, _ = parse(src)
        assert len(nodes) == 3  # class + 2 methods

    def test_multiple_classes_all_extracted(self):
        src = """\
class A: pass
class B: pass
class C: pass
"""
        nodes, _ = parse(src)
        classes = [n for n in nodes if n.type == "class"]
        assert len(classes) == 3

    def test_method_type_is_method_not_function(self):
        nodes, _ = parse("class C:\n    def m(self): pass")
        m = next(n for n in nodes if n.name == "C.m")
        assert m.type == "method"

    def test_module_level_function_type_is_function(self):
        nodes, _ = parse("def standalone(): pass")
        fn = next(n for n in nodes if n.name == "standalone")
        assert fn.type == "function"

    def test_inheritance_edge_produced(self):
        _, edges = parse("class Child(Parent): pass")
        inherits = [e for e in edges if e.edge_type == "inherits"]
        assert any(e.callee_name == "Parent" for e in inherits)

    def test_class_file_path_matches_input(self):
        nodes, _ = parse("class X: pass", path="src/models.py")
        cls = next(n for n in nodes if n.type == "class")
        assert cls.file.endswith("src/models.py")


# ── Call edge extraction ──────────────────────────────────────────────────────

class TestCallEdgeExtraction:
    """
    Call edges are what make get_callers() and get_impact_radius() work.
    They must correctly attribute calls to their enclosing function.
    """

    def test_direct_call_produces_edge(self):
        _, edges = parse("def caller():\n    callee()")
        assert any(e.callee_name == "callee" for e in edges)

    def test_edge_caller_id_matches_enclosing_function(self):
        _, edges = parse("def caller():\n    callee()", path="src/mod.py")
        edge = next(e for e in edges if e.callee_name == "callee")
        assert edge.caller_id == "src.mod.caller"

    def test_method_call_attributed_to_method_not_class(self):
        src = """\
class C:
    def do_work(self):
        helper()
"""
        _, edges = parse(src, path="src/mod.py")
        edge = next(e for e in edges if e.callee_name == "helper")
        assert edge.caller_id == "src.mod.C.do_work"

    def test_chained_attribute_call_preserved(self):
        _, edges = parse("def fn():\n    obj.method()")
        edge = next(e for e in edges if e.edge_type == "calls")
        assert "method" in edge.callee_name

    def test_call_inside_if_block_still_detected(self):
        src = """\
def fn():
    if condition:
        helper()
"""
        _, edges = parse(src)
        assert any(e.callee_name == "helper" for e in edges)

    def test_call_inside_for_loop_detected(self):
        src = """\
def fn():
    for x in items:
        process(x)
"""
        _, edges = parse(src)
        assert any(e.callee_name == "process" for e in edges)

    def test_nested_function_calls_not_attributed_to_outer(self):
        """
        Calls inside a nested def must NOT be attributed to the outer function.
        This is the enclosing-scope isolation rule.
        """
        src = """\
def outer():
    def inner():
        db_call()
"""
        _, edges = parse(src, path="src/mod.py")
        outer_edges = [e for e in edges if e.caller_id == "src.mod.outer"]
        assert not any(e.callee_name == "db_call" for e in outer_edges)

    def test_cross_module_call_produces_edge(self):
        src = """\
def fn():
    other_module.do_thing()
"""
        _, edges = parse(src)
        assert any("do_thing" in e.callee_name for e in edges)

    def test_multiple_calls_in_function_all_captured(self):
        src = """\
def process():
    validate()
    transform()
    save()
"""
        _, edges = parse(src)
        callees = {e.callee_name for e in edges if e.edge_type == "calls"}
        assert callees >= {"validate", "transform", "save"}

    def test_import_statement_produces_import_edge(self):
        _, edges = parse("import os")
        imports = [e for e in edges if e.edge_type == "imports"]
        assert any(e.callee_name == "os" for e in imports)

    def test_from_import_produces_import_edge(self):
        _, edges = parse("from pathlib import Path")
        imports = [e for e in edges if e.edge_type == "imports"]
        assert any("pathlib" in e.callee_name for e in imports)

    def test_edge_type_for_function_call_is_calls(self):
        _, edges = parse("def fn():\n    helper()")
        edge = next(e for e in edges if e.callee_name == "helper")
        assert edge.edge_type == "calls"


# ── Decorator extraction ──────────────────────────────────────────────────────

class TestDecoratorExtraction:
    """
    Decorators are used by entry_points detection in analysis.py to identify
    HTTP route handlers. Missing decorators = missing entry points.
    """

    def test_simple_decorator_captured(self):
        src = """\
@login_required
def view(): pass
"""
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "view")
        assert "login_required" in fn.decorators

    def test_attribute_decorator_captured(self):
        src = """\
@router.get("/path")
def handler(): pass
"""
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "handler")
        assert "router.get" in fn.decorators

    def test_multiple_decorators_all_captured(self):
        src = """\
@app.route("/")
@login_required
def view(): pass
"""
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "view")
        assert len(fn.decorators) == 2

    def test_function_without_decorator_has_empty_list(self):
        nodes, _ = parse("def plain(): pass")
        fn = next(n for n in nodes if n.name == "plain")
        assert fn.decorators == []

    def test_decorated_method_in_class_has_decorator(self):
        src = """\
class MyView:
    @staticmethod
    def get(): pass
"""
        nodes, _ = parse(src)
        method = next(n for n in nodes if n.name == "MyView.get")
        assert "staticmethod" in method.decorators


# ── Docstring and body extraction ─────────────────────────────────────────────

class TestDocstringAndBodyExtraction:
    """
    Docstrings power the embedding quality fallback (no docstring → large model).
    Body text is what performance detectors read. Missing = silent wrong results.
    """

    def test_docstring_extracted_from_function(self):
        src = '''\
def fn():
    """This does something useful."""
    pass
'''
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "fn")
        assert "This does something useful." in fn.docstring

    def test_function_without_docstring_has_empty_docstring(self):
        nodes, _ = parse("def fn(): pass")
        fn = next(n for n in nodes if n.name == "fn")
        assert fn.docstring == ""

    def test_body_text_stored_in_node(self):
        src = """\
def fn():
    x = 1
    return x
"""
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "fn")
        assert "x = 1" in fn.body

    def test_leading_comment_extracted_when_no_docstring(self):
        src = """\
def fn():
    # This does a database query
    return db.execute("SELECT 1")
"""
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "fn")
        assert "database query" in fn.leading_comment

    def test_leading_comment_empty_when_docstring_present(self):
        src = '''\
def fn():
    """Docstring here."""
    # A comment
    pass
'''
        nodes, _ = parse(src)
        fn = next(n for n in nodes if n.name == "fn")
        assert fn.leading_comment == ""

    def test_body_hash_is_hex_string(self):
        nodes, _ = parse("def fn(): pass")
        fn = next(n for n in nodes if n.name == "fn")
        assert len(fn.body_hash) == 16
        assert all(c in "0123456789abcdef" for c in fn.body_hash)

    def test_body_hash_changes_when_body_changes(self):
        nodes_a, _ = parse("def fn():\n    x = 1")
        nodes_b, _ = parse("def fn():\n    x = 2")
        hash_a = next(n for n in nodes_a if n.name == "fn").body_hash
        hash_b = next(n for n in nodes_b if n.name == "fn").body_hash
        assert hash_a != hash_b

    def test_identical_bodies_have_same_hash(self):
        src = "def fn():\n    return 42"
        nodes_a, _ = parse(src)
        nodes_b, _ = parse(src)
        hash_a = next(n for n in nodes_a if n.name == "fn").body_hash
        hash_b = next(n for n in nodes_b if n.name == "fn").body_hash
        assert hash_a == hash_b


# ── Edge cases and robustness ─────────────────────────────────────────────────

class TestRobustness:
    def test_empty_file_produces_no_nodes(self):
        nodes, edges = parse("")
        assert nodes == []

    def test_comment_only_file_produces_no_nodes(self):
        nodes, _ = parse("# This is just a comment\n# Another comment")
        assert nodes == []

    def test_unsupported_extension_returns_empty(self):
        nodes, edges = _parser.parse_file("file.unknown", "content", "/")
        assert nodes == []
        assert edges == []

    def test_nested_class_inside_function_scoped_correctly(self):
        src = """\
def outer():
    class Inner:
        pass
"""
        nodes, _ = parse(src, path="src/mod.py")
        inner = next(n for n in nodes if n.type == "class")
        assert "outer" in inner.id
        assert "Inner" in inner.id

    def test_async_function_extracted_same_as_sync(self):
        nodes, _ = parse("async def fetch(): pass")
        fn = next(n for n in nodes if n.name == "fetch")
        assert fn.type == "function"

    def test_async_method_in_class_extracted(self):
        src = """\
class Client:
    async def connect(self): pass
"""
        nodes, _ = parse(src)
        method = next(n for n in nodes if "connect" in n.name)
        assert method.type == "method"

    def test_file_path_stored_on_node(self):
        nodes, _ = parse("def fn(): pass", path="src/api/views.py")
        fn = next(n for n in nodes if n.name == "fn")
        assert fn.file.endswith("src/api/views.py")

    def test_project_root_stripped_from_module(self):
        nodes, _ = parse("def fn(): pass", path="src/views.py")
        fn = next(n for n in nodes if n.name == "fn")
        # Module is derived from path relative to root, not the full absolute path
        assert fn.module == "src.views"
