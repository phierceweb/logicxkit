"""A region moved onto another track — `regions --to-track` on a copy, read back — and what the
move refuses: the track it is on, a track that is not an audio track, a MIDI region."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _audio import tone
from _cli import count, data, run, source, written

from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.arrange.tracklist import CONTENT_FLAG, CONTENT_FLAG_AT, CONTENT_MARK, SELECTED_AT, arrange_run, row_object

from logicxkit.logic.services.regions.audio_regions import AUDIO_ENTRY, read_audio_regions
from logicxkit.logic.services.regions.region_edit import move_to_track
from logicxkit.logic.services.regions.regions import ENTRY, TRACK_OBJECT_AT, TRACK_ROW_AT, song_events
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.integrity import regressions, structural_report

THREE = "tracks-three-audio-logic"        # Audio 1, 2 and 3
INSTRUMENT = "tracks-instrument-logic"    # Audio 1 and Inst 1
BASE = "regions-a00-base-logic"           # region 1 is MIDI; 2, 3 and 4 are audio


@_goldens.needs(THREE, INSTRUMENT, BASE)
class MoveToTrackTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        self.take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{tone(self.out / 'take.wav')}", out=self.out / "take")

    def test_the_region_lands_on_the_other_track_with_every_other_field_kept(self):
        before, n = data(self.take), count(self.take)
        (was,) = read_audio_regions(before, n)
        code, text = run("regions", self.take, "--to-track", "1=Audio 2", "--out", self.out / "moved")
        self.assertEqual(code, 0, text)
        dest = self.out / "moved" / self.take.name
        after = data(dest)
        self.assertIsNone(structural_report(after)["unreadable"], text)
        self.assertEqual(regressions(before, after, removed=[(was.object_id, was.start, AUDIO_ENTRY)]), [], text)
        (now,) = read_audio_regions(after, count(dest))
        self.assertEqual((now.track, now.row), ("Audio 2", was.row + 1))
        a = song_events(project_records(before))[was.at:was.at + ENTRY]
        b = song_events(project_records(after))[now.at:now.at + ENTRY]
        track = {TRACK_OBJECT_AT, TRACK_OBJECT_AT + 1, TRACK_ROW_AT, TRACK_ROW_AT + 1}     # what Logic's own move changed
        changed = {i for i in range(ENTRY) if a[i] != b[i]}
        self.assertLessEqual(changed, track)
        self.assertTrue(changed & {TRACK_OBJECT_AT, TRACK_OBJECT_AT + 1}, changed)
        self.assertNotEqual(now.object_id, was.object_id)
        self.assertEqual((now.name, now.start, now.offset, now.frames, now.piece, now.fade, now.params, now.colour),
                         (was.name, was.start, was.offset, was.frames, was.piece, was.fade, was.params, was.colour))

    def test_onto_the_track_it_is_on_is_refused(self):
        code, text = run("regions", self.take, "--to-track", "1=Audio 1", "--out", self.out / "same")
        self.assertEqual(code, 1, text)
        self.assertIn("already on", text)
        self.assertFalse((self.out / "same" / self.take.name).exists())

    def test_a_move_runs_without_the_derived_notice_a_transpose_with_it(self):
        take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{tone(self.out / 'notice.wav')}", out=self.out / "noticetake")
        code, text = run("regions", take, "--to-track", "1=Audio 2", "--out", self.out / "moved")
        self.assertEqual(code, 0, text)
        self.assertNotIn("DERIVED", text)
        code, text = run("regions", take, "--transpose", "1=2", "--out", self.out / "transposed")
        self.assertEqual(code, 0, text)
        self.assertIn("'regions' is DERIVED", text)

    def test_onto_a_software_instrument_track_is_refused(self):
        take = written(self, "regions", INSTRUMENT, "--audio", f"Audio 1:1:{tone(self.out / 'inst.wav')}", out=self.out / "insttake")
        code, text = run("regions", take, "--to-track", "1=Inst 1", "--out", self.out / "refused")
        self.assertEqual(code, 1, text)
        self.assertIn("is not an audio track", text)
        self.assertFalse((self.out / "refused" / take.name).exists())

    def test_a_midi_region_is_refused(self):
        with self.assertRaisesRegex(ValueError, "MIDI"):
            move_to_track(data(BASE), 1, "Audio 2", count(BASE))
        code, text = run("regions", source(BASE), "--to-track", "1=Audio 2", "--out", self.out / "midi")
        self.assertEqual(code, 1, text)
        self.assertIn("MIDI", text)
        self.assertEqual(sorted((self.out / "midi").glob("*.logicx")), [], text)

    def test_a_move_past_the_next_track_and_back_lands_on_each_row(self):
        n = count(self.take)
        (was,) = read_audio_regions(data(self.take), n)
        far, back = self.out / "far" / self.take.name, self.out / "back" / self.take.name
        for src, to, dest in ((self.take, "Audio 3", far), (far, "Audio 1", back)):
            code, text = run("regions", src, "--to-track", f"1={to}", "--out", dest.parent)
            self.assertEqual(code, 0, text)
        rows = {r["name"]: r["object_id"] for r in read_tracks(data(far), n)}
        (on_far,), (on_back,) = read_audio_regions(data(far), n), read_audio_regions(data(back), n)
        self.assertEqual((on_far.track, on_far.object_id, on_far.row), ("Audio 3", rows["Audio 3"], was.row + 2))
        self.assertEqual((on_back.track, on_back.object_id, on_back.row), ("Audio 1", was.object_id, was.row))

    def test_an_unknown_track_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no track named"):
            move_to_track(data(self.take), 1, "Audio 9", count(self.take))

    def test_the_destination_row_is_flagged_as_holding_a_region_and_a_flagged_one_left_alone(self):
        """Logic 13.0's re-save of a move onto a bare row set `+2` 0x14 and `+43` 0x0c on it; the move writes them."""
        n = count(self.take)
        before = _row(data(self.take), "Audio 2", n)
        self.assertEqual(_flags(before), (0, 0))
        moved, back = self.out / "flagged" / self.take.name, self.out / "back-flagged" / self.take.name
        code, text = run("regions", self.take, "--to-track", "1=Audio 2", "--out", moved.parent)
        self.assertEqual(code, 0, text)
        after = _row(data(moved), "Audio 2", n)
        self.assertEqual(_flags(after), (CONTENT_FLAG, CONTENT_MARK))
        cleared = bytearray(after)
        cleared[HEADER + CONTENT_FLAG_AT] &= ~CONTENT_FLAG & 0xFF
        cleared[HEADER + SELECTED_AT] &= ~CONTENT_MARK & 0xFF
        self.assertEqual(bytes(cleared), before)
        code, text = run("regions", moved, "--to-track", "1=Audio 1", "--out", back.parent)              # Audio 1's row kept its flags
        self.assertEqual(code, 0, text)
        self.assertEqual(_row(data(back), "Audio 1", n), _row(data(moved), "Audio 1", n))


def _row(d: bytes, name: str, n: int) -> bytes:
    object_id = next(t["object_id"] for t in read_tracks(d, n) if t["name"] == name)
    records = project_records(d)
    return next(records[i].raw for i in arrange_run(records, n) if row_object(records[i].raw) == object_id)


def _flags(raw: bytes) -> tuple[int, int]:
    return raw[HEADER + CONTENT_FLAG_AT] & CONTENT_FLAG, raw[HEADER + SELECTED_AT] & CONTENT_MARK


if __name__ == "__main__":
    unittest.main()
