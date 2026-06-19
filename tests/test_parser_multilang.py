"""
Tests for the Swift, Kotlin, and PHP precision parsers.

All tests are stub-based (no DB, no network). The TreeSitterParser is
instantiated directly; assertions cover node extraction, call edge
extraction, async detection, return type parsing, and parameter names.
"""
import pytest
from src.call_graph.parser import TreeSitterParser, FunctionNode

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def parser() -> TreeSitterParser:
    return TreeSitterParser()


def _nodes(parser, ext, code):
    nodes, _ = parser.parse_file(f"src/file{ext}", code)
    return {n.name.split(".")[-1]: n for n in nodes}


def _edges(parser, ext, code):
    _, edges = parser.parse_file(f"src/file{ext}", code)
    return [(e.caller_id.split(".")[-1], e.callee_name) for e in edges]


# ══ Swift ═════════════════════════════════════════════════════════════════════

SWIFT_BASIC = """
class Calculator {
    func add(a: Int, b: Int) -> Int {
        let r = square(a)
        return r + b
    }
    func square(_ x: Int) -> Int { return x * x }
    init(config: Config) {}
}
"""

SWIFT_ASYNC = """
class Fetcher {
    func fetchData(url: String) async -> Data {
        let result = await network.get(url)
        let parsed = JSON.parse(result)
        return parsed
    }
    func syncMethod() -> String { return \"\" }
}
"""

SWIFT_STRUCT = """
struct Point {
    func distance(to other: Point) -> Double {
        return sqrt(dx(other) + dy(other))
    }
    private func dx(_ other: Point) -> Double { return 0.0 }
    private func dy(_ other: Point) -> Double { return 0.0 }
}
"""

SWIFT_PROTOCOL = """
protocol Drawable {
    func draw() -> Void
    func resize(factor: Double) -> Void
}
"""

SWIFT_TOP_LEVEL = """
func greet(name: String) -> String {
    return format(name)
}
func format(_ s: String) -> String { return s }
"""


class TestSwiftParser:
    def test_extension_registered(self, parser):
        assert ".swift" in parser.supported_extensions

    def test_class_and_methods_extracted(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_BASIC)
        assert "Calculator" in ns
        assert ns["Calculator"].type == "class"
        assert "add" in ns
        assert ns["add"].type == "method"
        assert "square" in ns
        assert "init" in ns

    def test_method_enclosing_class(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_BASIC)
        assert ns["add"].enclosing_class == "Calculator"
        assert ns["square"].enclosing_class == "Calculator"
        assert ns["init"].enclosing_class == "Calculator"

    def test_return_type_extraction(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_BASIC)
        assert ns["add"].return_type == "Int"
        assert ns["square"].return_type == "Int"

    def test_parameter_names(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_BASIC)
        assert "a" in ns["add"].parameter_names
        assert "b" in ns["add"].parameter_names

    def test_start_end_lines(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_BASIC)
        assert ns["add"].start_line > 0
        assert ns["add"].end_line >= ns["add"].start_line

    def test_async_detection(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_ASYNC)
        assert ns["fetchData"].is_async is True
        assert ns["syncMethod"].is_async is False

    def test_call_edges_extracted(self, parser):
        es = _edges(parser, ".swift", SWIFT_BASIC)
        assert ("add", "square") in es

    def test_async_call_edges(self, parser):
        es = _edges(parser, ".swift", SWIFT_ASYNC)
        callee_names = {callee for _, callee in es}
        assert "get" in callee_names or "parse" in callee_names

    def test_struct_parsed_as_class(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_STRUCT)
        assert "Point" in ns
        assert ns["Point"].type == "class"
        assert "distance" in ns
        assert ns["distance"].enclosing_class == "Point"

    def test_protocol_methods_extracted(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_PROTOCOL)
        assert "Drawable" in ns
        assert "draw" in ns
        assert "resize" in ns

    def test_top_level_functions(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_TOP_LEVEL)
        assert "greet" in ns
        assert ns["greet"].type == "function"
        assert ns["greet"].enclosing_class == ""

    def test_top_level_call_edges(self, parser):
        es = _edges(parser, ".swift", SWIFT_TOP_LEVEL)
        assert ("greet", "format") in es

    def test_structural_layer_is_precision(self, parser):
        ns = _nodes(parser, ".swift", SWIFT_BASIC)
        for n in ns.values():
            assert n.structural_layer == "precision"

    def test_module_derived_from_path(self, parser):
        nodes, _ = parser.parse_file("src/ui/Calculator.swift", SWIFT_BASIC)
        class_node = next(n for n in nodes if n.type == "class")
        assert "Calculator" in class_node.module

    def test_unknown_extension_ignored(self, parser):
        nodes, edges = parser.parse_file("file.swift_backup", SWIFT_BASIC)
        assert nodes == []
        assert edges == []


# ══ Kotlin ════════════════════════════════════════════════════════════════════

KOTLIN_BASIC = """
class Calculator {
    fun add(a: Int, b: Int): Int {
        val r = square(a)
        return r + b
    }
    fun square(x: Int): Int = x * x
}
"""

KOTLIN_SUSPEND = """
class Fetcher {
    suspend fun fetchData(url: String): Data {
        val result = network.get(url)
        val parsed = JSON.parse(result)
        return parsed
    }
    fun syncMethod(): String = ""
}
"""

KOTLIN_TOP_LEVEL = """
fun greet(name: String): String {
    return format(name)
}
fun format(s: String): String = s
"""

KOTLIN_OBJECT = """
object Registry {
    fun register(key: String, value: Any) {
        store(key, value)
    }
    private fun store(k: String, v: Any) {}
}
"""


class TestKotlinParser:
    def test_extension_registered(self, parser):
        assert ".kt" in parser.supported_extensions
        assert ".kts" in parser.supported_extensions

    def test_class_and_methods(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        assert "Calculator" in ns
        assert ns["Calculator"].type == "class"
        assert "add" in ns
        assert ns["add"].type == "method"
        assert "square" in ns

    def test_enclosing_class(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        assert ns["add"].enclosing_class == "Calculator"
        assert ns["square"].enclosing_class == "Calculator"

    def test_return_type_named(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        assert ns["add"].return_type == "Int"

    def test_return_type_single_expression(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        # single-expression fun square(x: Int): Int = x * x
        assert ns["square"].return_type == "Int"

    def test_parameter_names(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        assert ns["add"].parameter_names == ["a", "b"]
        assert ns["square"].parameter_names == ["x"]

    def test_suspend_is_async(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_SUSPEND)
        assert ns["fetchData"].is_async is True
        assert ns["syncMethod"].is_async is False

    def test_call_edges(self, parser):
        es = _edges(parser, ".kt", KOTLIN_BASIC)
        assert ("add", "square") in es

    def test_call_edges_method_on_object(self, parser):
        es = _edges(parser, ".kt", KOTLIN_SUSPEND)
        callee_names = {c for _, c in es}
        assert "get" in callee_names

    def test_top_level_functions(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_TOP_LEVEL)
        assert "greet" in ns
        assert ns["greet"].type == "function"
        assert ns["greet"].enclosing_class == ""
        assert "format" in ns

    def test_top_level_call_edges(self, parser):
        es = _edges(parser, ".kt", KOTLIN_TOP_LEVEL)
        assert ("greet", "format") in es

    def test_object_declaration(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_OBJECT)
        assert "Registry" in ns
        assert ns["Registry"].type == "class"
        assert "register" in ns
        assert ns["register"].enclosing_class == "Registry"

    def test_structural_layer(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        for n in ns.values():
            assert n.structural_layer == "precision"

    def test_kts_extension(self, parser):
        # .kts (Kotlin script) uses the same grammar
        nodes, _ = parser.parse_file("build.kts", KOTLIN_BASIC)
        assert len(nodes) > 0

    def test_start_end_lines(self, parser):
        ns = _nodes(parser, ".kt", KOTLIN_BASIC)
        assert ns["add"].start_line > 0
        assert ns["add"].end_line >= ns["add"].start_line


# ══ PHP ═══════════════════════════════════════════════════════════════════════

PHP_BASIC = """<?php
class Calculator {
    public function add(int $a, int $b): int {
        $r = $this->square($a);
        return $r + $b;
    }
    private function square(int $x): int { return $x * $x; }
}
"""

PHP_TOP_LEVEL = """<?php
function greet(string $name): string {
    return format($name);
}
function format(string $s): string { return $s; }
"""

PHP_STATIC_CALL = """<?php
function process(string $url): string {
    $r1 = JSON::decode($url);
    $r2 = strlen($url);
    return $r1;
}
"""

PHP_TRAIT = """<?php
trait Loggable {
    public function log(string $message): void {
        $this->write($message);
    }
    protected function write(string $msg): void {}
}
"""

PHP_INTERFACE = """<?php
interface Repository {
    public function findById(int $id): ?object;
    public function save(object $entity): void;
}
"""


class TestPhpParser:
    def test_extension_registered(self, parser):
        assert ".php" in parser.supported_extensions
        assert ".phtml" in parser.supported_extensions

    def test_class_and_methods(self, parser):
        ns = _nodes(parser, ".php", PHP_BASIC)
        assert "Calculator" in ns
        assert ns["Calculator"].type == "class"
        assert "add" in ns
        assert ns["add"].type == "method"
        assert "square" in ns

    def test_enclosing_class(self, parser):
        ns = _nodes(parser, ".php", PHP_BASIC)
        assert ns["add"].enclosing_class == "Calculator"
        assert ns["square"].enclosing_class == "Calculator"

    def test_return_type(self, parser):
        ns = _nodes(parser, ".php", PHP_BASIC)
        assert ns["add"].return_type == "int"
        assert ns["square"].return_type == "int"

    def test_parameter_names_strip_dollar(self, parser):
        # PHP params are "$a", "$b" — parser strips the "$"
        ns = _nodes(parser, ".php", PHP_BASIC)
        assert ns["add"].parameter_names == ["a", "b"]
        assert ns["square"].parameter_names == ["x"]

    def test_no_async(self, parser):
        ns = _nodes(parser, ".php", PHP_BASIC)
        for n in ns.values():
            assert n.is_async is False

    def test_instance_call_edges(self, parser):
        es = _edges(parser, ".php", PHP_BASIC)
        assert ("add", "square") in es

    def test_top_level_functions(self, parser):
        ns = _nodes(parser, ".php", PHP_TOP_LEVEL)
        assert "greet" in ns
        assert ns["greet"].type == "function"
        assert "format" in ns

    def test_top_level_call_edges(self, parser):
        es = _edges(parser, ".php", PHP_TOP_LEVEL)
        assert ("greet", "format") in es

    def test_static_call_callee_is_method_not_class(self, parser):
        # JSON::decode($url) → callee should be "decode", not "JSON"
        es = _edges(parser, ".php", PHP_STATIC_CALL)
        callee_names = {c for _, c in es}
        assert "decode" in callee_names
        assert "JSON" not in callee_names

    def test_builtin_function_call(self, parser):
        es = _edges(parser, ".php", PHP_STATIC_CALL)
        callee_names = {c for _, c in es}
        assert "strlen" in callee_names

    def test_trait_methods(self, parser):
        ns = _nodes(parser, ".php", PHP_TRAIT)
        assert "Loggable" in ns
        assert ns["Loggable"].type == "class"
        assert "log" in ns
        assert ns["log"].enclosing_class == "Loggable"

    def test_interface_methods(self, parser):
        ns = _nodes(parser, ".php", PHP_INTERFACE)
        assert "Repository" in ns
        assert "findById" in ns
        assert "save" in ns

    def test_structural_layer(self, parser):
        ns = _nodes(parser, ".php", PHP_BASIC)
        for n in ns.values():
            assert n.structural_layer == "precision"

    def test_start_end_lines(self, parser):
        ns = _nodes(parser, ".php", PHP_BASIC)
        assert ns["add"].start_line > 0
        assert ns["add"].end_line >= ns["add"].start_line

    def test_phtml_extension(self, parser):
        nodes, _ = parser.parse_file("view.phtml", PHP_BASIC)
        assert len(nodes) > 0
