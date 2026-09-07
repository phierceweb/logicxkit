"""Parameter values sourced from a saved strip rather than derived from JSON.

A curve derived from a JSON description is a guess: it rounds off the surgical cuts and wide
bands a hand-dialled strip actually carries, so the built chain sounds different from the strip
it claims to reproduce. A chain naming a `strip` takes that strip's parameter floats verbatim.
"""

import struct
import unittest

from _fixtures import chunk

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 4) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def ref_payload(name: str) -> bytes:
    return b"\x00" * 16 + name.encode().ljust(64, b"\x00") + b"Drums".ljust(64, b"\x00")


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


class StripSourcedValuesTest(unittest.TestCase):
    """Parameter values come from a saved strip when the config names one.

    A derived curve flattens what the strip actually holds, so a named strip is copied whole
    rather than re-derived.
    """

    def _cst(self, tmp, name, *chunks):
        """A .cst holding one slot record per chunk, keyed in chain order."""
        from pathlib import Path
        body = b"".join(
            rec(b"UCuA", 0, 4 + i, b"\x00" * 14 + b"S.pst".ljust(62, b"\x00") + c)
            for i, c in enumerate(chunks))
        path = Path(tmp) / name
        path.write_bytes(body)
        return path

    def setUp(self):
        self.eq_donor = rec(b"UCuA", 90, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                            + chunk(236, [0.0] * 52))
        self.comp_donor = rec(b"UCuA", 91, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                              + chunk(154, [0.0] * 31))
        self.data = proj(rec(b"OCuA", 0, 0xFFFF, b"C" * 225),
                         rec(b"UCuA", 0, 10, ref_payload("Kick In.cst")))

    def test_reads_a_strips_chain_in_slot_order(self):
        import tempfile
        from logicxkit.logic import strip_chain
        with tempfile.TemporaryDirectory() as tmp:
            path = self._cst(tmp, "K.cst", chunk(183, [1.0] * 10), chunk(236, [2.0] * 52),
                             chunk(154, [3.0] * 31))
            self.assertEqual([t for t, _f in strip_chain(path)], [183, 236, 154])

    def test_params_are_keyed_by_plugin_type(self):
        import tempfile
        from logicxkit.logic import strip_params
        with tempfile.TemporaryDirectory() as tmp:
            path = self._cst(tmp, "K.cst", chunk(236, [7.0] * 52))
            self.assertEqual(strip_params(path)[236], [7.0] * 52)

    def test_every_float_is_copied_not_just_the_user_prefix(self):
        """build_eq only emits 33 of the 52; a strip supplies all of them."""
        import tempfile
        from logicxkit.logic import chain_plan
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(236, [float(i) for i in range(52)]))
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "Kick In", "strip": "K.cst"}}}
            plan, report = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor)
            floats, limit = plan[0][0][2], plan[0][0][3]
            self.assertEqual(limit, 52, "writes the whole array, not the 33-float prefix")
            self.assertEqual(floats[51], 51.0)
            self.assertEqual(report["shape_mismatch"], [])

    def test_a_strip_without_a_compressor_yields_no_compressor_slot(self):
        import tempfile
        from logicxkit.logic import chain_plan
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "R.cst", chunk(236, [1.0] * 52))
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "Room", "strip": "R.cst"}}}
            plan, _ = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor)
            self.assertEqual([s[6] for s in plan[0]], [236])

    def test_dropping_a_plugin_the_strip_has_is_reported(self):
        """The config silently lacked Kick Out's polarity-invert Gain; this catches that."""
        import tempfile
        from logicxkit.logic import chain_plan
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(183, [1.0] * 10), chunk(236, [2.0] * 52))
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "K", "strip": "K.cst"}}}
            _plan, report = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor)
            self.assertTrue(report["shape_mismatch"], "Gain in the strip, absent from the plan")

    def test_a_shorter_source_chunk_is_reported_not_silently_partial(self):
        import tempfile
        from logicxkit.logic import chain_plan
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "G.cst", chunk(236, [1.0] * 51))   # the real guitar bus strip has 51
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "G", "strip": "G.cst"}}}
            _plan, report = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor)
            self.assertTrue(any("51 floats" in m for m in report["shape_mismatch"]))

    def test_strip_plus_a_json_block_is_refused_as_ambiguous(self):
        import json
        import tempfile
        from pathlib import Path
        from logicxkit.logic import load_chain_config
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            cfg.write_text(json.dumps({"chains": {"Kick In.cst": {
                "strip": "K.cst", "eq": {"hpf": {"freq": 30}}}}}))
            with self.assertRaises(ValueError):
                load_chain_config(cfg)

    def test_json_values_still_work_where_no_strip_exists(self):
        from logicxkit.logic import chain_plan
        cfg = {"chains": {"Kick In.cst": {"label": "Vox", "eq": {"hpf": {"freq": 90}}}}}
        plan, _ = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor)
        self.assertEqual(plan[0][0][3], 33, "derived values keep the user-param limit")

    def test_strip_path_resolves_against_the_root(self):
        from pathlib import Path
        from logicxkit.logic import strip_path
        got = strip_path({"strip_root": "/a/b"}, {"strip": "c/d.cst"})
        self.assertEqual(got, Path("/a/b/c/d.cst"))

    def test_an_absolute_strip_ignores_the_root(self):
        from pathlib import Path
        from logicxkit.logic import strip_path
        got = strip_path({"strip_root": "/a/b"}, {"strip": "/x/y.cst"})
        self.assertEqual(got, Path("/x/y.cst"))

    def test_the_enveloper_takes_its_values_from_the_strip_not_the_donor(self):
        """A v3 project's Enveloper donor is a FACTORY instance; taking it verbatim shipped
        Apple's defaults where the saved strip holds a dialled setting."""
        import tempfile
        from logicxkit.logic import chain_plan
        factory = rec(b"UCuA", 92, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                      + chunk(157, [0.0, 11.0, 18.0, 22.0, 0.0, -100.0, 20.0, 0.0]))
        dialled = [0.0, 7.0, 41.0, 88.0, 0.0, -23.0, 14.0, 2.0]
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(236, [1.0] * 52), chunk(157, dialled),
                      chunk(154, [2.0] * 31))
            cfg = {"strip_root": tmp, "chains": {"Kick In.cst": {
                "label": "K", "strip": "K.cst", "env": True, "bypass": ["env"]}}}
            plan, report = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor,
                                      env_donor=factory)
            env = next(s for s in plan[0] if s[6] == 157)
            self.assertEqual(env[2], dialled,
                             "the strip's values, not the donor's factory defaults")
            self.assertTrue(env[7], "still bypassed")
            self.assertEqual(report["shape_mismatch"], [])

    def test_a_pre_slot_present_in_the_strip_takes_its_values(self):
        import tempfile
        from logicxkit.logic import chain_plan
        gain_donor = rec(b"UCuA", 93, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                         + chunk(183, [0.0] * 10))
        invert = [0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "KO.cst", chunk(183, invert), chunk(236, [1.0] * 52))
            cfg = {"strip_root": tmp, "chains": {"Kick In.cst": {
                "label": "KO", "strip": "KO.cst", "pre": ["gain_invert"]}}}
            plan, _ = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor,
                                 extra={"gain_invert": (gain_donor, 183)})
            self.assertEqual(plan[0][0][2], invert, "polarity invert, not the donor's zeros")

    def test_an_extra_absent_from_the_strip_is_still_copied_verbatim(self):
        """FX-return reverbs have no strip; they must keep the donor's dialled values."""
        import tempfile
        from logicxkit.logic import chain_plan
        verb = rec(b"UCuA", 94, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                   + chunk(287, [3.0] * 40))
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(236, [1.0] * 52))
            cfg = {"strip_root": tmp, "chains": {"Kick In.cst": {
                "label": "K", "strip": "K.cst", "post": ["verb"]}}}
            plan, _ = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor,
                                 extra={"verb": (verb, 287)})
            post = next(s for s in plan[0] if s[6] == 287)
            self.assertIsNone(post[2], "no strip values for it — donor kept as-is")


class VerifyStripValuesTest(unittest.TestCase):
    """Read a WRITTEN project back and check every strip-sourced float against its strip.

    Slot counts and structural validation both passed while three projects carried a factory
    Enveloper instead of the strip's, so success is measured by reading the result, not the report.
    """

    def _cst(self, tmp, name, *chunks):
        from pathlib import Path
        body = b"".join(
            rec(b"UCuA", 0, 4 + i, b"\x00" * 14 + b"S.pst".ljust(62, b"\x00") + c)
            for i, c in enumerate(chunks))
        path = Path(tmp) / name
        path.write_bytes(body)
        return path

    def _built(self, tmp, eq_values):
        """A project whose one channel carries an EQ slot holding ``eq_values``."""
        return proj(
            rec(b"OCuA", 0, 0xFFFF, b"C" * 225),
            rec(b"UCuA", 0, 4, b"\x00" * 14 + b"S.pst".ljust(62, b"\x00")
                + chunk(236, eq_values)),
            rec(b"UCuA", 0, 10, ref_payload("Kick In.cst")))

    def test_matching_values_report_nothing(self):
        import tempfile
        from logicxkit.logic import verify_strip_values
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(236, [float(i) for i in range(52)]))
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "K", "strip": "K.cst"}}}
            data = self._built(tmp, [float(i) for i in range(52)])
            self.assertEqual(verify_strip_values(data, cfg), [])

    def test_a_single_wrong_float_is_caught(self):
        import tempfile
        from logicxkit.logic import verify_strip_values
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(236, [float(i) for i in range(52)]))
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "K", "strip": "K.cst"}}}
            wrong = [float(i) for i in range(52)]
            wrong[40] = 99.0
            problems = verify_strip_values(self._built(tmp, wrong), cfg)
            self.assertEqual(len(problems), 1)
            self.assertIn("40", problems[0])

    def test_a_factory_plugin_where_the_strip_has_a_dialled_one_is_caught(self):
        """The exact defect: a donor copied verbatim instead of taking the strip's values."""
        import tempfile
        from logicxkit.logic import verify_strip_values
        factory = [0.0, 11.0, 18.0, 22.0, 0.0, -100.0, 20.0, 0.0]
        dialled = [0.0, 7.0, 41.0, 88.0, 0.0, -23.0, 14.0, 2.0]
        with tempfile.TemporaryDirectory() as tmp:
            self._cst(tmp, "K.cst", chunk(236, [1.0] * 52), chunk(157, dialled))
            cfg = {"strip_root": tmp,
                   "chains": {"Kick In.cst": {"label": "K", "strip": "K.cst", "env": True}}}
            data = proj(
                rec(b"OCuA", 0, 0xFFFF, b"C" * 225),
                rec(b"UCuA", 0, 4, b"\x00" * 14 + b"S.pst".ljust(62, b"\x00")
                    + chunk(236, [1.0] * 52)),
                rec(b"UCuA", 0, 5, b"\x00" * 14 + b"S.pst".ljust(62, b"\x00")
                    + chunk(157, factory)),
                rec(b"UCuA", 0, 10, ref_payload("Kick In.cst")))
            problems = verify_strip_values(data, cfg)
            self.assertTrue(any("157" in p for p in problems))

    def test_channels_with_no_strip_are_not_checked(self):
        import tempfile
        from logicxkit.logic import verify_strip_values
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"chains": {"Kick In.cst": {"label": "K", "eq": {"hpf": {"freq": 30}}}}}
            self.assertEqual(verify_strip_values(self._built(tmp, [7.0] * 52), cfg), [])
