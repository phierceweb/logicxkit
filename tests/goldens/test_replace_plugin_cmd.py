"""`replace-plugin` through its command with no flags at all — the path every other test skipped —
and with `--keep-automation`. Skips without the public corpus."""

import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import _goldens
from logicxkit.logic._add_plugin_cmd import cmd_replace_plugin
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED


def _replace(key: str, out: str, **more):
    args = Namespace(project=str(_goldens.path(key)), out=out, at=1, plugin="Noise Gate", channel=["Audio 2"], stack=None, bypass=False,
                     side_chain=None, translate=False, set=None, keep_automation=False, library=str(PACKAGED / "donors"), force=False)
    for k, v in more.items():
        setattr(args, k, v)
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        code = cmd_replace_plugin(args)
    return code, text.getvalue()


@_goldens.needs("autoset-ours")
class PlainReplaceTest(unittest.TestCase):
    def test_no_flags_replaces_and_drops_the_lanes_with_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _replace("autoset-ours", tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("slot 1: Noise Gate in, key 3 out", out)
            self.assertIn("lane(s) of the old plug-in dropped", out)
            names = [r.name for r, _p in slot_payloads(project_data(next(Path(tmp).glob("*.logicx")))) if r.channel == "Audio 2"]
            self.assertEqual(names[0], "Noise Gate")

    def test_keep_automation_keeps_the_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _replace("autoset-ours", tmp, keep_automation=True)
            self.assertEqual(code, 0, out)
            self.assertIn("lane(s) kept on slot 1 as they were", out)


@_goldens.needs("snap-ours")
class SideChainDroppedTest(unittest.TestCase):
    def test_a_plain_replace_names_the_side_chain_it_drops(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _replace("snap-ours", tmp, at=2, plugin="Compressor")
            self.assertEqual(code, 0, out)
            self.assertIn("side chain Bus 1 dropped with the old plug-in", out)


if __name__ == "__main__":
    unittest.main()
