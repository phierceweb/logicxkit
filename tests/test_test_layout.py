"""`python tests/.../test_x.py` must run all of that file or none of it.

`unittest.main()` runs where it appears, so a test class defined below it is never collected —
the file reports ``OK`` having skipped the rest. pytest collects by module and sees everything,
which is what makes the gap invisible: the suite stays green while a direct run silently covers
a fraction of the file. 26 files had drifted this way before this gate existed.
"""

import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _files():
    return sorted(TESTS.rglob("test_*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), str(path))


def _main_block(tree: ast.Module) -> ast.If | None:
    """The top-level ``if __name__ == "__main__":`` guard, if the file has one."""
    for node in tree.body:
        if isinstance(node, ast.If) and "__name__" in ast.dump(node.test):
            return node
    return None


def _needs_on_functions(tree: ast.Module) -> list[str]:
    """Top-level functions decorated with a ``needs(...)`` call (`_goldens.needs`, `_data.needs`)."""
    def is_needs(d):
        f = d.func if isinstance(d, ast.Call) else None
        return (isinstance(f, ast.Name) and f.id == "needs") or (isinstance(f, ast.Attribute) and f.attr == "needs")
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any(map(is_needs, n.decorator_list))]


class MainBlockTest(unittest.TestCase):
    def test_no_test_is_defined_after_the_main_block(self):
        late = {}
        for path in _files():
            tree = _tree(path)
            block = _main_block(tree)
            if block is None:
                continue
            after = [n.name for n in tree.body
                     if n.lineno > block.lineno
                     and (isinstance(n, ast.ClassDef)
                          or (isinstance(n, ast.FunctionDef) and n.name.startswith("test")))]
            if after:
                late[str(path.relative_to(TESTS))] = after
        self.assertEqual(late, {}, "unittest.main() runs where it appears, so these are never "
                                   "collected by a direct run: move the block to the end of the file")

    def test_a_file_of_bare_pytest_functions_carries_no_unittest_main(self):
        """`unittest.main()` cannot collect a plain ``def test_x()``, so a file holding one can
        never run itself completely — the guard has to go rather than move."""
        wrong = []
        for path in _files():
            tree = _tree(path)
            bare = [n.name for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]
            if bare and _main_block(tree) is not None:
                wrong.append(f"{path.relative_to(TESTS)}: {len(bare)} bare function(s)")
        self.assertEqual(wrong, [])

    def test_a_skip_unless_present_decorator_sits_on_a_class(self):
        """`needs(...)` on a helper function guards nothing: the class below it runs, and errors,
        on a machine without the files."""
        wrong = [f"{path.relative_to(TESTS)}: {name}" for path in _files() for name in _needs_on_functions(_tree(path))]
        self.assertEqual(wrong, [])

    def test_the_gate_reads_every_test_file_and_finds_the_shapes_it_screens_for(self):
        """A gate that silently matched nothing would pass for the wrong reason."""
        files = _files()
        self.assertGreater(len(files), 100, "the sweep found almost no test files")
        self.assertGreater(sum(_main_block(_tree(p)) is not None for p in files), 100,
                           "no __main__ block was recognised: the detector, not the tree, is wrong")


class DetectorTest(unittest.TestCase):
    """The detector must fail on the shape it exists to catch, or it proves nothing."""

    def _late(self, source: str) -> list[str]:
        tree = ast.parse(source)
        block = _main_block(tree)
        return [] if block is None else [n.name for n in tree.body if n.lineno > block.lineno
                                         and isinstance(n, ast.ClassDef)]

    def test_a_class_below_the_block_is_caught_and_one_above_it_is_not(self):
        block = 'if __name__ == "__main__":\n    unittest.main()\n'
        klass = "class LateTest(unittest.TestCase):\n    pass\n"
        self.assertEqual(self._late(block + klass), ["LateTest"])
        self.assertEqual(self._late(klass + block), [])
        self.assertEqual(self._late(klass), [])

    def test_needs_on_a_helper_is_caught_and_on_a_class_is_not(self):
        helper = "@_goldens.needs('k')\ndef _channel(d):\n    return d\n"
        klass = "@needs('logic')\nclass T(unittest.TestCase):\n    pass\n"
        self.assertEqual(_needs_on_functions(ast.parse(helper + klass)), ["_channel"])
        self.assertEqual(_needs_on_functions(ast.parse(klass)), [])


if __name__ == "__main__":
    unittest.main()
