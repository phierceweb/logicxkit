"""A stereo instrument channel: the one Logic made itself carries `INST_FRESH_STEREO`, the bytes
`add-track --instrument --stereo` writes, and Logic 12.4 saved a track added that way with the
channel still stereo. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.mixer.binding import channel_label
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

LOGIC = "sessionplayer-track-logic"
MINE, RESAVE = "addtrack-inst-stereo-mine", "addtrack-inst-stereo-logic"


@_goldens.needs(LOGIC)
class LogicsStereoInstrumentTest(unittest.TestCase):
    def test_its_one_stereo_instrument_channel_carries_the_set(self):
        from logicxkit.logic.services.mixer.channel_alloc import INST_FRESH, INST_FRESH_STEREO
        channels = [r.raw[HEADER:] for r in project_records(project_data(_goldens.path(LOGIC)))
                    if is_mixer_record(r) and channel_label(r.raw[HEADER:]).startswith("Inst ")]
        stereo = [p for p in channels if p[123] == 2]
        self.assertEqual(len(stereo), 1)
        self.assertEqual({at: stereo[0][at] for at in INST_FRESH_STEREO}, INST_FRESH_STEREO)
        for p in channels:
            if p[123] == 1:
                self.assertEqual({at: p[at] for at in INST_FRESH}, INST_FRESH)


def _strip(test: unittest.TestCase, key: str) -> tuple[bytes, bytes]:
    """(channel payload, instrument slot payload) of the track the facts name."""
    from logicxkit.logic.services.mixer.slots import slot_index_base
    from logicxkit.logic.services.arrange.stacks import read_tracks
    data = project_data(_goldens.path(key))
    rows = read_tracks(data, _goldens.fact(key, "tracks"))
    row = next(r for r in rows if r["name"] == _goldens.fact(key, "track"))
    test.assertEqual(row["label"], _goldens.fact(key, "label"))
    records = project_records(data)
    owner, base = row["owner"], slot_index_base(data)
    channel = next(r.raw[HEADER:] for r in records if is_mixer_record(r) and r.owner == owner)
    slot = next(r.raw[HEADER:] for r in records
                if r.tag == b"UCuA" and r.owner == owner and r.key == base)
    return channel, slot


@_goldens.needs(MINE, RESAVE)
class LogicKeptOursStereoTest(unittest.TestCase):
    """Logic takes an instrument channel's width from its instrument slot, so the slot is written
    stereo as well."""

    def test_the_channel_and_its_slot_are_stereo_in_both(self):
        from logicxkit.logic.services.mixer.channel_alloc import INST_SLOT_WIDTH_AT
        for key in (MINE, RESAVE):
            with self.subTest(key):
                channel, slot = _strip(self, key)
                self.assertEqual([channel[at] for at in (78, 81, 86, 123)],
                                 _goldens.fact(key, "channel_width"))
                self.assertEqual([slot[at] for at in INST_SLOT_WIDTH_AT],
                                 _goldens.fact(key, "slot_width"))

    def test_logic_kept_the_instrument_slot_byte_for_byte(self):
        from logicxkit.logic.services.mixer.channel_alloc import INST_SLOT_CLOSE
        (_, ours), (_, logics) = _strip(self, MINE), _strip(self, RESAVE)
        self.assertEqual(logics, ours)
        self.assertEqual(ours[-INST_SLOT_CLOSE:], bytes(INST_SLOT_CLOSE))


CHAN = ("addtrack-inst-stereo-chan-mine", "addtrack-inst-stereo-chan-logic")
OUTS = ("addtrack-inst-stereo-outs-mine", "addtrack-inst-stereo-outs-logic")
SLOT_BYTES_AT = (81, 84, 116, 119)


@_goldens.needs(*CHAN, *OUTS)
class SlotDecidesTheWidthTest(unittest.TestCase):
    """The two saves behind `INST_SLOT_STEREO`: a stereo channel over a mono slot comes back mono,
    and a slot whose output counts alone are stereo keeps the channel stereo, Logic filling in
    the config index and the variant id itself."""

    def _bytes(self, key: str) -> tuple[list[int], list[int]]:
        channel, slot = _strip(self, key)
        return [channel[at] for at in (78, 81, 86, 123)], [slot[at] for at in SLOT_BYTES_AT]

    def test_the_facts_are_the_files(self):
        for key in (*CHAN, *OUTS):
            with self.subTest(key):
                self.assertEqual(self._bytes(key), (_goldens.fact(key, "channel_width"), _goldens.fact(key, "slot_bytes")))

    def test_a_stereo_channel_over_a_mono_slot_is_saved_mono(self):
        (ours_channel, ours_slot), (logic_channel, logic_slot) = self._bytes(CHAN[0]), self._bytes(CHAN[1])
        self.assertEqual(ours_channel, [247, 8, 1, 2])
        self.assertEqual(logic_channel, [243, 8, 0, 1])
        self.assertEqual(logic_slot, ours_slot)
        self.assertEqual(ours_slot, [1, 1, 254, 1])

    def test_stereo_output_counts_alone_keep_the_channel_stereo(self):
        from logicxkit.logic.services.mixer.channel_alloc import INST_SLOT_STEREO
        (ours_channel, ours_slot), (logic_channel, logic_slot) = self._bytes(OUTS[0]), self._bytes(OUTS[1])
        self.assertEqual(ours_slot, [1, 2, 254, 2])
        self.assertEqual(logic_channel, ours_channel)
        self.assertEqual(logic_channel, [247, 8, 1, 2])
        self.assertEqual(logic_slot, [INST_SLOT_STEREO[at] for at in SLOT_BYTES_AT])


if __name__ == "__main__":
    unittest.main()
