"""`logic chains` — apply native tracking chains to a project's channels.

Channels are matched by the channel-strip reference they carry, so one config works across
every session. Donors are taken from the target project itself, which keeps the record
class version correct (Logic 11.2.2 writes AuCU v4, 12.x writes v5)."""

import struct
import unittest
from _fixtures import chunk
from logicxkit.logic import chain_plan

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


class ChainPlanTest(unittest.TestCase):
    def setUp(self):
        self.eq_donor = rec(b"UCuA", 90, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                            + chunk(236, [0.0] * 52))
        self.comp_donor = rec(b"UCuA", 91, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                              + chunk(154, [0.0] * 31))
        self.data = proj(
            rec(b"OCuA", 0, 0xFFFF, b"C" * 225), rec(b"UCuA", 0, 10, ref_payload("Kick In.cst")),
            rec(b"OCuA", 1, 0xFFFF, b"C" * 225), rec(b"UCuA", 1, 10, ref_payload("Hi Hat.cst")),
            rec(b"OCuA", 2, 0xFFFF, b"C" * 225), rec(b"UCuA", 2, 10, ref_payload("Guitar SLO.cst")),
        )
        self.cfg = {"chains": {
            "Kick In.cst": {"label": "Kick In", "eq": {"hpf": {"freq": 30}},
                            "comp": {"circuit": "ClassicVCA", "threshold": -22, "ratio": 5,
                                     "attack": 8, "release": 45}},
            "Hi Hat.cst": {"label": "Hi Hat", "eq": {"hpf": {"freq": 300}}},
        }}

    def test_matches_channels_by_their_reference(self):
        plan, report = chain_plan(self.data, self.cfg, self.eq_donor, self.comp_donor)
        self.assertEqual(sorted(plan), [0, 1])
        self.assertEqual(report["unmatched"], ["Guitar SLO.cst"])

    def test_eq_only_chain_gets_one_slot(self):
        plan, _ = chain_plan(self.data, self.cfg, self.eq_donor, self.comp_donor)
        self.assertEqual(len(plan[1]), 1)
        self.assertEqual(len(plan[0]), 2)

    def test_comp_only_chain_takes_the_first_slot_key(self):
        cfg = {"chains": {"Kick In.cst": {"label": "Bus", "comp": {
            "circuit": "ClassicVCA", "threshold": -10, "ratio": 2, "attack": 40, "release": 100}}}}
        plan, _ = chain_plan(self.data, cfg, self.eq_donor, self.comp_donor)
        self.assertEqual([slot[1] for slot in plan[0]], [4])

    def test_missing_comp_donor_is_reported_not_crashed(self):
        plan, report = chain_plan(self.data, self.cfg, self.eq_donor, None)
        self.assertEqual(len(plan[0]), 1, "EQ still applies")
        self.assertIn("Kick In.cst", report["degraded"])

    def test_labels_flow_through(self):
        plan, _ = chain_plan(self.data, self.cfg, self.eq_donor, self.comp_donor)
        self.assertEqual({slot[4] for slot in plan[0]}, {"Trk - Kick In"})


class ConfigDeclaredDonorTest(unittest.TestCase):
    """Plugins that exist in no session (Enveloper, Gain, ChromaVerb) are declared in the
    config with the .cst to source them from, so adding one is a config edit rather than a
    code change. `pre` slots sit ahead of the EQ; `post` after the compressor."""

    def setUp(self):
        self.eq = rec(b"UCuA", 90, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(236, [0.0] * 52))
        self.cp = rec(b"UCuA", 91, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(154, [0.0] * 31))
        self.gain = rec(b"UCuA", 92, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(183, [0.0] * 10))
        self.data = proj(rec(b"OCuA", 0, 0xFFFF, b"C" * 225),
                         rec(b"UCuA", 0, 10, ref_payload("Snare Down.cst")))

    def test_pre_slot_comes_before_the_eq(self):
        from logicxkit.logic import chain_plan
        cfg = {"chains": {"Snare Down.cst": {"label": "Snare Btm", "pre": ["gain"],
                                             "eq": {"hpf": {"freq": 180}},
                                             "comp": {"circuit": "ClassicVCA", "threshold": -16,
                                                      "ratio": 2.5, "attack": 7, "release": 55}}}}
        plan, _ = chain_plan(self.data, cfg, self.eq, self.cp, extra={"gain": (self.gain, 183)})
        self.assertEqual([s[1] for s in plan[0]], [4, 5, 6])
        self.assertEqual(plan[0][0][6], 183, "Gain leads the chain")

    def test_extra_slot_is_copied_verbatim_when_no_values_given(self):
        from logicxkit.logic import chain_plan
        cfg = {"chains": {"Snare Down.cst": {"label": "S", "pre": ["gain"]}}}
        plan, _ = chain_plan(self.data, cfg, self.eq, self.cp, extra={"gain": (self.gain, 183)})
        self.assertIsNone(plan[0][0][2], "no float patching — the donor's own settings are kept")

    def test_unknown_donor_name_is_reported_not_crashed(self):
        from logicxkit.logic import chain_plan
        cfg = {"chains": {"Snare Down.cst": {"label": "S", "pre": ["chromaverb"],
                                             "eq": {"hpf": {"freq": 180}}}}}
        plan, report = chain_plan(self.data, cfg, self.eq, self.cp, extra={})
        self.assertEqual([s[1] for s in plan[0]], [4])
        self.assertIn("Snare Down.cst", report["degraded"])

    def test_post_slot_follows_the_compressor(self):
        from logicxkit.logic import chain_plan
        verb = rec(b"UCuA", 93, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(287, [0.0] * 40))
        cfg = {"chains": {"Snare Down.cst": {"label": "S", "eq": {"hpf": {"freq": 180}},
                                             "post": ["verb"]}}}
        plan, _ = chain_plan(self.data, cfg, self.eq, self.cp, extra={"verb": (verb, 287)})
        self.assertEqual([s[6] for s in plan[0]], [236, 287])


class FloatOverrideTest(unittest.TestCase):
    """Sparse parameter overrides: change named float indices and leave every other value in
    the donor untouched.

    A whole-array write would zero the parameters we cannot map, and several plugins have
    indices Apple's own parameter list omits. ChromaVerb has 81 floats of which ~12 are
    documented, so overriding by index is the only safe way to dial one.
    """

    def _donor(self, values):
        payload = bytearray(14 + 62)
        payload[14:14 + 6] = b"D.pst"
        return rec(b"UCuA", 9, 4, bytes(payload) + chunk(287, values))

    def test_overrides_only_the_named_indices(self):
        from logicxkit.logic import apply_float_overrides
        donor = self._donor([float(i) for i in range(20)])
        out = apply_float_overrides(donor, {3: 9.0, 6: 2.5})
        from logicxkit.logic import find_blocks, read_block_floats
        idx, _t, n = find_blocks(out[36:])[0]
        got = read_block_floats(out[36:], idx, n)
        self.assertEqual(got[3], 9.0)
        self.assertEqual(got[6], 2.5)
        self.assertEqual([got[i] for i in (0, 1, 2, 4, 5, 7)], [0.0, 1.0, 2.0, 4.0, 5.0, 7.0])

    def test_length_is_unchanged(self):
        from logicxkit.logic import apply_float_overrides
        donor = self._donor([0.0] * 20)
        self.assertEqual(len(apply_float_overrides(donor, {3: 2.0})), len(donor))

    def test_index_past_the_array_is_ignored(self):
        from logicxkit.logic import apply_float_overrides
        donor = self._donor([0.0] * 5)
        out = apply_float_overrides(donor, {99: 1.0})
        self.assertEqual(out, donor)

    def test_no_overrides_is_a_no_op(self):
        from logicxkit.logic import apply_float_overrides
        donor = self._donor([1.0] * 5)
        self.assertEqual(apply_float_overrides(donor, {}), donor)


class DuplicateChainSlotTest(unittest.TestCase):
    """A channel whose existing chain sits at higher slot keys than the plan keeps those
    records: the plan overwrites keys 4..n and anything past them survives. When the survivor
    is a plugin the chain just placed, the channel gets it twice in series — the run still
    reports success, and the doubling only shows up on playback."""

    def _chan(self, owner: int, ref: str, existing: list[tuple[int, int]]) -> list[bytes]:
        chan = bytearray(b"C" * 225)
        chan[123] = 1                      # the channel's own width; 'C' is not a valid one
        out = [rec(b"OCuA", owner, 0xFFFF, bytes(chan)),
               rec(b"UCuA", owner, 10, ref_payload(ref))]
        for key, type_id in existing:
            payload = bytearray(200)
            payload[6] = key - 4                       # slot index; this project's base is 4
            payload[14:19] = b"D.pst"
            for off in (81, 84, 118, 119, 156):
                payload[off] = 1                       # mono, matching the channel
            out.append(rec(b"UCuA", owner, key, bytes(payload) + chunk(type_id, [0.0] * 31)))
        return out

    def setUp(self):
        self.eq_donor = rec(b"UCuA", 90, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                            + chunk(236, [0.0] * 52))
        self.comp_donor = rec(b"UCuA", 91, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00")
                              + chunk(154, [0.0] * 31))
        self.cfg = {"chains": {"Vox - Lead.cst": {
            "label": "Vox", "eq": {"hpf": {"freq": 90}},
            "comp": {"circuit": "VintageVCA", "threshold": -19, "ratio": 2.5,
                     "attack": 22, "release": 140}}}}

    def test_a_survivor_of_a_placed_type_is_reported(self):
        from logicxkit.logic import chain_plan, duplicate_chain_slots, insert_slots
        # the project's own Compressor sits at key 6; the plan writes EQ@4 and Comp@5
        data = proj(*self._chan(0, "Vox - Lead.cst", [(6, 154)]))
        plan, _ = chain_plan(data, self.cfg, self.eq_donor, self.comp_donor)
        patched = insert_slots(data, plan)
        dupes = duplicate_chain_slots(patched, plan)
        self.assertEqual(dupes, [(0, 6, 154)], "two Compressors in series must not pass silently")
        from logicxkit.logic import describe_duplicates
        self.assertIn("Vox - Lead.cst", describe_duplicates(patched, dupes)[0])

    def test_dropping_the_duplicate_leaves_exactly_the_chain(self):
        from logicxkit.logic import chain_plan, duplicate_chain_slots, insert_slots
        data = proj(*self._chan(0, "Vox - Lead.cst", [(6, 154)]))
        plan, _ = chain_plan(data, self.cfg, self.eq_donor, self.comp_donor)
        dupes = duplicate_chain_slots(insert_slots(data, plan), plan)
        drop = {owner: {key} for owner, key, _t in dupes}
        cleaned = insert_slots(data, plan, drop=drop)
        self.assertEqual(duplicate_chain_slots(cleaned, plan), [])

    def test_dropping_never_touches_a_plugin_the_chain_does_not_place(self):
        """Bass DI's own Channel EQ is not superseded, so nothing is dropped for it."""
        from logicxkit.logic import chain_plan, duplicate_chain_slots, insert_slots
        cfg = {"chains": {"Bass DI.cst": {"label": "Bass DI", "comp": {
            "circuit": "FET", "threshold": -12.0, "ratio": 2.5,
            "attack": 33, "release": 64}}}}
        data = proj(*self._chan(0, "Bass DI.cst", [(5, 236)]))
        plan, _ = chain_plan(data, cfg, self.eq_donor, self.comp_donor)
        self.assertEqual(duplicate_chain_slots(insert_slots(data, plan), plan), [])

    def test_a_pre_existing_plugin_the_chain_does_not_place_is_left_alone(self):
        """Bass DI's chain is a Compressor only; the channel's own Channel EQ is not a
        duplicate and must not be flagged."""
        from logicxkit.logic import chain_plan, duplicate_chain_slots, insert_slots
        cfg = {"chains": {"Bass DI.cst": {"label": "Bass DI", "comp": {
            "circuit": "FET", "threshold": -12.0, "ratio": 2.5,
            "attack": 33, "release": 64}}}}
        data = proj(*self._chan(0, "Bass DI.cst", [(5, 236)]))
        plan, _ = chain_plan(data, cfg, self.eq_donor, self.comp_donor)
        self.assertEqual(duplicate_chain_slots(insert_slots(data, plan), plan), [])

    def test_a_fully_overwritten_channel_is_clean(self):
        from logicxkit.logic import chain_plan, duplicate_chain_slots, insert_slots
        data = proj(*self._chan(0, "Vox - Lead.cst", [(4, 236), (5, 154)]))
        plan, _ = chain_plan(data, self.cfg, self.eq_donor, self.comp_donor)
        self.assertEqual(duplicate_chain_slots(insert_slots(data, plan), plan), [])


class ChainsDiscardTest(unittest.TestCase):
    """A refused run must take the copy away: `chains` writes alternative by alternative, so a
    refusal on the second leaves the first already patched."""

    def test_a_refused_run_removes_the_copy(self):
        import argparse
        import tempfile
        from pathlib import Path
        from unittest import mock
        from pf_core.exceptions import PreconditionError
        from logicxkit.logic import _chains_cmd

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "Song.logicx"
            (src / "Alternatives" / "000").mkdir(parents=True)
            (src / "Alternatives" / "000" / "ProjectData").write_bytes(b"x")
            out = root / "out"
            cfg = root / "cfg.json"
            cfg.write_text('{"chains": {}, "donors": {}}')
            args = argparse.Namespace(project=str(src), out=str(out), config=str(cfg),
                                      library=None, plan=False, strict=False)
            with mock.patch.object(_chains_cmd, "load_chain_config", return_value={}), \
                 mock.patch.object(_chains_cmd, "_apply_chains",
                                   side_effect=PreconditionError("refused")):
                with self.assertRaises(PreconditionError):
                    _chains_cmd.cmd_chains(args)
            self.assertEqual(list(out.glob("*")), [], "the refused copy was left behind")
