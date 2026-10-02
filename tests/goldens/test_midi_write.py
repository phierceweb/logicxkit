"""Writing MIDI regions and notes, held to Logic's own saves: the empty region Logic made with
the Pencil tool, and the note it then made in the Event List."""

import unittest
from collections import Counter
import _goldens
from logicxkit.logic.services.midi import read_midi
from logicxkit.logic.services.midi_write import add_note, add_region
from logicxkit.logic.services.recdiff import diff_records
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

UNSIZED = (b"gnoS", b"qeSM")


def shape(data: bytes) -> Counter:
    from logicxkit.logic.services.stream import project_records
    return Counter((r.tag, None if r.tag in UNSIZED else len(r.raw)) for r in project_records(data))


@_goldens.needs("inserts-native-all-logic", "midi-empty-region-logic")
class RegionTest(unittest.TestCase):
    def test_our_region_reads_and_is_shaped_like_logics(self):
        base = project_data(_goldens.path("inserts-native-all-logic"))
        logic = project_data(_goldens.path("midi-empty-region-logic"))
        (theirs,) = read_midi(logic)
        out, report = add_region(base, track=theirs.track, start=theirs.start, length=3840)
        (ours,) = read_midi(out)
        self.assertEqual((ours.track, ours.start, ours.name, ours.loop, ours.events), (theirs.track, theirs.start, theirs.name, False, []))
        self.assertEqual(validate_project(out), [])
        self.assertEqual(shape(out), shape(logic))       # consecutive saves of one session: no load noise


@_goldens.needs("midi-empty-region-logic", "midi-one-note-logic", "midi-note-channel-2-logic", "midi-two-notes-logic")
class NoteTest(unittest.TestCase):
    def test_our_note_is_logics_note(self):
        base = project_data(_goldens.path("midi-empty-region-logic"))
        logic = project_data(_goldens.path("midi-one-note-logic"))
        (want,) = read_midi(logic)
        (n,) = want.events
        out = add_note(base, track=want.track, tick=n.tick, pitch=n.pitch, velocity=n.velocity, length=n.length, channel=n.channel)
        (ours,) = read_midi(out)
        self.assertEqual(ours.events, want.events)
        self.assertEqual(validate_project(out), [])
        self.assertEqual(diff_records(out, logic).added, [])

    def test_a_second_note_lands_in_tick_order(self):
        base = project_data(_goldens.path("midi-note-channel-2-logic"))       # one note at beat 2
        (have,) = read_midi(base)
        (want,) = read_midi(project_data(_goldens.path("midi-two-notes-logic")))
        (new,) = [e for e in want.events if e not in have.events]
        out = add_note(base, track=want.track, tick=new.tick, pitch=new.pitch, velocity=new.velocity, length=new.length, channel=new.channel)
        (ours,) = read_midi(out)
        self.assertEqual(ours.events, want.events)


@_goldens.needs("midi-write-ours", "midi-write-resave-logic")
class LogicResavedWriteTest(unittest.TestCase):
    def test_logic_kept_the_region_and_its_notes(self):
        (ours,), (logic,) = (read_midi(project_data(_goldens.path(k))) for k in ("midi-write-ours", "midi-write-resave-logic"))
        notes = lambda r: [[e.tick, e.channel, e.pitch, e.velocity, e.length] for e in r.events]  # noqa: E731
        self.assertEqual((ours.start, notes(ours)), (_goldens.fact("midi-write-ours", "start"), _goldens.fact("midi-write-ours", "notes")))
        self.assertEqual((logic.start, logic.name, notes(logic)), (ours.start, ours.name, notes(ours)))


@_goldens.needs("midi-names-ours", "midi-names-resave-logic")
class LogicResavedNamesTest(unittest.TestCase):
    """Region names of four and nine bytes, off the template's six."""

    DISPLAY_AT = 225            # past the name's end; Logic recomputes it on load

    def payloads(self, data: bytes, names) -> dict[str, bytes]:
        import struct
        from logicxkit.logic.services.stream import HEADER, project_records
        from logicxkit.logic.services.midi import NAME_AT
        out = {}
        for r in project_records(data):
            p = r.raw[HEADER:]
            if r.tag == b"qeSM" and len(p) > NAME_AT + 2:
                name = p[NAME_AT + 2:NAME_AT + 2 + struct.unpack_from("<H", p, NAME_AT)[0]].decode("latin-1")
                if name in names:
                    out[name] = p
        return out

    def test_logic_kept_the_regions_their_words_and_notes(self):
        from logicxkit.logic.services.midi_write import name_end
        ours, logic = (project_data(_goldens.path(k)) for k in ("midi-names-ours", "midi-names-resave-logic"))
        facts = _goldens.fact("midi-names-ours", "regions")
        for data in (ours, logic):
            self.assertEqual([[r.name, r.start, [[e.tick, e.pitch, e.velocity, e.length] for e in r.events]] for r in read_midi(data)], facts)
        names = [f[0] for f in facts]
        mine, theirs = self.payloads(ours, names), self.payloads(logic, names)
        self.assertEqual(sorted(mine), sorted(names))
        for name in names:
            a, b = bytearray(mine[name]), bytearray(theirs[name])
            for at in (8, name_end(a) + self.DISPLAY_AT):          # the sequence id Logic renumbers, and the display byte
                a[at:at + 1 if at > 8 else at + 4] = b[at:at + 1 if at > 8 else at + 4]
            self.assertEqual(bytes(b), bytes(a), name)


def _regions(data: bytes, count: int | None) -> dict[tuple[str, str], int]:
    return {(r.track, r.name): len(r.events) for r in read_midi(data, count)}


@_goldens.needs("sessionplayer-track-logic")
class OtherTrackAtTheSameTickTest(unittest.TestCase):
    def setUp(self):
        from logicxkit.logic.services.project import project_metadata
        p = _goldens.path("sessionplayer-track-logic")
        self.count = project_metadata(p).get("tracks")
        data = project_data(p)
        self.before = _regions(data, self.count)
        self.track = _goldens.fact("sessionplayer-track-logic", "track")
        self.other = next(k for k in self.before if k[0] != self.track)
        self.start = next(r.start for r in read_midi(data, self.count) if (r.track, r.name) == self.other)
        self.data, _ = add_region(data, track=self.track, start=self.start, length=3840 * 4, name="second", track_count=self.count)

    def _note(self, **kw) -> bytes:
        return add_note(self.data, track=self.track, tick=self.start + 960, pitch=60, velocity=100, length=480,
                        track_count=self.count, **kw)

    def test_the_note_lands_on_the_named_track_not_the_first_entry_at_that_tick(self):
        data = self._note(region_start=self.start)
        after = _regions(data, self.count)
        self.assertEqual(after[(self.track, "second")], 1)
        self.assertEqual(after[self.other], self.before[self.other])
        self.assertEqual(validate_project(data), [])

    def test_without_a_start_the_overlap_with_logics_region_is_refused(self):
        with self.assertRaisesRegex(ValueError, "inside 2 MIDI regions"):
            self._note()


@_goldens.needs("midi-empty-region-logic")
class NameLengthTest(unittest.TestCase):
    """The words after a region's name move with it: a name longer than the template's."""

    def test_length_and_track_follow_the_name(self):
        import struct
        from logicxkit.logic.services.stream import HEADER, project_records
        from logicxkit.logic.services.midi import NAME_AT
        from logicxkit.logic.services.sequence import sequences, triple_by_slot
        base = project_data(_goldens.path("midi-empty-region-logic"))
        start = 38400 + 8 * 3840
        out, report = add_region(base, track="Inst 1", start=start, length=3840 * 4, name="a longer name")
        records = project_records(out)
        q = records[triple_by_slot(sequences(records), report["slot"]).start].raw[HEADER:]
        n = struct.unpack_from("<H", q, NAME_AT)[0]
        end = NAME_AT + 2 + n + (n & 1)
        self.assertEqual(struct.unpack_from("<I", q, end + 60)[0], 3840 * 4)
        self.assertEqual(struct.unpack_from("<H", q, end + 204)[0], report["object_id"])
        out = add_note(out, track="Inst 1", tick=start + 960, pitch=60, velocity=100, length=240)
        q2 = project_records(out)[triple_by_slot(sequences(project_records(out)), report["slot"]).start].raw[HEADER:]
        self.assertEqual([struct.unpack_from("<I", q2, end + off)[0] for off in (123, 172, 192)], [84, 44, 1])
        self.assertEqual(q2[:end + 123], q[:end + 123])

    def test_a_track_that_is_not_a_software_instrument_is_refused_by_kind(self):
        base = project_data(_goldens.path("midi-empty-region-logic"))
        for track, kind in [("Audio 2", "an audio track (Audio 2)"), ("Stereo Out", "an output track (Output 1-2)")]:
            with self.subTest(track), self.assertRaisesRegex(ValueError, f"^'{track}' is {kind.replace('(', '[(]').replace(')', '[)]')}; "
                                                                        "a MIDI region goes only on a software instrument track$"):
                add_region(base, track=track, start=38400, length=3840)


if __name__ == "__main__":
    unittest.main()
