"""What Logic 13.0's re-save changes in a 12.3.1 save, over eleven twins (`*-13-0-logic`, opened
and saved with no change, 2026-11-06): the format word at the song record's +4 and +1906 and a byte
at its +2457; every environment object's type words at +0 and +114, 488 lower; a word in each of the
32 `lytS` records; the audio file record's leading words 920 -> 952; one `gnnT` and one `ktSU` record,
the undo stack 13.0 saves (a `lESU` per step on the two 13.0 edit saves); `MroC` listing five MIDI
inputs. Three bases, the earliest saves of the blank, also gain what the other eight already carried
(channel `+42` 3, the Klopfgeist channel's Smart Controls archives, one `karT` row, the full
registry): save state, not 13.0's. Nothing else moves but the bytes listed in `ALLOWED`."""

import difflib
import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.environment import ENV_TAG, NAME_AT
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.regions.audio_regions import FILE_TAG, magic_at
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

PAIRS = (("tracks-two-audio-logic", "tracks-two-audio-13-0-logic"),
         ("stack-summing-logic", "stack-summing-13-0-logic"),
         ("inserts-native-all-logic", "inserts-native-all-13-0-logic"),
         ("send-two-base-3-logic", "send-two-base-3-13-0-logic"),
         ("automation-volume-fade-logic", "automation-volume-fade-13-0-logic"),
         ("tracks-instrument-logic", "tracks-instrument-13-0-logic"),
         ("stack-folder-logic", "stack-folder-13-0-logic"),
         ("regions-a10-midi-split-logic", "regions-a10-midi-split-13-0-logic"),
         ("group-drums-logic", "group-drums-13-0-logic"),
         ("tempo-point-140-logic", "tempo-point-140-13-0-logic"),
         ("markers-a23-second-logic", "markers-a23-second-13-0-logic"))
CATCH_UP = {"tracks-two-audio-logic", "stack-summing-logic", "stack-folder-logic"}
EDITS = {"regions-c04-crossfade-split-logic": "Split Regions",
         "strip-reference-reset-logic": "Change Channel Strip Setting"}
CHURN = {b"qeSM", b"qSvE"}                                  # rewritten on every save by every Logic
FORMAT, TYPE_DROP = 2514, 488
SONG_FORMAT_AT, SONG_STALE_AT, SONG_FLAG_AT = (4, 1906), (704, 2497), 2457      # 13.0 leaves the stale copies at 2513
LYTS_WORDS = [44, 104, 16, 20, 12, 68, 28, 36, 40, 32, 8, 120, 80, 88, 52, 24, 60, 84, 96, 56, 72, 76,
              92, 108, 112, 48, 100, 0xFFFF, 116, 124, 4, 64]
FILE_WORDS = (920, 952)                                     # `lFuA` +4 under 2513, under 2514
GNNT = bytes(586) + struct.pack("<II", 18, 100)
MIDI_INPUTS = [b"Logic Pro Virtual In", b"Touch Keyboard A", b"Touch Keyboard B", b"Touch Keyboard C", b"Touch Keyboard D"]
ALLOWED = {b"karT": {43}, b"OCuA": {42, 80, 116, 117, 118, 128}, b"nCuA": {67}, b"UCuA": {0, 116, 117, 146},
           b"qSxT": {27}, b"gRuA": {136}, b"vEuA": {0, 1, 2, 3, 21, 44, 51}, b"lytS": {12, 13}}


def records(key):
    return project_records(project_data(_goldens.path(key)))


def paired(base, twin):
    """Same-position records of the two saves, matched on (tag, owner, key)."""
    a, b = records(base), records(twin)
    sm = difflib.SequenceMatcher(a=[(r.tag, r.owner, r.key) for r in a], b=[(r.tag, r.owner, r.key) for r in b], autojunk=False)
    same, added, removed = [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            same.extend(zip(a[i1:i2], b[j1:j2], strict=True))
        else:
            added.extend(b[j1:j2])
            removed.extend(a[i1:i2])
    return same, added, removed


def name_end(payload: bytes) -> int:
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    return NAME_AT + 2 + n + (n & 1)


def allowed(tag: bytes, old: bytes, new: bytes, offset: int) -> bool:
    if tag in (ENV_TAG, b"snrT"):
        if offset in (0, 1, 114, 115):
            return True
        if old[NAME_AT + 2:NAME_AT + 12] == b"MIDI Click":
            return offset >= 223
        return name_end(old) + 10 <= offset < name_end(old) + 14      # two words 12.3.1's earliest saves carried, 0 since
    if tag == FILE_TAG:
        m = magic_at(old)
        return offset in (0, 1, 4, 5, m + 4, m + 530, m + 531)       # the words, the present byte, a word cleared with it
    if tag == b"UCuA" and offset >= len(old) - 16:
        return True                                                  # an archive's trailing stamp
    return offset in ALLOWED.get(tag, ())


@_goldens.needs(*(k for pair in PAIRS for k in pair))
class TwinsTest(unittest.TestCase):
    def test_no_byte_moves_outside_the_measured_set(self):
        for base, twin in PAIRS:
            same, added, removed = paired(base, twin)
            with self.subTest(twin=twin):
                self.assertLessEqual({r.tag for r in added} - CHURN, {b"gnnT", b"ktSU", b"karT"} | ({b"UCuA"} if base in CATCH_UP else set()))
                self.assertLessEqual({r.tag for r in removed} - CHURN, {b"karT"})       # the track lists pair up positionally
                self.assertEqual(sum(r.tag == b"karT" for r in added) - sum(r.tag == b"karT" for r in removed), 1 if base in CATCH_UP else 0)
                resized = {ra.tag for ra, rb in same if len(ra.raw) != len(rb.raw)} - CHURN
                self.assertIn(b"MroC", resized)
                self.assertLessEqual(resized, {b"gnoS", b"MroC"} | ({CHANNEL_TAG} if base in CATCH_UP else set()))
                for ra, rb in same:
                    if ra.tag in CHURN | {b"gnoS"} or len(ra.raw) != len(rb.raw):
                        continue
                    old, new = ra.raw[HEADER:], rb.raw[HEADER:]
                    stray = [i for i in range(len(old)) if old[i] != new[i] and not allowed(ra.tag, old, new, i)]
                    self.assertEqual(stray, [], (ra.tag, ra.owner, ra.key, len(old)))

    def test_the_song_record_carries_the_format_twice_and_a_new_flag(self):
        for base, twin in PAIRS:
            with self.subTest(twin=twin):
                old = next(r.raw[HEADER:] for r in records(base) if r.tag == b"gnoS")
                new = next(r.raw[HEADER:] for r in records(twin) if r.tag == b"gnoS")
                self.assertEqual([struct.unpack_from("<H", new, at)[0] for at in SONG_FORMAT_AT], [FORMAT, FORMAT])
                self.assertEqual([struct.unpack_from("<H", old, at)[0] for at in SONG_FORMAT_AT], [2513, 2513])
                self.assertEqual([struct.unpack_from("<H", g, at)[0] for g in (old, new) for at in SONG_STALE_AT], [2513] * 4)
                self.assertEqual((old[SONG_FLAG_AT], new[SONG_FLAG_AT]), (0, 8))
                self.assertGreaterEqual(len(new), len(old))

    def test_every_object_type_word_is_488_lower_at_both_places(self):
        for base, twin in PAIRS:
            same, _a, _r = paired(base, twin)
            with self.subTest(twin=twin):
                objects = [(ra.raw[HEADER:], rb.raw[HEADER:]) for ra, rb in same if ra.tag in (ENV_TAG, b"snrT")]
                self.assertGreater(len(objects), 10)
                for old, new in objects:
                    for at in (0, 114):
                        self.assertEqual(struct.unpack_from("<H", old, at)[0] - struct.unpack_from("<H", new, at)[0], TYPE_DROP)

    def test_the_32_style_records_get_one_fixed_word(self):
        for base, twin in PAIRS:
            with self.subTest(twin=twin):
                old = [struct.unpack_from("<I", r.raw, HEADER + 12)[0] for r in records(base) if r.tag == b"lytS"]
                new = [struct.unpack_from("<I", r.raw, HEADER + 12)[0] for r in records(twin) if r.tag == b"lytS"]
                self.assertEqual(old, [0] * 32)
                self.assertEqual(new, LYTS_WORDS)

    def test_the_audio_file_record_leads_with_952(self):
        seen = 0
        for base, twin in PAIRS:
            same, _a, _r = paired(base, twin)
            for ra, rb in same:
                if ra.tag != FILE_TAG:
                    continue
                seen += 1
                old, new = ra.raw[HEADER:], rb.raw[HEADER:]
                self.assertEqual((struct.unpack_from("<I", old, 4)[0], struct.unpack_from("<I", new, 4)[0]), FILE_WORDS)
                self.assertEqual(struct.unpack_from("<I", new, 0)[0] & 0x3FFFF, FILE_WORDS[1])
        self.assertEqual(seen, 7)

    def test_the_new_records_and_the_midi_inputs(self):
        for base, twin in PAIRS:
            with self.subTest(twin=twin):
                new = records(twin)
                self.assertEqual([r.raw[HEADER:] for r in new if r.tag == b"gnnT"], [GNNT])
                self.assertEqual([r.raw[HEADER:] for r in new if r.tag == b"ktSU"], [bytes(8)])
                self.assertEqual([r.tag for r in new if r.tag == b"lESU"], [])
                inputs = next(r.raw[HEADER:] for r in new if r.tag == b"MroC")
                self.assertEqual((len(inputs), inputs[2]), (506, 5))
                self.assertEqual([inputs[10 + 100 * i:10 + 100 * i + 20].rstrip(b"\0") for i in range(5)], MIDI_INPUTS)
                before = next(r.raw[HEADER:] for r in records(base) if r.tag == b"MroC")
                self.assertEqual(len(before), 6 + 100 * before[2])

    def test_the_catch_up_is_save_state_the_other_eight_already_carry(self):
        for base, twin in PAIRS:
            with self.subTest(base=base):
                for key, expect in ((base, base not in CATCH_UP), (twin, True)):
                    recs = records(key)
                    at_42 = {r.raw[HEADER + 42] for r in recs if r.tag == CHANNEL_TAG and len(r.raw) - HEADER > 42}
                    archives = sorted(len(r.raw) - HEADER for r in recs if r.tag == b"UCuA" and len(r.raw) - HEADER in (831, 1921))
                    self.assertEqual((at_42, bool(archives)), ({3}, True) if expect else ({0}, False), key)


@_goldens.needs(*EDITS)
class UndoStackTest(unittest.TestCase):
    def test_an_edit_save_holds_the_step_by_its_undo_name(self):
        for key, name in EDITS.items():
            with self.subTest(key=key):
                recs = records(key)
                self.assertEqual([r.raw[HEADER:] for r in recs if r.tag == b"ktSU"], [struct.pack("<II", 1, 1)])
                steps = [r.raw[HEADER:] for r in recs if r.tag == b"lESU"]
                self.assertEqual(len(steps), 1)
                length = struct.unpack_from("<I", steps[0], 0)[0]
                self.assertEqual((length, steps[0][8:8 + length]), (len(name), name.encode()))
                self.assertEqual(steps[0].count(b"gnoS"), 2)              # the records before and after the step


if __name__ == "__main__":
    unittest.main()
