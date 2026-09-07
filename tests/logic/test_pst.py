"""Plugin-preset (.pst) build + Limiter parameter model.

A `.pst` is exactly ONE GAMETSPP chunk at offset 0 — no OCuA header, no routing, no sends.
That makes it the safe way to deliver settings to a channel: loading a full `.cst` replaces
the channel's routing and sends, loading a `.pst` touches only the one plugin.

Limiter float layout (index == Apple's parameterID, from Limiter.plist):
  [1] Gain dB · [2] Lookahead ms · [3] Softknee · [4] Release ms · [5] Output Level dB
  [6] Gain Reduction · [7] True Peak Detection · [8] Mode (0 Legacy, 1 Precision)
"""

import unittest

from _fixtures import chunk
from logicxkit.logic import build_limiter, build_pst, decode_limiter, find_blocks, read_block_floats


class LimiterModelTest(unittest.TestCase):
    def test_roundtrip(self):
        spec = {"gain": 0, "lookahead": 0, "release": 250, "ceiling": -1.0,
                "true_peak": 0, "mode": "Legacy"}
        got = decode_limiter(build_limiter(spec))
        self.assertEqual(got["ceiling"], -1.0)
        self.assertEqual(got["lookahead"], 0.0)
        self.assertEqual(got["mode"], "Legacy")

    def test_factory_default_decodes(self):
        """Logic's own #default.pst values, as read off disk."""
        got = decode_limiter([0.0, 0.0, 5.0, 1.0, 250.0, 0.0, 0.0, 1.0, 1.0])
        self.assertEqual(got["lookahead"], 5.0)
        self.assertEqual(got["release"], 250.0)
        self.assertEqual(got["mode"], "Precision")
        self.assertEqual(got["true_peak"], 1)

    def test_indices_match_apple_parameter_ids(self):
        vals = build_limiter({"gain": 3, "lookahead": 7, "release": 470,
                              "ceiling": -0.3, "softknee": 1, "true_peak": 1,
                              "mode": "Precision"})
        self.assertEqual(vals[1], 3.0)
        self.assertEqual(vals[2], 7.0)
        self.assertEqual(vals[3], 1.0)
        self.assertEqual(vals[4], 470.0)
        self.assertEqual(vals[5], -0.3)
        self.assertEqual(vals[8], 1.0)

    def test_bad_mode_raises(self):
        with self.assertRaises(ValueError):
            build_limiter({"mode": "Turbo"})


class BuildPstTest(unittest.TestCase):
    def setUp(self):
        self.template = chunk(199, [0.0] * 9)  # a Limiter #default-shaped preset

    def test_patches_values_and_keeps_length(self):
        out = build_pst(self.template, build_limiter({"ceiling": -1.0, "lookahead": 0}))
        self.assertEqual(len(out), len(self.template))
        idx, tid, n = find_blocks(out)[0]
        self.assertEqual((tid, n), (199, 9))
        self.assertEqual(read_block_floats(out, idx, n)[5], -1.0)

    def test_does_not_write_past_the_template_block(self):
        """A 13-value model must not overflow a 9-float factory preset."""
        out = build_pst(self.template, [1.0] * 13)
        self.assertEqual(len(out), len(self.template))
        self.assertEqual(read_block_floats(out, *find_blocks(out)[0][::2]), [1.0] * 9)

    def test_rejects_template_with_no_chunk(self):
        with self.assertRaises(ValueError):
            build_pst(b"not a preset", [0.0])


class BuildStripLimiterTest(unittest.TestCase):
    """A strip carrying a Limiter (e.g. a tracking master) must get its values patched too."""

    def test_patches_limiter_block(self):
        from _fixtures import block
        from logicxkit.logic import build_strip, decode_limiter, find_blocks, read_block_floats
        template = block("Limiter", 13)
        out = build_strip(template, {"limiter": {"ceiling": -1.0, "lookahead": 0,
                                                 "mode": "Legacy", "true_peak": 0}})
        idx, _t, n = find_blocks(out)[0]
        got = decode_limiter(read_block_floats(out, idx, n))
        self.assertEqual(got["ceiling"], -1.0)
        self.assertEqual(got["mode"], "Legacy")

    def test_missing_limiter_block_raises(self):
        from _fixtures import block
        from logicxkit.logic import build_strip
        with self.assertRaises(RuntimeError):
            build_strip(block("ChanEQ", 33), {"limiter": {"ceiling": -1.0}})
