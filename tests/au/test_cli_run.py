"""The au CLI's offline subcommands run in-process: preset on a built .aupreset, strip over a
corpus bundle, tables."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _goldens

sys.path.insert(0, str(Path(__file__).parent))
from test_au_report import proc2_aupreset_bytes  # noqa: E402

from logicxkit.au.cli import main  # noqa: E402

PROC = "translate-proc"        # a Pro-C 2 state, decoded without the AU host


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = main([str(a) for a in argv])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
    return code, buf.getvalue()


@_goldens.needs(PROC)
class StripTest(unittest.TestCase):
    def test_strip_decodes_a_bundles_states_offline(self):
        code, text = run("strip", _goldens.path(PROC), "--no-host")
        self.assertEqual(code, 0, text)
        self.assertIn("FabF/FC2p", text)               # the name beside it needs the data root's tables
        code, text = run("strip", _goldens.path(PROC), "--no-host", "--json")
        self.assertEqual(code, 0, text)
        self.assertTrue(json.loads(text))


class PresetTest(unittest.TestCase):
    def test_preset_decodes_an_aupreset_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Example.aupreset"
            path.write_bytes(proc2_aupreset_bytes([(1, -6.0), (2, 0.4)]))
            code, text = run("preset", path, "--no-host")
            self.assertEqual(code, 0, text)
            self.assertIn("FC2p", text)
            code, text = run("preset", path, "--no-host", "--json", "--all")
            self.assertEqual(code, 0, text)
            out = json.loads(text)
            self.assertEqual(out["plugin"]["subtype"], "FC2p")
            self.assertTrue(out["params"])


class MissingPathTest(unittest.TestCase):
    """A path that is not there is refused in a sentence, through the top-level wrapper."""

    def wrapped(self, *argv) -> tuple[int, str]:
        from logicxkit.cli import main as top
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = top(["au", *map(str, argv)])
        return code, buf.getvalue()

    def test_preset_and_strip_name_the_missing_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            for argv in (("preset", Path(tmp) / "gone.aupreset"), ("preset", tmp),
                         ("strip", Path(tmp) / "gone.cst")):
                with self.subTest(argv[0], path=argv[1]):
                    code, text = self.wrapped(*argv, "--no-host")
                    self.assertEqual(code, 1, text)
                    self.assertIn(f"no such file: {argv[1]}", text)
                    self.assertNotIn("Errno", text)


class TablesTest(unittest.TestCase):
    def test_tables_lists_what_is_checked_in(self):
        code, text = run("tables")
        self.assertEqual(code, 0, text)
        self.assertTrue(text.strip())


if __name__ == "__main__":
    unittest.main()
