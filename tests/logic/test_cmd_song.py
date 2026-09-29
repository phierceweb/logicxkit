"""The song-level commands run in-process on public corpus bundles, and the copy read back:
arrangement, signature, tempo, group."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, written

from logicxkit.logic.services.arrangement import read_sections
from logicxkit.logic.services.groups import read_groups
from logicxkit.logic.services.signature import BAR_ONE, PPQ, read_signatures
from logicxkit.logic.services.stacks import read_tracks
from logicxkit.logic.services.tempo import read_tempo_events

ARRANGEMENT = "arrangement-track-logic"        # the arrangement track shown, no sections yet
BLANK = "signature-list-base-logic"            # 4/4, one key, one tempo
THREE = "tracks-three-audio-logic"
BAR = 4 * PPQ


@_goldens.needs(ARRANGEMENT, BLANK, THREE, "group-drums-logic")
class SongCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_arrangement_add_rename_length_move_delete(self):
        added = written(self, "arrangement", ARRANGEMENT, "--add", "1:8:Intro:verse", "--add", "9:8:Verse",
                        out=self.out / "a")
        first = read_sections(data(added))
        self.assertEqual([(s.name, s.length) for s in first], [("Intro", 8 * BAR), ("Verse", 8 * BAR)])
        self.assertEqual(first[1].start, first[0].start + 8 * BAR)
        edited = written(self, "arrangement", added, "--rename", "1=Opening", "--length", "1=4", out=self.out / "b")
        self.assertEqual([(s.name, s.length) for s in read_sections(data(edited))], [("Opening", 4 * BAR), ("Verse", 8 * BAR)])
        moved = written(self, "arrangement", edited, "--move", "2=5", out=self.out / "c")
        self.assertEqual(read_sections(data(moved))[1].start, first[0].start + 4 * BAR)
        cut = written(self, "arrangement", moved, "--delete", "2", out=self.out / "d")
        self.assertEqual([s.name for s in read_sections(data(cut))], ["Opening"])

    def test_signature_time_and_key(self):
        dest = written(self, "signature", BLANK, "--time", "3/4", "--key", "A minor", out=self.out)
        times, keys = read_signatures(data(dest))
        self.assertEqual([(t.numerator, t.denominator) for t in times], [(3, 4)])
        self.assertNotEqual(keys[0].number, read_signatures(data(BLANK))[1][0].number)

    def test_tempo_set_and_add(self):
        dest = written(self, "tempo", BLANK, "--set", "140", "--add", "3=150", out=self.out)
        events = read_tempo_events(data(dest))
        self.assertEqual([(e.bpm, e.generated) for e in events], [(140.0, False), (150.0, False)])
        self.assertEqual(events[1].position - events[0].position, 2 * BAR)

    def test_tempo_ramp_after_the_bar_1_event(self):
        code, text = run("tempo", _goldens.path(BLANK), "--ramp", "1=120:5=140", "--out", self.out / "refused")
        self.assertEqual((code, "inside the ramp" in text), (1, True), text)
        dest = written(self, "tempo", BLANK, "--ramp", "3=120:7=140", out=self.out / "ramp")
        events = read_tempo_events(data(dest))
        self.assertEqual((events[0].position, events[0].bpm), (BAR_ONE, 120.0))
        self.assertEqual((events[1].position, events[-1].position, events[-1].bpm), (BAR_ONE + 2 * BAR, BAR_ONE + 6 * BAR, 140.0))
        self.assertEqual([e.bpm for e in events], sorted(e.bpm for e in events))
        self.assertGreater(len(events), 30, events)                      # eight points a bar, as Logic's 1/8

    def test_signature_changes_at_a_later_bar(self):
        dest = written(self, "signature", BLANK, "--time-at", "5=3/4", "--key-at", "5=G", out=self.out)
        times, keys = read_signatures(data(dest))
        self.assertEqual([(t.tick, t.numerator, t.denominator) for t in times], [(0, 4, 4), (BAR_ONE + 4 * BAR, 3, 4)])
        self.assertEqual([k.tick for k in keys], [0, BAR_ONE + 4 * BAR])

    def test_group_reads_without_out(self):
        code, text = run("group", _goldens.path("group-drums-logic"))
        self.assertEqual(code, 0, text)
        self.assertIn("Drums", text)

    def test_group_create_assign_rename(self):
        made = written(self, "group", THREE, "--create", "Drums", "--track", "Audio 1", "--track", "Audio 2",
                       out=self.out / "a")
        rows = {r["name"]: r["object_id"] for r in read_tracks(data(made), count(made))}
        self.assertEqual([(g.number, g.name, set(g.members)) for g in read_groups(data(made))],
                         [(1, "Drums", {rows["Audio 1"], rows["Audio 2"]})])
        more = written(self, "group", made, "--assign", "Audio 3=1", out=self.out / "b")
        self.assertEqual(set(read_groups(data(more))[0].members), {rows["Audio 1"], rows["Audio 2"], rows["Audio 3"]})
        named = written(self, "group", more, "--group", "1", "--name", "Kit", out=self.out / "c")
        self.assertEqual([g.name for g in read_groups(data(named))], ["Kit"])
        off = written(self, "group", named, "--group", "1", "--off", out=self.out / "d")
        self.assertNotEqual(read_groups(data(off))[0].flags, read_groups(data(named))[0].flags)
        self.assertEqual(set(read_groups(data(off))[0].members), set(read_groups(data(named))[0].members))


if __name__ == "__main__":
    unittest.main()
