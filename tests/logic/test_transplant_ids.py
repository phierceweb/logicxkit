"""`transplant`'s per-instance ids, width refusals and stack targets.

Every copy of a plug-in gets its own instance id, measured from two instances of that plug-in
in the source, inside the last 20 bytes but the final four (the logic README, "Per-instance
ids"). A third-party slot keeps the width it was saved at, so a channel of the other width is
refused."""

import plistlib
import struct
import unittest

from _fixtures import chunk
from _records import chan, proj, rec
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.mixer.transplant import channel_slots, transplant

TAIL = 20
MONO, STEREO = 1, 2


def _tail(n: int) -> bytes:
    return struct.pack(">IHH", 0xA0000000 + n, 0xB2FC, 0x11F1) + bytes([0x80 | n, n]) + bytes(6) + bytes(4)


def _widths(p: bytearray, fmt: int) -> None:
    for off in (84, 118, 119):
        p[off] = fmt
    p[81] = fmt
    p[156] = fmt


def native(owner: int, key: int, n: int, *, gain: float = 0.0, fmt: int = MONO) -> bytes:
    p = bytearray(400)
    p[6] = key - 4
    body = chunk(236, [gain] * 8)
    p[200:200 + len(body)] = body
    _widths(p, fmt)
    return rec(b"UCuA", owner, key, bytes(p) + _tail(n), 5)


def au(owner: int, key: int, n: int, *, fmt: int = MONO, subtype: str = "Aln2") -> bytes:
    p = bytearray(400)
    p[6] = key - 4
    state = plistlib.dumps({"type": 0x61756678, "subtype": int.from_bytes(subtype.encode(), "big"), "manufacturer": 0x53726478})
    p[200:200 + len(state)] = state
    _widths(p, fmt)
    return rec(b"UCuA", owner, key, bytes(p[:200 + len(state) + 8]) + _tail(n), 5)


def ref(owner: int, key: int) -> bytes:
    p = bytearray(192)
    p[16:25] = b"Strip.cst"
    return rec(b"UCuA", owner, key, bytes(p), 5)


def mono_chan(owner: int, label: str, fmt: int = MONO) -> bytes:
    raw = bytearray(chan(owner, label))
    raw[HEADER + 123] = fmt
    return bytes(raw)


def ids(data: bytes, *owners: int) -> list[bytes]:
    return [channel_slots(data, o)[0].raw[-TAIL:-4] for o in owners]


def dst_project() -> bytes:
    return proj(*(r for o in (3, 4, 5) for r in (mono_chan(o, f"Audio {o}"), native(o, 4, 90 + o), ref(o, 10))))


class InstanceIdTest(unittest.TestCase):
    def _fan(self, src: bytes, force: bool = False) -> bytes:
        data = dst_project()
        for o in (3, 4, 5):
            data, _ = transplant(src, data, src_owner=1, dst_owner=o, fan_out=True, force=force)
        return data

    def test_each_copy_gets_its_own_id(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10), mono_chan(2, "Audio 2"), au(2, 4, 2), ref(2, 10))
        out = self._fan(src)
        got = ids(out, 3, 4, 5)
        self.assertEqual(len(set(got)), 3)
        self.assertNotIn(ids(src, 1)[0], got)

    def test_only_the_bytes_that_differ_between_instances_move(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10), mono_chan(2, "Audio 2"), au(2, 4, 2), ref(2, 10))
        donor = channel_slots(src, 1)[0].raw
        clone = channel_slots(self._fan(src), 4)[0].raw
        moved = {i for i in range(len(donor) - TAIL, len(donor)) if donor[i] != clone[i]}
        self.assertTrue(moved)
        self.assertTrue(moved <= {len(donor) - TAIL + i for i in (0, 1, 2, 3, 8, 9)})
        self.assertEqual(donor[HEADER + 200:len(donor) - TAIL], clone[HEADER + 200:len(clone) - TAIL])

    def test_settings_that_differ_between_instances_are_not_taken_for_the_id(self):
        src = proj(mono_chan(1, "Audio 1"), native(1, 4, 1, gain=0.0), ref(1, 10),
                   mono_chan(2, "Audio 2"), native(2, 4, 2, gain=6.0), ref(2, 10))
        donor = channel_slots(src, 1)[0].raw
        clone = channel_slots(self._fan(src), 3)[0].raw
        self.assertEqual(donor[HEADER:len(donor) - TAIL], clone[HEADER:len(clone) - TAIL])
        self.assertNotEqual(donor[-TAIL:], clone[-TAIL:])

    def test_a_single_instance_fanned_out_is_refused(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10))
        with self.assertRaises(ValueError) as e:
            self._fan(src)
        self.assertIn("second instance", str(e.exception))

    def test_force_writes_the_single_instance_verbatim(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10))
        self.assertEqual(set(ids(self._fan(src, force=True), 3, 4, 5)), set(ids(src, 1)))

    def test_one_copy_of_a_single_instance_needs_nothing(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10))
        out, report = transplant(src, dst_project(), src_owner=1, dst_owner=3)
        self.assertEqual(report["ids"], "verbatim")
        self.assertEqual(ids(out, 3), ids(src, 1))

    def test_a_one_to_one_move_keeps_the_source_id_even_when_it_could_be_measured(self):
        """apply-template's chains op is one-to-one and converges on byte equality with the
        template; stamping there would break that and change a path Logic re-saved as written."""
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10), mono_chan(2, "Audio 2"), au(2, 4, 2), ref(2, 10))
        out, report = transplant(src, dst_project(), src_owner=1, dst_owner=3)
        self.assertEqual(report["ids"], "verbatim")
        self.assertEqual(channel_slots(out, 3)[0].raw[HEADER:], channel_slots(src, 1)[0].raw[HEADER:])

    def test_the_report_says_the_ids_were_stamped(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10), mono_chan(2, "Audio 2"), au(2, 4, 2), ref(2, 10))
        _, report = transplant(src, dst_project(), src_owner=1, dst_owner=3, fan_out=True)
        self.assertEqual(report["ids"], "stamped")


class ChunkInWindowTest(unittest.TestCase):
    """A native plug-in whose parameter floats run into the last 20 bytes: two instances with
    different settings differ there, and those bytes are settings, not an id."""

    @staticmethod
    def _slot(owner: int, gain: float) -> bytes:
        p = bytearray(300)
        p[6] = 0
        _widths(p, MONO)
        return rec(b"UCuA", owner, 4, bytes(p) + chunk(236, [gain] * 8) + bytes(4), 5)

    def test_floats_in_the_window_are_not_taken_for_an_id(self):
        from logicxkit.logic.services.mixer.transplant import id_offsets
        src = proj(mono_chan(1, "Audio 1"), self._slot(1, 0.0), ref(1, 10),
                   mono_chan(2, "Audio 2"), self._slot(2, 6.0), ref(2, 10))
        raw = channel_slots(src, 1)[0].raw
        self.assertEqual(id_offsets(src, raw), ())


class WidthRefusalTest(unittest.TestCase):
    def test_a_stereo_third_party_slot_onto_a_mono_channel_is_refused(self):
        src = proj(mono_chan(1, "Audio 1", STEREO), au(1, 4, 1, fmt=STEREO), ref(1, 10))
        with self.assertRaises(ValueError) as e:
            transplant(src, dst_project(), src_owner=1, dst_owner=3)
        self.assertIn("mono", str(e.exception))

    def test_force_writes_it_anyway(self):
        src = proj(mono_chan(1, "Audio 1", STEREO), au(1, 4, 1, fmt=STEREO), ref(1, 10))
        out, report = transplant(src, dst_project(), src_owner=1, dst_owner=3, force=True)
        self.assertEqual(report["slots"], 1)

    def test_a_native_slot_is_restamped_not_refused(self):
        src = proj(mono_chan(1, "Audio 1", STEREO), native(1, 4, 1, fmt=STEREO), ref(1, 10))
        out, _ = transplant(src, dst_project(), src_owner=1, dst_owner=3)
        self.assertEqual(channel_slots(out, 3)[0].raw[HEADER + 84], MONO)

    def test_matching_widths_pass(self):
        src = proj(mono_chan(1, "Audio 1"), au(1, 4, 1), ref(1, 10))
        transplant(src, dst_project(), src_owner=1, dst_owner=3)

    def test_an_instrument_channel_is_not_refused(self):
        """An instrument channel's width byte does not describe its plug-in: Logic's own saves
        put stereo instruments on channels whose byte reads mono."""
        src = proj(mono_chan(1, "Inst 1", STEREO), au(1, 4, 1, fmt=STEREO), ref(1, 10))
        dst = proj(mono_chan(7, "Inst 3"), au(7, 4, 9), ref(7, 10))
        out, report = transplant(src, dst, src_owner=1, dst_owner=7)
        self.assertEqual(report["slots"], 1)


class StackTargetTest(unittest.TestCase):
    """`transplant --stack NAME=SRC`: every member of the stack, by the channel it is bound to."""

    @staticmethod
    def _targets(channel=None, stack=None):
        from argparse import Namespace
        from test_stacks import TRACKS, session
        from logicxkit.logic._apply import _targets
        return _targets(Namespace(channel=channel, stack=stack), session(), TRACKS)

    def test_the_members_take_the_source_label(self):
        self.assertEqual(self._targets(stack=["Drums=Audio 2"]), [("Audio 1", "Audio 2"), ("Audio 3", "Audio 2")])

    def test_a_channel_named_twice_goes_once_and_the_first_naming_wins(self):
        got = self._targets(channel=["Audio 1=Audio 9"], stack=["Drums=Audio 2"])
        self.assertEqual(got, [("Audio 1", "Audio 9"), ("Audio 3", "Audio 2")])

    def test_an_unknown_stack_names_the_ones_there_are(self):
        from logicxkit.logic._edit import CommandError
        with self.assertRaises(CommandError) as e:
            self._targets(stack=["Toms=Audio 2"])
        self.assertIn("Drums", str(e.exception))

    def test_a_stack_without_a_source_is_refused(self):
        from logicxkit.logic._edit import CommandError
        with self.assertRaises(CommandError):
            self._targets(stack=["Drums"])


if __name__ == "__main__":
    unittest.main()
