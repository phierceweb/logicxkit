"""Logic strip tests: EQ/Comp model round-trips + synthetic GAMETSPP build_strip."""

import unittest

from logicxkit.logic import (
    build_comp,
    build_eq,
    build_strip,
    decode_comp,
    decode_eq,
    decode_strip,
    find_blocks,
    identify_plugin,
    read_block_floats,
    template_path_for,
)


from _fixtures import block as _block


class EqTest(unittest.TestCase):
    def test_build_decode_roundtrip(self):
        spec = {"hpf": {"freq": 30}, "peak1": {"freq": 100, "gain": 3.0, "q": 1.0},
                "high_shelf": {"freq": 10000, "gain": 2.0, "q": 0.71}}
        got = decode_eq(build_eq(spec))
        self.assertEqual(got["hpf"]["freq"], 30.0)
        self.assertEqual(got["peak1"], {"freq": 100.0, "gain": 3.0, "q": 1.0})
        self.assertEqual(got["high_shelf"]["gain"], 2.0)

    def test_unknown_band_raises(self):
        with self.assertRaises(ValueError):
            build_eq({"wobble": {"freq": 100}})


class CompTest(unittest.TestCase):
    def test_build_decode_roundtrip(self):
        spec = {"circuit": "StudioFET", "threshold": -20, "ratio": 3,
                "attack": 15, "release": 75, "gain": 4, "knee": 0.5}
        got = decode_comp(build_comp(spec))
        self.assertEqual(got["circuit"], "StudioFET")
        self.assertEqual(got["threshold"], -20.0)
        self.assertEqual(got["ratio"], 3.0)

    def test_bad_circuit_raises(self):
        with self.assertRaises(ValueError):
            build_comp({"circuit": "Imaginary", "threshold": -20, "ratio": 2,
                        "attack": 10, "release": 50})


class BuildStripTest(unittest.TestCase):
    def setUp(self):
        # gap must exceed identify_plugin's 220-byte context window so the Compressor
        # block doesn't see the earlier "ChanEQ" label (real .cst files space blocks far apart)
        self.template = _block("ChanEQ", 33) + b"\x00" * 300 + _block("Compressor", 14)

    def test_synthetic_template_has_two_blocks(self):
        blocks = find_blocks(self.template)
        self.assertEqual(len(blocks), 2)
        kinds = [identify_plugin(self.template, idx) for idx, _, _ in blocks]
        self.assertEqual(kinds, ["Channel EQ", "Compressor"])

    def test_build_strip_patches_eq_and_comp(self):
        preset = {"eq": {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}},
                  "comp": {"circuit": "StudioFET", "threshold": -20, "ratio": 3,
                           "attack": 15, "release": 75}}
        data = build_strip(self.template, preset)
        eq = comp = None
        for idx, _s, n in find_blocks(data):
            plug = identify_plugin(data, idx)
            if plug == "Channel EQ":
                eq = decode_eq(read_block_floats(data, idx, n))
            elif plug == "Compressor":
                comp = decode_comp(read_block_floats(data, idx, n))
        self.assertEqual(eq["peak1"]["gain"], 3.0)
        self.assertEqual(comp["circuit"], "StudioFET")
        self.assertEqual(comp["threshold"], -20.0)

    def test_missing_block_raises(self):
        with self.assertRaises(RuntimeError):
            build_strip(_block("ChanEQ", 33), {"comp": {"circuit": "FET", "threshold": -20,
                                                        "ratio": 2, "attack": 10, "release": 50}})

    def test_decode_strip_returns_spec_fragment(self):
        preset = {"eq": {"peak2": {"freq": 250, "gain": -4.0, "q": 2.0}},
                  "comp": {"circuit": "Platinum", "threshold": -18, "ratio": 3,
                           "attack": 12, "release": 90}}
        spec = decode_strip(build_strip(self.template, preset))
        self.assertEqual(spec["eq"]["peak2"], {"freq": 250.0, "gain": -4.0, "q": 2.0})
        self.assertEqual(spec["comp"]["threshold"], -18.0)
        self.assertEqual(decode_strip(b"no blocks here"), {})


class DoubleBlockTest(unittest.TestCase):
    """A Logic re-saved strip writes each EQ/Comp slot as two consecutive same-size
    GAMETSPP blocks; only the first carries the plugin-name label (the copy reads as
    'Unknown' because the label is outside identify_plugin's 220-byte window). A robust
    build must patch BOTH copies, else Logic may load the stale one."""

    def setUp(self):
        # 250-byte gaps push each copy's context past the 220-byte name window, so the
        # paired copy identifies as "Unknown" exactly like a real re-saved strip.
        self.template = (
            _block("ChanEQ", 33) + b"\x00" * 250 + _block("", 33)          # EQ + paired copy
            + b"\x00" * 250 + _block("Enveloper", 39)                        # unrelated, different size
            + b"\x00" * 250 + _block("Compressor", 14) + b"\x00" * 250 + _block("", 14)  # Comp + copy
        )

    def test_template_copies_are_unknown(self):
        kinds = [identify_plugin(self.template, idx) for idx, _, _ in find_blocks(self.template)]
        self.assertEqual(kinds, ["Channel EQ", "Unknown", "Enveloper", "Compressor", "Unknown"])

    def test_both_copies_patched(self):
        preset = {"eq": {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}},
                  "comp": {"circuit": "ClassicVCA", "threshold": -22, "ratio": 5,
                           "attack": 8, "release": 45}}
        data = build_strip(self.template, preset)
        eqs, comps = [], []
        for idx, _s, n in find_blocks(data):
            floats = read_block_floats(data, idx, n)
            if n == 33:
                eqs.append(decode_eq(floats))
            elif n == 14:
                comps.append(decode_comp(floats))
        self.assertEqual(len(eqs), 2)
        self.assertEqual(len(comps), 2)
        for eq in eqs:
            self.assertEqual(eq["peak1"]["gain"], 3.0)
        for comp in comps:
            self.assertEqual(comp["circuit"], "ClassicVCA")
            self.assertEqual(comp["threshold"], -22.0)


class TemplateResolveTest(unittest.TestCase):
    def test_per_preset_overrides_global(self):
        self.assertEqual(
            str(template_path_for({"template": "/g.cst"}, {"template": "/p.cst"})), "/p.cst")

    def test_falls_back_to_global(self):
        self.assertEqual(str(template_path_for({"template": "/g.cst"}, {})), "/g.cst")

    def test_missing_both_raises(self):
        with self.assertRaises(ValueError):
            template_path_for({}, {})


if __name__ == "__main__":
    unittest.main()
