"""Logic's Library saves of one strip, one change per save, and one from a summing stack
(2026-09-16): what a patch bundle carries and what the reader reads from it."""

import unittest
import _goldens
from logicxkit.logic.services.mixer.patch import read_patch

KEYS = ("patch-base-logic", "patch-fader-logic", "patch-insert-logic", "patch-send-logic", "patch-stack-logic")


@_goldens.needs(*KEYS)
class PatchSetTest(unittest.TestCase):
    def test_each_patch_reads_as_its_manifest_records(self):
        for key in KEYS:
            with self.subTest(key):
                p = read_patch(_goldens.path(key))
                facts = _goldens.entry(key)["facts"]
                self.assertEqual(len(p.channels), facts["channels"])
                root = p.channels[0]
                self.assertEqual((root.plugins, root.fader, root.pan_byte, root.strip),
                                 (facts["root"]["plugins"], facts["root"]["fader"], facts["root"]["pan"], facts["root"]["strip"]))

    def test_the_fader_step_is_the_channel_records_byte(self):
        base, fader = (read_patch(_goldens.path(k)).channels[0] for k in ("patch-base-logic", "patch-fader-logic"))
        self.assertEqual((base.fader, fader.fader), (90, 89))
        self.assertEqual(base.plugins, fader.plugins)

    def test_the_insert_adds_one_plugin_and_the_send_keeps_it(self):
        base, insert, send = (read_patch(_goldens.path(k)).channels[0] for k in ("patch-base-logic", "patch-insert-logic", "patch-send-logic"))
        self.assertEqual(insert.plugins, base.plugins + ["Adaptive Limiter"])
        self.assertEqual(send.plugins, insert.plugins)

    def test_a_stack_patch_carries_its_members(self):
        p = read_patch(_goldens.path("patch-stack-logic"))
        self.assertEqual(len(p.channels), 4)
        self.assertEqual(sorted(c.strip for c in p.channels), ["#Root.cst", "Audio1.cst", "Audio2.cst", "Audio3.cst"])
        self.assertEqual(sorted(_goldens.fact("patch-stack-logic", "files")),
                         sorted(c.strip for c in p.channels) + ["data.plist"])


if __name__ == "__main__":
    unittest.main()
