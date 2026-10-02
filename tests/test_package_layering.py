"""The subpackage import graph stays a DAG, and logicx stays a leaf; pf_core.guards' layering
rule inspects only `app/` trees, so it is enforced here."""

import ast
import os
import unittest

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src", "logicxkit"))
_PKGS = ("au", "logic", "utils", "logicx")


def _package_of(path: str) -> str:
    head = os.path.relpath(path, _SRC).split(os.sep)[0]
    return head if head in _PKGS else "(root)"


def _modules(path: str, node: ast.Import | ast.ImportFrom) -> list[str]:
    """The absolute modules an import names, relative ``from`` imports resolved."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if node.level:
        rel = os.path.relpath(os.path.dirname(path), _SRC)
        package = ["logicxkit"] + ([] if rel == "." else rel.split(os.sep))
        base = ".".join(package[:len(package) - (node.level - 1)])
    else:
        base = ""
    module = ".".join(p for p in (base, node.module) if p)
    return [module] if node.module else [f"{module}.{a.name}" for a in node.names]


def _edges() -> dict[tuple[str, str], list[str]]:
    """(importer, imported) -> call sites, for cross-subpackage imports only."""
    out: dict[tuple[str, str], list[str]] = {}
    for d, _, files in os.walk(_SRC):
        if "__pycache__" in d:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(d, fn)
            src = _package_of(path)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for mod in _modules(path, node):
                    parts = mod.split(".")
                    if parts[0] != "logicxkit":
                        continue
                    tgt = parts[1] if len(parts) > 1 else "(root)"
                    if tgt != src:
                        site = f"{os.path.relpath(path, _SRC)}:{node.lineno}"
                        out.setdefault((src, tgt), []).append(site)
    return out


def _module_edges() -> dict[str, set[str]]:
    """module -> the package's modules it imports. An import inside a function is an edge too;
    one under `if TYPE_CHECKING:` is not."""
    names = {}
    for d, _, files in os.walk(_SRC):
        for fn in files:
            if fn.endswith(".py"):
                path = os.path.join(d, fn)
                rel = os.path.relpath(path, os.path.dirname(_SRC))[:-3].replace(os.sep, ".")
                names[rel[:-9] if rel.endswith(".__init__") else rel] = path
    graph: dict[str, set[str]] = {}
    for name, path in names.items():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        typing_only = {id(n) for block in ast.walk(tree)
                       if isinstance(block, ast.If) and "TYPE_CHECKING" in ast.unparse(block.test)
                       for n in ast.walk(block)}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in typing_only:
                continue
            for mod in _modules(path, node):
                named = ([f"{mod}.{a.name}" for a in node.names]
                         if isinstance(node, ast.ImportFrom) else [])
                for target in [mod, *named]:
                    if target in names and target != name:
                        graph.setdefault(name, set()).add(target)
    return graph


def _knots(graph: dict[str, set[str]]) -> list[list[str]]:
    """Every group of nodes that reach each other (strongly connected components of two or more)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    out: list[list[str]] = []

    def visit(v: str) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            group = stack[stack.index(v):]
            del stack[stack.index(v):]
            if len(group) > 1:
                out.append(sorted(group))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return sorted(out)


def _package_graph(edges) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for a, b in edges:
        graph.setdefault(a, set()).add(b)
    return graph


class PackageLayeringTest(unittest.TestCase):
    def test_graph_is_non_empty(self):
        self.assertTrue(_edges(), f"no cross-package imports found under {_SRC}")

    def test_no_import_cycles(self):
        edges = _edges()
        self.assertEqual(_knots(_package_graph(edges)), [],
                         f"import cycle(s); edges: {sorted(edges)}")

    def test_no_module_imports_a_module_that_imports_it_back(self):
        """A cycle broken by a function-level import fails at call time, in whichever command
        first takes that path — so those imports count here."""
        knots = [" <-> ".join(m.removeprefix("logicxkit.") for m in group)
                 for group in _knots(_module_edges())]
        self.assertEqual(knots, [], "modules that import each other")

    def test_au_does_not_import_logic(self):
        sites = _edges().get(("au", "logic"), [])
        self.assertEqual(sites, [], "au must read projects through logicxkit.logicx")

    def test_logicx_is_a_leaf(self):
        out = {b: s for (a, b), s in _edges().items() if a == "logicx"}
        self.assertEqual(out, {}, "logicxkit.logicx must not import a sibling package")


class RelativeImportTest(unittest.TestCase):
    def test_a_relative_import_across_packages_is_an_edge(self):
        import sys
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            for sub in ("au", "logic"):
                os.makedirs(os.path.join(tmp, sub))
            with open(os.path.join(tmp, "au", "reader.py"), "w") as fh:
                fh.write("from ..logic import services\nfrom .. import logic\n")
            with mock.patch.object(sys.modules[__name__], "_SRC", tmp):
                self.assertEqual(len(_edges().get(("au", "logic"), [])), 2)


class ModuleCycleTest(unittest.TestCase):
    def _knots_of(self, sources: dict[str, str]) -> list[list[str]]:
        import sys
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "logicxkit")
            os.makedirs(os.path.join(src, "logic"))
            for name, text in sources.items():
                with open(os.path.join(src, "logic", f"{name}.py"), "w") as fh:
                    fh.write(text)
            with mock.patch.object(sys.modules[__name__], "_SRC", src):
                return _knots(_module_edges())

    def test_a_function_level_import_closes_a_cycle(self):
        knots = self._knots_of({"a": "from .b import x\n", "b": "def f():\n    from .a import y\n"})
        self.assertEqual(knots, [["logicxkit.logic.a", "logicxkit.logic.b"]])

    def test_a_type_checking_import_does_not(self):
        typed = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .a import y\n"
        knots = self._knots_of({"a": "from .b import x\n", "b": typed})
        self.assertEqual(knots, [])

    def test_a_cycle_reached_through_a_visited_module_is_found(self):
        knots = self._knots_of({"a": "from . import b, c\n", "b": "from . import d\n",
                                "c": "from . import d\n", "d": "from . import c\n"})
        self.assertEqual(knots, [["logicxkit.logic.c", "logicxkit.logic.d"]])


if __name__ == "__main__":
    unittest.main()
