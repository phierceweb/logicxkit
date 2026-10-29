"""A split's link word sits after the region's name, so it is written from the record's end:
the parent's reads NO_LINK and the piece's first byte 1 wherever the name's length puts them, as
Logic's own split wrote them on a ten- and a twelve-byte name."""

import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, written
from _audio import THREE, sound_gap_sound

from logicxkit.logic.services.regions.audio_regions import REGION_NAME_AT, REGION_TAG, region_key
from logicxkit.logic.services.regions.region_edit import NO_LINK, SPLIT_LINK_FROM_END, split_region
from logicxkit.logic.services.regions.region_locate import listed, samples_per_tick_of
from logicxkit.logic.services.stream.stream import HEADER, project_records

SPLIT = "regions-a04-audio-split-logic"        # Logic's own split of 'v030-tone2' into it and 'v030-tone2.1'
FRAMES_AT = 22


def name_of(record: bytes) -> str:
    n = struct.unpack_from("<H", record, HEADER + REGION_NAME_AT)[0]
    return record[HEADER + REGION_NAME_AT + 2:HEADER + REGION_NAME_AT + 2 + n].decode()


def link_word(record: bytes) -> int:
    return struct.unpack_from("<I", record, len(record) - SPLIT_LINK_FROM_END)[0]


@_goldens.needs(SPLIT)
class LogicsOwnSplitTest(unittest.TestCase):
    def test_logic_wrote_the_link_word_eleven_bytes_from_the_end_on_both_records(self):
        records = [r.raw for r in project_records(data(SPLIT)) if r.tag == REGION_TAG]
        parent = next(r for r in records if name_of(r) == "v030-tone2")
        piece = next(r for r in records if name_of(r) == "v030-tone2.1")
        self.assertEqual((region_key(parent)[1], region_key(piece)[1]), (0, 1))
        self.assertEqual(SPLIT_LINK_FROM_END, 11)
        self.assertEqual(link_word(parent), NO_LINK)
        self.assertEqual(link_word(piece), 1)
        other = next(r for r in records if name_of(r) == "v030-tone")
        self.assertEqual(link_word(other), 0)


@_goldens.needs(THREE)
class SplitLinkByNameLengthTest(unittest.TestCase):
    def test_the_word_lands_from_the_end_whatever_the_names_length(self):
        for name in ("tw", "abc", "take", "twice", "v030-tone2", "a region name of some length"):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                wav = sound_gap_sound(out / f"{name}.wav")
                take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{wav}", out=out / "take")
                before, n = data(take), count(take)
                was = next(r.raw for r in project_records(before) if r.tag == REGION_TAG and name_of(r.raw) == name)
                loc = next(x for x in listed(before, n) if x.audio)
                spt = samples_per_tick_of(before, 44100)
                after = split_region(before, loc.number, loc.audio.start + round(loc.audio.frames / 2 / spt), spt=spt, track_count=n)
                records = [r.raw for r in project_records(after) if r.tag == REGION_TAG]
                parent = next(r for r in records if name_of(r) == name)
                piece = next(r for r in records if name_of(r) == f"{name}.1")
                self.assertEqual(len(parent), len(was))
                self.assertEqual(link_word(parent), NO_LINK)
                self.assertEqual(link_word(piece), 1)
                end = len(was) - SPLIT_LINK_FROM_END
                self.assertEqual(parent[HEADER + FRAMES_AT + 4:end], was[HEADER + FRAMES_AT + 4:end])      # nothing else after the frames moved
                self.assertEqual(parent[end + 4:], was[end + 4:])

    def test_a_piece_of_a_piece_gets_the_word_1_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            take = written(self, "regions", THREE, "--audio", f"Audio 1:1:{sound_gap_sound(out / 'take.wav')}", out=out / "take")
            before, n = data(take), count(take)
            loc = next(x for x in listed(before, n) if x.audio)
            spt = samples_per_tick_of(before, 44100)
            once = split_region(before, loc.number, loc.audio.start + round(loc.audio.frames / 3 / spt), spt=spt, track_count=n)
            piece = next(x for x in listed(once, n) if x.audio and x.audio.name == "take.1")
            twice = split_region(once, piece.number, piece.audio.start + round(piece.audio.frames / 2 / spt), spt=spt, track_count=n)
            words = {name_of(r.raw): link_word(r.raw) for r in project_records(twice) if r.tag == REGION_TAG}
            self.assertEqual((words["take"], words["take.1"], words["take.2"]), (NO_LINK, NO_LINK, 1))


if __name__ == "__main__":
    unittest.main()
