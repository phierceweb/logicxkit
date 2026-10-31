"""strip-silence, songs --breaks and split-sections rebuilt here from the fixtures and held to Logic's
re-save of the same writes: every audio entry and section as written, and every region record but for
the time and UUID a write mints and the payload ``+130`` Logic fills with the record's header owner."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _audio import THREE, band_playing, sound_gap_sound, tone, vocal_mic
from _cli import count, data, run, source

from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.audio_write import REGION_TIME_AT, REGION_UUID_FROM_END
from logicxkit.logic.services.regions.regions import ENTRY, song_container
from logicxkit.logic.services.song.arrangement import read_sections
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.utils.swiftrun import swift_available

STRIP = "writers-a01-strip-silence-ours-resave-logic"
SONGS = "writers-a02-songs-breaks-ours-resave-logic"
SECTIONS = "writers-a03-split-sections-ours-resave-logic"
PIECE_AT = 130


def write(command: str, bundle: str | Path, *rest, out: Path) -> Path:
    code, text = run(command, source(bundle), *rest, "--out", out)
    assert code == 0, text
    return out / source(bundle).name


def rows(bundle: str | Path) -> dict[tuple[str, int], tuple[bytes, bytes, int]]:
    """Each audio region by (track, start): its entry, its record with the time, UUID and ``+130``
    zeroed, and the record's header owner."""
    d, n = data(bundle), count(bundle)
    records = project_records(d)
    payload = records[song_container(records, arrange_run(records, n)).end].raw[HEADER:]
    out = {}
    for r in read_audio_regions(d, n):
        raw = bytearray(records[r.record].raw)
        raw[HEADER + REGION_TIME_AT:HEADER + REGION_TIME_AT + 8] = bytes(8)
        raw[len(raw) - REGION_UUID_FROM_END:len(raw) - REGION_UUID_FROM_END + 16] = bytes(16)
        raw[HEADER + PIECE_AT:HEADER + PIECE_AT + 2] = bytes(2)
        out[(r.track, r.start)] = (payload[r.at:r.at + ENTRY], bytes(raw), records[r.record].owner)
    return out


class ResaveCase(unittest.TestCase):
    KEY = ""

    @classmethod
    def build(cls, out: Path) -> Path:
        raise NotImplementedError

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.ours = cls.build(Path(tmp.name))

    def test_the_manifest_facts_are_the_file(self):
        regions = sorted(read_audio_regions(data(self.KEY), count(self.KEY)), key=lambda r: (r.track, r.start))
        self.assertEqual([{"track": r.track, "name": r.name, "start": r.start, "frames": r.frames, "piece": r.piece}
                          for r in regions], _goldens.fact(self.KEY, "regions"))
        self.assertEqual([{"name": s.name, "start": s.start, "length": s.length} for s in read_sections(data(self.KEY))],
                         _goldens.fact(self.KEY, "sections", []))

    def test_logic_resaves_every_entry_and_record_as_written(self):
        ours, logic = rows(self.ours), rows(self.KEY)
        self.assertEqual(sorted(ours), sorted(logic))
        for at in ours:
            with self.subTest(region=at):
                self.assertEqual(ours[at][:2], logic[at][:2])

    def test_logic_fills_each_piece_records_plus_130_with_its_header_owner(self):
        d, n = data(self.KEY), count(self.KEY)
        records = project_records(d)
        for r in read_audio_regions(d, n):
            raw = records[r.record].raw
            self.assertEqual(int.from_bytes(raw[HEADER + PIECE_AT:HEADER + PIECE_AT + 2], "little"), records[r.record].owner, r.name)

    def test_the_sections_are_logics(self):
        self.assertEqual(read_sections(data(self.ours)), read_sections(data(self.KEY)))


@_goldens.needs(THREE, STRIP, lacking=None if swift_available() else "the band-limited envelope runs through swift")
class StripSilenceResaveTest(ResaveCase):
    KEY = STRIP

    @classmethod
    def build(cls, out: Path) -> Path:
        take, vox, ref = sound_gap_sound(out / "take.wav"), vocal_mic(out / "vox.wav"), band_playing(out / "ref.wav")
        took = write("regions", THREE, "--audio", f"Audio 1:1:{take}", "--audio", f"Audio 2:1:{vox}",
                     "--audio", f"Audio 3:1:{ref}", out=out / "take")
        plain = write("strip-silence", took, "--track", "Audio 1", "--min-gap", "2", "--min-keep", "0.5", "--pad", "100",
                      "--fade", "20", out=out / "plain")
        return write("strip-silence", plain, "--track", "Audio 2", "--ref", "Audio 3", "--band", "300:3000",
                     "--min-gap", "1", "--min-keep", "0.5", "--pad", "100", out=out / "ref")


@_goldens.needs(THREE, SONGS)
class SongsBreaksResaveTest(ResaveCase):
    KEY = SONGS

    @classmethod
    def build(cls, out: Path) -> Path:
        bass, drums = sound_gap_sound(out / "bass.wav"), sound_gap_sound(out / "drums.wav")
        took = write("regions", THREE, "--audio", f"Audio 1:1:{bass}", "--audio", f"Audio 2:1:{drums}", out=out / "set")
        setlist = out / "setlist.txt"
        setlist.write_text("One\nTwo\nbreak\nThree\n")
        return write("songs", took, setlist, "--track", "Audio 1", "--track", "Audio 2", "--min-stop", "2", "--merge", "1",
                     "--min-song", "0.5", "--breaks", "break", out=out / "breaks")


@_goldens.needs(THREE, SECTIONS)
class SplitSectionsResaveTest(ResaveCase):
    KEY = SECTIONS

    @classmethod
    def build(cls, out: Path) -> Path:
        took = write("regions", THREE, "--audio", f"Audio 1:1:{tone(out / 'take.wav', 10)}", out=out / "take")
        sections = write("arrangement", took, "--add", "1:1:break", "--add", "2:2:Song", "--add", "4:1:break",
                         "--add", "5:1:Song 2", out=out / "sections")
        return write("split-sections", sections, "--section", "break", "--track", "Audio 1", "--to", "Audio 2",
                     out=out / "moved")


del ResaveCase
