"""`logic chains` — apply native tracking chains to a project's channels.

Channels are matched by the channel-strip reference they carry, so one config works across
every session. Donors are taken from the target project itself, which keeps the record
class version correct (Logic 11.2.2 writes AuCU v4, 12.x writes v5).

The real-file part of tests/logic/test_chains.py; skips without the owner's files."""

import struct
import unittest
import _goldens
import _paths
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


class ExternalDonorTest(unittest.TestCase):
    """Some plugins exist in no project on disk — the Enveloper is in the user's saved .cst
    tracking strips but in none of the sessions. A donor can therefore be pulled from a .cst,
    which is safe only when the record class version matches the target project's."""

    def test_pulls_a_typed_slot_record_out_of_a_cst(self):
        from logicxkit.logic import donor_from_cst
        cst = _paths.STRIP_ROOT / "Track" / _paths.TRACK_LIB / "Drums/Kick In.cst"
        if not cst.exists():
            self.skipTest("strip library not present")
        raw, ver = donor_from_cst(cst, 157)
        self.assertIsNotNone(raw)
        self.assertEqual(ver, 5)

    def test_missing_type_returns_none(self):
        from logicxkit.logic import donor_from_cst
        cst = _paths.STRIP_ROOT / "Track" / _paths.TRACK_LIB / "Drums/Hi Hat.cst"
        if not cst.exists():
            self.skipTest("strip library not present")
        raw, _ver = donor_from_cst(cst, 157)
        self.assertIsNone(raw)

    def test_chain_with_env_orders_eq_env_comp(self):
        eq = rec(b"UCuA", 90, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(236, [0.0] * 52))
        cp = rec(b"UCuA", 91, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(154, [0.0] * 31))
        ev = rec(b"UCuA", 92, 5, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(157, [0.0] * 8))
        data = proj(rec(b"OCuA", 0, 0xFFFF, b"C" * 225),
                    rec(b"UCuA", 0, 10, ref_payload("Kick In.cst")))
        cfg = {"chains": {"Kick In.cst": {"label": "Kick In", "eq": {"hpf": {"freq": 30}},
                                          "env": True,
                                          "comp": {"circuit": "ClassicVCA", "threshold": -22,
                                                   "ratio": 5, "attack": 8, "release": 45}}}}
        plan, _ = chain_plan(data, cfg, eq, cp, env_donor=ev)
        self.assertEqual([s[1] for s in plan[0]], [4, 5, 6], "EQ -> Enveloper -> Compressor")

    def test_env_requested_without_a_donor_is_reported(self):
        eq = rec(b"UCuA", 90, 4, b"\x00" * 14 + b"D.pst".ljust(62, b"\x00") + chunk(236, [0.0] * 52))
        data = proj(rec(b"OCuA", 0, 0xFFFF, b"C" * 225),
                    rec(b"UCuA", 0, 10, ref_payload("Kick In.cst")))
        cfg = {"chains": {"Kick In.cst": {"label": "K", "eq": {"hpf": {"freq": 30}}, "env": True}}}
        plan, report = chain_plan(data, cfg, eq, None, env_donor=None)
        self.assertEqual([s[1] for s in plan[0]], [4])
        self.assertIn("Kick In.cst", report["degraded"])


class ChainChangesTest(unittest.TestCase):
    """What `chains` would replace, said out loud before it writes.

    `insert_slots` overwrites any existing slot at a key it writes, so on an already-dialled
    song the run silently discards work. The plan has to name it first.
    """

    def setUp(self):
        import _goldens
        self.SONG = _goldens.path("tracked-song")
        if not self.SONG:
            self.skipTest("the tracked-song golden is not present")
        from logicxkit.logic.services.chains import load_chain_config
        from logicxkit.logicx import project_data
        cfg_path = _paths.RIG_CONFIG / "logic" / "tracking-chains.json"
        if not cfg_path.exists():
            self.skipTest("the real chain config is not on this machine")
        self.cfg = _paths.onto_staged_strips(load_chain_config(cfg_path))
        self.data = project_data(self.SONG)

    def _changes(self, data=None):
        from logicxkit.logic.services.chain_report import chain_changes
        from logicxkit.logic.services.chains import base_donors, chain_plan, load_extra_donors
        from logicxkit.logic.services.insert import project_records
        data = self.data if data is None else data
        ver = next((r.ver for r in project_records(data) if r.tag == b"UCuA"), None)
        from logicxkit.utils.data import data_dir
        eq, comp, _ = base_donors(data, ver, data_dir("donors"))
        extra, _ = load_extra_donors(self.cfg, ver, data_dir("donors"))
        plan, _ = chain_plan(data, self.cfg, eq, comp,
                             env_donor=extra.get("enveloper", (None, None))[0], extra=extra)
        return chain_changes(data, plan)

    def test_a_dialled_song_reports_what_would_be_replaced(self):
        replacing = [c for c in self._changes() if c.replaced]
        self.assertTrue(replacing, "the tracked song carries dialled chains; none reported replaced")

    def test_every_change_names_its_channel_and_both_chains(self):
        for c in self._changes():
            with self.subTest(c.ref):
                self.assertTrue(c.ref)
                self.assertIsInstance(c.before, list)
                self.assertIsInstance(c.after, list)
                self.assertTrue(c.after, "a planned channel must end with a chain")

    def test_a_reorder_is_flagged(self):
        """Kick In is [Enveloper, EQ, Comp] in this song and [EQ, Enveloper, Comp] in the config."""
        kick = [c for c in self._changes() if c.ref == "Kick In.cst"]
        self.assertEqual(len(kick), 1)
        self.assertTrue(kick[0].replaced, "the dialled Kick In chain is overwritten")

    def test_an_untouched_channel_reports_no_replacement(self):
        """A channel the config covers but that carries no chain yet: made here by stripping
        one dialled channel, since every channel of the tracked song is dialled."""
        from logicxkit.logic.services.transplant import remove_slots
        dialled = next(c for c in self._changes() if c.before)
        stripped, removed = remove_slots(self.data, dialled.owner)
        self.assertTrue(removed)
        clean = next(c for c in self._changes(stripped) if c.owner == dialled.owner)
        self.assertEqual((clean.before, clean.replaced), ([], []))
        self.assertEqual(clean.after, dialled.after)


if __name__ == "__main__":
    unittest.main()


@_goldens.needs("chains-mine", "chains-logic")
class LogicResavedChainsTest(unittest.TestCase):
    """The tracking chains applied by `chains`, re-saved by Logic: every channel's chain came
    back as written (2026-09-12)."""

    def test_logic_kept_every_chain(self):
        from logicxkit.logic.services.project import analyze
        from logicxkit.logicx import project_data
        ours = {c["label"]: c["chain"] for c in analyze(project_data(_goldens.path("chains-mine")))["channels"]}
        logic = {c["label"]: c["chain"] for c in analyze(project_data(_goldens.path("chains-logic")))["channels"]}
        self.assertEqual(len(ours), _goldens.fact("chains-mine", "channels_with_inserts"))
        self.assertEqual(ours, logic)
