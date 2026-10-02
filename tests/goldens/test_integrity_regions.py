"""The write gate's region checks on Logic's own saves: the blank-born region goldens, each
corrupted the way a writer could, and a session Logic flexed."""

import unittest
from pathlib import Path

import _goldens
import _paths


REGION_SAVES = ("audio-one-region-logic", "audio-three-regions-logic", "audio-write-two-resave-logic",
                "midi-write-resave-logic", "midi-two-notes-logic", "midi-names-resave-logic",
                "sessionplayer-track-logic")


def _song(data: bytes):
    from logicxkit.logic.services.stream import project_records
    from logicxkit.logic.services.regions import song_container
    from logicxkit.logic.services.tracklist import arrange_run
    records = project_records(data)
    return records, song_container(records, arrange_run(records, None)).end


def _replaced(data: bytes, index: int, raw: bytes | None) -> bytes:
    from logicxkit.logic.services.stream import project_records, reassemble
    kept = [raw if i == index else r.raw for i, r in enumerate(project_records(data))]
    return reassemble(data, [k for k in kept if k is not None])


@_goldens.needs(*REGION_SAVES)
class LogicRegionSavesTest(unittest.TestCase):
    def test_logics_blank_born_saves_hold_every_region_invariant(self):
        from logicxkit.logic.services.integrity import structural_report
        from logicxkit.logicx import project_data
        for key in REGION_SAVES:
            with self.subTest(key):
                r = structural_report(project_data(_goldens.path(key)))
                self.assertTrue(r["regions"])
                self.assertEqual((r["dangling_files"], r["unregistered_slots"], r["marker_blocks"]),
                                 ({"entries": [], "records": [], "unfiled": [], "files": [], "doubled": [], "rba": []}, [], []))


@_goldens.needs("audio-one-region-logic", "audio-three-regions-logic", "midi-write-resave-logic")
class RegionRefusalTest(unittest.TestCase):
    def test_our_writers_leave_the_region_checks_clean(self):
        import math
        import struct
        import tempfile
        import wave

        from logicxkit.logic.services.audio_regions import read_audio_regions
        from logicxkit.logic.services.audio_write import add_audio_region
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.midi import read_midi
        from logicxkit.logic.services.midi_write import add_note, add_region
        from logicxkit.logicx import project_data
        base = project_data(_goldens.path("audio-one-region-logic"))
        (placed,) = read_audio_regions(base)
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp, "v040-gate.wav")
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(i / 20))) for i in range(4410)))
            imported, _ = add_audio_region(base, track=placed.track, start=placed.start + 3840, wav=wav,
                                           media_folder=Path(tmp, "Media"))
        self.assertEqual(regressions(base, imported), [])
        midi = project_data(_goldens.path("midi-write-resave-logic"))
        (inst,) = [r.track for r in read_midi(midi)]
        region, _ = add_region(midi, track=inst, start=38400 + 4 * 3840, length=3840)
        noted = add_note(region, track=inst, tick=38400 + 4 * 3840, pitch=60, velocity=100, length=480)
        self.assertEqual(regressions(midi, region), [])
        self.assertEqual(regressions(region, noted), [])

    def test_a_dropped_region_record_and_a_dropped_entry_are_refused_by_name(self):
        from logicxkit.logic.services.audio_regions import AUDIO_ENTRY, REGION_TAG
        from logicxkit.logic.services.stream import HEADER, project_records
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.recbuild import rec
        from logicxkit.logic.services.regions import ENTRY, TAIL, entry_offsets
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("audio-three-regions-logic"))
        last = max(i for i, r in enumerate(project_records(data)) if r.tag == REGION_TAG)
        found = regressions(data, _replaced(data, last, None))
        self.assertTrue(any(f.startswith("dangling_files: audio entries with no region record 0 -> 1: [(8, 0)]")
                            for f in found), found)
        records, end = _song(data)
        payload = records[end].raw[HEADER:]
        off = next(o for o in entry_offsets(payload) if payload[o] == AUDIO_ENTRY)
        cut = _replaced(data, end, rec(b"qSvE", records[end].raw, payload[:off] + payload[off + ENTRY:]))
        found = regressions(data, cut)
        self.assertTrue(any(f.startswith("lost_regions: 1 ") for f in found), found)
        cut_records, cut_end = _song(cut)
        self.assertEqual(len(cut_records[cut_end].raw[HEADER:]) % ENTRY, TAIL)
        self.assertFalse(any(f.startswith("marker_blocks") for f in found), found)

    def test_a_stray_file_record_and_moved_counters_are_refused(self):
        import struct

        from logicxkit.logic.services.audio_regions import AUDIO_ENTRY, ENTRY_ORDINAL_AT, FILE_TAG
        from logicxkit.logic.services.stream import HEADER, project_records, reassemble
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.recbuild import rec
        from logicxkit.logic.services.regions import TRACK_OBJECT_AT, entry_offsets
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("audio-three-regions-logic"))
        records = project_records(data)
        files = [i for i, r in enumerate(records) if r.tag == FILE_TAG]
        raws = [r.raw for r in records]
        raws.insert(files[0], records[files[-1]].raw)
        found = regressions(data, reassemble(data, raws))
        self.assertIn("dangling_files: file slots carried by two records 0 -> 1: [8]", found)

        records, end = _song(data)
        payload = records[end].raw[HEADER:]
        audio = [o for o in entry_offsets(payload) if payload[o] == AUDIO_ENTRY]
        a = audio[0]
        b = next(o for o in audio if payload[o + TRACK_OBJECT_AT:o + TRACK_OBJECT_AT + 2] != payload[a + TRACK_OBJECT_AT:a + TRACK_OBJECT_AT + 2])

        def with_counters(first: int, second: int) -> bytes:
            p = bytearray(payload)
            struct.pack_into("<I", p, a + ENTRY_ORDINAL_AT, first)
            struct.pack_into("<I", p, b + ENTRY_ORDINAL_AT, second)
            return _replaced(data, end, rec(b"qSvE", records[end].raw, bytes(p)))

        word = lambda o: struct.unpack_from("<I", payload, o + ENTRY_ORDINAL_AT)[0]  # noqa: E731
        found = regressions(data, with_counters(word(b), word(a)))
        self.assertTrue(any(f.startswith("dangling_files: 2 audio placement(s) now play another file") for f in found), found)
        self.assertTrue(any(f.startswith("moved_regions: 2 ") for f in found), found)
        found = regressions(data, with_counters(word(a), 4 * 999))
        self.assertIn("dangling_files: audio entries with no region record 0 -> 1: [(3996, 0)]", found)
        self.assertTrue(any(f.startswith("dangling_files: 1 audio placement(s) now play another file") for f in found), found)

    def test_two_regions_trading_tracks_at_one_tick_are_refused(self):
        import struct

        from logicxkit.logic.services.audio_regions import AUDIO_ENTRY, read_audio_regions
        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.integrity_regions import entry_key
        from logicxkit.logic.services.recbuild import rec
        from logicxkit.logic.services.regions import ENTRY, TRACK_OBJECT_AT, entry_offsets, sync_region_tracks
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("audio-three-regions-logic"))
        records, end = _song(data)
        payload = bytearray(records[end].raw[HEADER:])
        keys = {o: entry_key(payload[o:o + ENTRY]) for o in entry_offsets(payload) if payload[o] == AUDIO_ENTRY}
        (a, (obj_a, _, _)), (b, (obj_b, _, _)) = next(
            (x, y) for x in keys.items() for y in keys.items() if x[1][1] == y[1][1] and x[1][0] < y[1][0])
        struct.pack_into("<H", payload, a + TRACK_OBJECT_AT, obj_b)
        struct.pack_into("<H", payload, b + TRACK_OBJECT_AT, obj_a)
        swapped = sync_region_tracks(_replaced(data, end, rec(b"qSvE", records[end].raw, bytes(payload))))
        self.assertNotEqual([(r.track, r.name) for r in read_audio_regions(swapped)],
                            [(r.track, r.name) for r in read_audio_regions(data)])
        found = regressions(data, swapped)
        self.assertTrue(any(f.startswith("moved_regions: 2 ") for f in found), found)
        self.assertFalse(any(f.startswith("lost_regions") for f in found), found)

    def test_a_dropped_registry_record_leaves_the_region_slots_unregistered(self):
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.registry import GNOS_TAG
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("midi-write-resave-logic"))
        records, _end = _song(data)
        found = regressions(data, _replaced(data, next(i for i, r in enumerate(records) if r.tag == GNOS_TAG), None))
        self.assertTrue(any(f.startswith("unregistered_slots: ") and "has no registry entry" in f for f in found), found)

    def test_a_region_slot_taken_out_of_the_registry_is_refused_by_name(self):
        import struct

        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.midi import ENTRY_SLOT_AT, MIDI_ENTRY
        from logicxkit.logic.services.recbuild import rec
        from logicxkit.logic.services.regions import entry_offsets
        from logicxkit.logic.services.registry import GNOS_TAG, SLOT_TYPE, TIME_STRIDE, UUID_STRIDE, run_entries
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("midi-write-resave-logic"))
        records, end = _song(data)
        payload = records[end].raw[HEADER:]
        slot = next(struct.unpack_from("<I", payload, o + ENTRY_SLOT_AT)[0] for o in entry_offsets(payload)
                    if payload[o] == MIDI_ENTRY)
        at = next(i for i, r in enumerate(records) if r.tag == GNOS_TAG)
        g = bytearray(records[at].raw[HEADER:])
        for stride in (UUID_STRIDE, TIME_STRIDE):
            (off,) = [o for o, s in run_entries(g, SLOT_TYPE, stride) if s == slot]
            struct.pack_into("<I", g, off + 4, 4092)            # a slot word nothing uses
        found = regressions(data, _replaced(data, at, rec(GNOS_TAG, records[at].raw, bytes(g))))
        self.assertTrue(any(f.startswith("unregistered_slots: 1 ") and f"slot {slot} has no registry entry" in f
                            for f in found), found)


class FlexedSessionTest(unittest.TestCase):
    """A session Logic flexed and quantized: its marker blocks framed as the check reads them."""

    def setUp(self):
        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logic.services.regions import MARKER_KIND, MARKER_KIND_AT
        for project in sorted(p for d in ("legacy", "mixes") for p in (_paths.RESOURCES / d).rglob("*.logicx")):
            data = sorted(project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
            records, end = _song(data)
            payload = records[end].raw[HEADER:]
            blocks = [o for o in range(0, len(payload) - 96, 80) if payload[o + MARKER_KIND_AT] == MARKER_KIND]
            if blocks:
                self.data, self.records, self.end, self.block = data, records, end, blocks[0]
                return
        self.skipTest("no flexed session under resources/legacy or resources/mixes")

    def test_a_block_that_lost_its_mark_is_refused_by_name(self):
        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logic.services.integrity import regressions, structural_report
        from logicxkit.logic.services.recbuild import rec
        from logicxkit.logic.services.regions import MARKER_KIND_AT
        self.assertEqual(structural_report(self.data)["marker_blocks"], [])
        payload = bytearray(self.records[self.end].raw[HEADER:])
        payload[self.block + MARKER_KIND_AT] = 0
        found = regressions(self.data, _replaced(self.data, self.end, rec(b"qSvE", self.records[self.end].raw, bytes(payload))))
        self.assertTrue(any(f.startswith("marker_blocks: 1 ") and "0x88 bytes without the 0xAA mark" in f for f in found), found)

    def _with_segments(self, arrange) -> bytes:
        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logic.services.recbuild import rec
        from logicxkit.logic.services.regions import ENTRY, TAIL, entry_blocks
        payload = self.records[self.end].raw[HEADER:]
        segments = [payload[o:o + ENTRY * (1 + n)] for o, n in entry_blocks(payload)]
        self.assertEqual(sum(map(len, segments)), len(payload) - TAIL)
        body = b"".join(arrange(segments))
        return _replaced(self.data, self.end, rec(b"qSvE", self.records[self.end].raw, body + payload[-TAIL:]))

    def test_a_flexed_entry_stripped_of_its_blocks_is_refused(self):
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.regions import ENTRY

        def strip(segs):
            flexed = next(i for i, s in enumerate(segs) if len(s) > ENTRY)
            return segs[:flexed] + [segs[flexed][:ENTRY]] + segs[flexed + 1:]

        found = regressions(self.data, self._with_segments(strip))
        self.assertTrue(any(f.startswith("marker_blocks: 1 flexed entr(ies) lost their marker blocks") for f in found), found)

    def test_a_midi_entry_slipped_between_a_flexed_entry_and_its_blocks_is_refused(self):
        from logicxkit.logic.services.integrity import regressions
        from logicxkit.logic.services.midi import MIDI_ENTRY
        from logicxkit.logic.services.regions import ENTRY

        def slip(segs):
            midi = next((i for i, s in enumerate(segs) if s[0] == MIDI_ENTRY and len(s) == ENTRY), None)
            if midi is None:
                self.skipTest("the flexed session holds no MIDI entry")
            flexed = next(i for i, s in enumerate(segs) if len(s) > ENTRY)
            out = list(segs)
            out[flexed] = segs[flexed][:ENTRY] + segs[midi] + segs[flexed][ENTRY:]
            return out[:midi] + out[midi + 1:]

        found = regressions(self.data, self._with_segments(slip))
        self.assertTrue(any(f.startswith("marker_blocks: 1 flexed entr(ies) lost their marker blocks") for f in found), found)
        self.assertTrue(any(f.startswith("marker_blocks: 1 MIDI entr(ies) gained marker blocks") for f in found), found)


if __name__ == "__main__":
    unittest.main()
