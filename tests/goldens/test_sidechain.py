"""The side-chain word Logic writes at slot payload +144/+145 — a Compressor pointed at Bus 1,
Bus 2 and Audio 1, then a Noise Gate and Pro-C 2 at Bus 1 (`sidechain-*`, 2026-09-22) — read
back to the source Logic showed, resolved from the source's name, and written byte for byte.
Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.insert import HEADER
from logicxkit.logic.services.sidechain import SideChain, carry, resolve, side_chain, source_name, with_side_chain
from logicxkit.logic.services.transplant import channel_slots, slot_at
from logicxkit.logicx import project_data

KEYS = ("sidechain-comp-none", "sidechain-comp-bus1", "sidechain-comp-bus2", "sidechain-comp-track",
        "sidechain-gate-bus1", "sidechain-proc-bus1", "sidechain-ours", "sidechain-ours-resave-logic")


def _slot(key: str):
    data = project_data(_goldens.path(key))
    facts = _goldens.entry(key)["facts"]
    return data, facts, slot_at(data, owner_by_label(data, facts["channel"]), facts["slot"]).raw


@_goldens.needs(*KEYS)
class SideChainGoldensTest(unittest.TestCase):
    def test_every_save_reads_the_source_logic_showed(self):
        for key in KEYS:
            with self.subTest(key):
                data, facts, raw = _slot(key)
                sc = side_chain(raw[HEADER:])
                want = facts["source"]
                if want is None:
                    self.assertIsNone(sc)
                else:
                    self.assertEqual((sc.kind, sc.index, sc.label), (want["kind"], want["index"], want["label"]))
                    self.assertEqual(source_name(data, sc), want["name"])

    def test_the_source_resolves_from_its_name_and_its_label(self):
        for key in KEYS[1:]:
            with self.subTest(key):
                data, facts, _raw = _slot(key)
                want = SideChain(facts["source"]["kind"], facts["source"]["index"])
                self.assertEqual(resolve(data, facts["source"]["name"]), want)
                self.assertEqual(resolve(data, facts["source"]["label"]), want)

    def test_writing_the_word_reproduces_logic_own_save(self):
        """The none save's Compressor given Bus 1, Bus 2 or Audio 1 is the record Logic wrote."""
        _d, _f, none = _slot("sidechain-comp-none")
        for key in ("sidechain-comp-bus1", "sidechain-comp-bus2", "sidechain-comp-track"):
            with self.subTest(key):
                data, facts, want = _slot(key)
                self.assertEqual(with_side_chain(none, SideChain(facts["source"]["kind"], facts["source"]["index"])), want)
                self.assertEqual(with_side_chain(want, None), none)

    def test_logic_kept_the_side_chain_we_wrote(self):
        """`add-plugin --side-chain 'Bus 2'` wrote the Noise Gate; Logic showed Bus 2 in its
        header and re-saved the record with the word as written."""
        _d, _f, ours = _slot("sidechain-ours")
        _d2, facts, theirs = _slot("sidechain-ours-resave-logic")
        self.assertEqual(side_chain(ours[HEADER:]), SideChain(0x45, 1))
        self.assertEqual(side_chain(theirs[HEADER:]), SideChain(0x45, 1))
        self.assertEqual(facts["source"]["menu"], "Bus 2")
        self.assertEqual(len(ours), len(theirs))

    def test_carried_between_the_saves_by_name(self):
        src, _f, raw = _slot("sidechain-comp-bus1")
        dst, _f2, _r = _slot("sidechain-comp-track")
        out, note = carry(src, raw, dst)
        self.assertEqual(out, raw)                    # the same project: Drums is still Bus 1
        self.assertIsNone(note)
        self.assertEqual(source_name(src, side_chain(raw[HEADER:])), "Bus 1")   # the file names no aux return


@_goldens.needs("sidechain-input2-logic", "sidechain-inst1-logic", "sidechain-inst-mine", "sidechain-inst-logic")
class InputAndInstrumentBytesTest(unittest.TestCase):
    """Logic's own saves of an input and an instrument track as the source, and `add-plugin
    --side-chain 'Inst 1'` kept as written."""

    def test_the_word_logic_wrote_and_the_one_we_write(self):
        for key in ("sidechain-input2-logic", "sidechain-inst1-logic", "sidechain-inst-mine", "sidechain-inst-logic"):
            facts = _goldens.entry(key)["facts"]
            data = project_data(_goldens.path(key))
            payload = slot_at(data, owner_by_label(data, facts["channel"]), facts["slot"]).raw[HEADER:]
            with self.subTest(key):
                want = facts["source"]
                self.assertEqual(side_chain(payload), SideChain(want["kind"], want["index"]))
                self.assertEqual(side_chain(payload).label, want["label"])


@_goldens.needs("sidechain-comp-bus1", "tracks-instrument-logic")
class InputAndInstrumentTest(unittest.TestCase):
    """Logic offers the interface's inputs and instrument tracks as sources too (Input 2 saved
    as 0x41 1, Inst 1 as 0x43 0)."""

    def test_an_input_side_chain_is_the_interfaces_and_stays_as_it_is(self):
        from logicxkit.logic.services.binding import channels
        from logicxkit.logic.services.sidechain import SideChain, carry, resolve, with_side_chain
        data = project_data(_goldens.path("sidechain-comp-bus1"))
        slot = next(s[0] for o in channels(data) if (s := channel_slots(data, o)))
        raw = with_side_chain(slot.raw, SideChain(0x41, 2))                  # Input 3: no channel object for it here
        self.assertEqual(carry(data, raw, data), (raw, None))
        self.assertEqual(resolve(data, "Input 3"), SideChain(0x41, 2))

    def test_an_instrument_track_feeds_a_side_chain(self):
        from logicxkit.logic.services.sidechain import SideChain, resolve
        data = project_data(_goldens.path("tracks-instrument-logic"))
        self.assertEqual(resolve(data, "Inst 1"), SideChain(0x43, 0))
        self.assertEqual(SideChain(0x43, 0).label, "Inst 1")


if __name__ == "__main__":
    unittest.main()
