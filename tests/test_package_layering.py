"""The subpackage import graph stays a DAG, and logicx stays a leaf.

`au` and `logic` were mutually dependent until the .logicx container primitives moved into
`logicxkit.logicx`. Nothing mechanical catches a relapse — pf_core.guards' layering rule only
inspects `app/` trees — so it is caught here.
"""

import ast
import os
import unittest

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src", "logicxkit"))
_PKGS = ("au", "logic", "utils", "logicx")


def _package_of(path: str) -> str:
    head = os.path.relpath(path, _SRC).split(os.sep)[0]
    return head if head in _PKGS else "(root)"


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
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    mods = [node.module]
                else:
                    continue
                for mod in mods:
                    parts = mod.split(".")
                    if parts[0] != "logicxkit":
                        continue
                    tgt = parts[1] if len(parts) > 1 else "(root)"
                    if tgt != src:
                        site = f"{os.path.relpath(path, _SRC)}:{node.lineno}"
                        out.setdefault((src, tgt), []).append(site)
    return out


def _cycles(edges) -> list[list[str]]:
    graph: dict[str, set[str]] = {}
    for a, b in edges:
        graph.setdefault(a, set()).add(b)
    found: list[list[str]] = []

    def walk(node, path, seen):
        for nxt in graph.get(node, ()):
            if nxt in path:
                found.append(path[path.index(nxt):] + [nxt])
            elif nxt not in seen:
                seen.add(nxt)
                walk(nxt, path + [nxt], seen)

    for node in list(graph):
        walk(node, [node], set())
    return found


class PackageLayeringTest(unittest.TestCase):
    def test_graph_is_non_empty(self):
        self.assertTrue(_edges(), f"no cross-package imports found under {_SRC}")

    def test_no_import_cycles(self):
        edges = _edges()
        cycles = {" -> ".join(c) for c in _cycles(edges)}
        self.assertEqual(cycles, set(), f"import cycle(s); edges: {sorted(edges)}")

    def test_au_does_not_import_logic(self):
        sites = _edges().get(("au", "logic"), [])
        self.assertEqual(sites, [], "au must read projects through logicxkit.logicx")

    def test_logicx_is_a_leaf(self):
        out = {b: s for (a, b), s in _edges().items() if a == "logicx"}
        self.assertEqual(out, {}, "logicxkit.logicx must not import a sibling package")


if __name__ == "__main__":
    unittest.main()
