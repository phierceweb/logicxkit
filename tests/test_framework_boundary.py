"""pw-foundation stops at the CLI boundary: ``pw_foundation.log`` in ``logicxkit/cli.py`` alone,
``pw_foundation.exceptions`` in command modules only, and below them nothing but
``pw_foundation.utils.io``. The library stays importable and quiet for anyone embedding it."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "logicxkit"
LOG_SITE = "cli.py"
COMMAND_ENTRY = ("cli.py", "logic/cli.py", "au/cli.py")
NOT_COMMAND = ("logic/_binary.py",)
ANYWHERE = ("pw_foundation.utils.io",)


def _pw_imports(source: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pw_foundation"):
            yield node.module, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("pw_foundation"):
                    yield alias.name, node.lineno


def _command_module(rel: str) -> bool:
    if rel in NOT_COMMAND:
        return False
    parts = rel.split("/")
    return rel in COMMAND_ENTRY or (len(parts) == 2 and parts[0] in ("logic", "au") and parts[1].startswith("_"))


def violations(rel: str, source: str) -> list[str]:
    """Every pw_foundation import in ``source``, a module at ``rel`` under the package, that the
    boundary forbids."""
    out = []
    for module, line in _pw_imports(source):
        if module in ANYWHERE:
            continue
        if module == "pw_foundation.log" and rel == LOG_SITE:
            continue
        if module == "pw_foundation.exceptions" and _command_module(rel):
            continue
        out.append(f"{rel}:{line}: {module}")
    return out


class FrameworkBoundaryTest(unittest.TestCase):
    def test_the_tree(self):
        found = []
        for path in sorted(SRC.rglob("*.py")):
            found += violations(path.relative_to(SRC).as_posix(), path.read_text())
        self.assertEqual([], found)

    def test_logging_only_at_the_entry_point(self):
        src = "from pw_foundation.log import get_logger\n"
        self.assertEqual([], violations("cli.py", src))
        self.assertEqual(["logic/cli.py:1: pw_foundation.log"], violations("logic/cli.py", src))
        self.assertEqual(["logic/services/stream/header.py:1: pw_foundation.log"],
                         violations("logic/services/stream/header.py", src))

    def test_exceptions_only_in_command_modules(self):
        src = "from pw_foundation.exceptions import PreconditionError\n"
        self.assertEqual([], violations("logic/_chains_cmd.py", src))
        self.assertEqual([], violations("au/_views.py", src))
        self.assertEqual(["logic/_binary.py:1: pw_foundation.exceptions"], violations("logic/_binary.py", src))
        self.assertEqual(["logic/services/mixer/chains.py:1: pw_foundation.exceptions"],
                         violations("logic/services/mixer/chains.py", src))
        self.assertEqual(["logic/orchestrators/apply.py:1: pw_foundation.exceptions"],
                         violations("logic/orchestrators/apply.py", src))

    def test_atomic_writes_anywhere_and_nothing_else_below(self):
        rel = "logic/services/mixer/donors.py"
        self.assertEqual([], violations(rel, "from pw_foundation.utils.io import atomic_write_bytes\n"))
        self.assertEqual([f"{rel}:2: pw_foundation.utils.env"],
                         violations(rel, "import os\nfrom pw_foundation.utils.env import resolve_int\n"))
        self.assertEqual([f"{rel}:1: pw_foundation"], violations(rel, "import pw_foundation\n"))
        self.assertEqual([f"{rel}:3: pw_foundation.log"],
                         violations(rel, "def f():\n    if True:\n        from pw_foundation.log import get_logger\n"))


if __name__ == "__main__":
    unittest.main()
