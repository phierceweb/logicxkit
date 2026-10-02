"""Writing an audio region from a WAV, held to Logic's own imports of the same-shaped files."""

import math
import struct
import tempfile
import unittest
import uuid
import wave
from collections import Counter
from pathlib import Path

import _goldens
from logicxkit.logic.services.audio_regions import (
    AUDIO_ENTRY, ENTRY_ORDINAL_AT, FILE_TAG, OFFSET_AT, PATH_AT, REGION_TAG, SIZE_AT, magic_at, read_audio_files,
    read_audio_regions)
from logicxkit.logic.services.audio_write import LINK_AT, ORDINAL_AT, _register, add_audio_region, wav_info
from logicxkit.logic.services.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.recbuild import rec, slot_of, with_slot
from logicxkit.logic.services.regions import ENTRY, TAIL, entry_offsets, song_container
from logicxkit.logic.services.registry import TIME_STRIDE, UUID_STRIDE, run_entries
from logicxkit.logic.services.tracklist import arrange_run
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

UNSIZED = (b"gnoS", b"qeSM", b"MroC", b"OCuA", b"UCuA")     # grow, shrink or carry the name on any load
# From the LFUA magic: the folder, and the facts of the copy Logic wrote of the WAV (it adds chunks).
COPY_FIELDS = ((PATH_AT, 256), (SIZE_AT, 4), (OFFSET_AT, 4), (530, 2))


def tone(path: Path, seconds: float = 1.0, rate: int = 44100, channels: int = 1) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate))) * channels for i in range(int(rate * seconds))))
    return path


def shape(data: bytes) -> Counter:
    return Counter((r.tag, None if r.tag in UNSIZED else len(r.raw)) for r in project_records(data))


def payloads(data: bytes, tag: bytes) -> list[bytes]:
    return [r.raw[HEADER:] for r in project_records(data) if r.tag == tag]


def file_bodies(data: bytes) -> list[bytes]:
    out = []
    for p in payloads(data, FILE_TAG):
        body, m = bytearray(p), magic_at(p)
        for at, size in COPY_FIELDS:
            body[m + at:m + at + size] = bytes(size)
        out.append(bytes(body))
    return out


def region_bodies(data: bytes) -> list[bytes]:
    """Region payloads without the fresh UUID and the time at `+42`."""
    return [p[:42] + p[50:-47] + p[-31:] for p in payloads(data, REGION_TAG)]


def region_clocks(data: bytes) -> list[int]:
    """Each region's `+42` time less its UUID's timestamp."""
    return [(struct.unpack_from("<Q", p, 42)[0] - uuid.UUID(bytes=p[-47:-31]).time) % 2**64 for p in payloads(data, REGION_TAG)]


def song_events(data: bytes) -> bytes:
    records = project_records(data)
    return records[song_container(records, arrange_run(records, None)).end].raw[HEADER:]


def song_entries(data: bytes) -> list[bytes]:
    """The song container's entries, flags included, sorted (Logic's order at a shared tick is not
    measured), then its tail."""
    p = song_events(data)
    return sorted(p[off:off + ENTRY] for off in entry_offsets(p)) + [p[-TAIL:]]


def audio_words(data: bytes) -> list[int]:
    p = song_events(data)
    return sorted(struct.unpack_from("<I", p, off + ENTRY_ORDINAL_AT)[0] for off in entry_offsets(p)
                  if struct.unpack_from("<H", p, off)[0] == AUDIO_ENTRY)


def registry_block(data: bytes) -> list[tuple[int, bytes]]:
    """(offset, kind+id) of the 0x0b entries stacked directly before the first 0x0c entry, per stride."""
    g = payloads(data, b"gnoS")[0]
    out = []
    for stride in (UUID_STRIDE, TIME_STRIDE):
        at = run_entries(g, 0x0C, stride)[0][0]
        while struct.unpack_from("<I", g, at - stride)[0] == 0x0B:
            at -= stride
            out.append((at, g[at:at + 8]))
    return sorted(out)


def headers(data: bytes) -> list[tuple[bytes, int]]:
    return [(r.tag, slot_of(r.raw)) for r in project_records(data) if r.tag in (FILE_TAG, REGION_TAG)]


def regions(data: bytes) -> list[tuple]:
    return sorted((r.track, r.name, r.start, r.frames, r.file.name, r.file.frames, r.file.rate, r.file.channels) for r in read_audio_regions(data))


class LikeLogic:
    def assert_like(self, out: bytes, logic: bytes):
        self.assertEqual(validate_project(out), [])
        self.assertEqual(shape(out), shape(logic))
        self.assertEqual(regions(out), regions(logic))
        self.assertEqual(headers(out), headers(logic))
        self.assertEqual(file_bodies(out), file_bodies(logic))
        self.assertEqual(region_bodies(out), region_bodies(logic))
        self.assertEqual(region_clocks(out), region_clocks(logic))
        self.assertEqual(song_entries(out), song_entries(logic))
        self.assertEqual(registry_block(out), registry_block(logic))


class WavInfoTest(unittest.TestCase):
    def test_a_canonical_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = wav_info(tone(Path(tmp, "v030-tone.wav")))
            self.assertEqual((info.frames, info.rate, info.channels, info.bits, info.data_offset, info.format), (44100, 44100, 1, 16, 44, "WAVE"))
            self.assertEqual(info.size, 44 + 88200)


@_goldens.needs("midi-write-resave-logic", "audio-one-region-logic")
class ImportTest(LikeLogic, unittest.TestCase):
    def test_our_import_reads_like_logics(self):
        base = project_data(_goldens.path("midi-write-resave-logic"))
        logic = project_data(_goldens.path("audio-one-region-logic"))
        (want_file,), (want_region,) = read_audio_files(logic), read_audio_regions(logic)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp, "Media", "Audio Files")
            media.mkdir(parents=True)
            out, report = add_audio_region(base, track=want_region.track, start=want_region.start,
                                           wav=tone(Path(tmp, "v030-tone.wav")), media_folder=media)
            self.assertTrue((media / "v030-tone.wav").is_file())
        (f,), (r,) = read_audio_files(out), read_audio_regions(out)
        self.assertEqual((f.name, f.frames, f.rate, f.channels, f.bits, f.format, f.data_offset), (want_file.name, want_file.frames, want_file.rate, want_file.channels, want_file.bits, want_file.format, want_file.data_offset))
        self.assertEqual((r.track, r.name, r.start, r.frames), (want_region.track, want_region.name, want_region.start, want_region.frames))
        self.assert_like(out, logic)


@_goldens.needs("audio-one-region-logic", "audio-three-regions-logic", "midi-write-resave-logic")
class SecondAndThirdImportTest(LikeLogic, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.media = Path(self.tmp.name, "Media", "Audio Files")
        self.logic = project_data(_goldens.path("audio-three-regions-logic"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_imports_read_like_logics(self):
        data = project_data(_goldens.path("audio-one-region-logic"))
        placed = {r.file.name: r for r in read_audio_regions(self.logic)}
        wavs = (tone(Path(self.tmp.name, "v030-tone_1.wav")), tone(Path(self.tmp.name, "v030-tone2.wav"), seconds=2, channels=2))
        for wav, ordinal in zip(wavs, (1, 2), strict=True):
            data, report = add_audio_region(data, track=placed[wav.name].track, start=placed[wav.name].start, wav=wav, media_folder=self.media)
            self.assertEqual(report["ordinal"], ordinal)
        self.assertEqual(audio_words(data), [0, 4, 8])
        self.assert_like(data, self.logic)
        tails = payloads(data, REGION_TAG)
        self.assertEqual({p[-31:-27] for p in tails}, {b"\xff" * 4})
        self.assertEqual(len({p[-47:-31] for p in tails}), 3)

    def refused(self, data: bytes, message: str = "measured on.*import it in Logic", wav: str = "v030-tone3.wav"):
        with self.assertRaisesRegex(ValueError, message):
            add_audio_region(data, track="Audio 2", start=38400, wav=tone(Path(self.tmp.name, wav)), media_folder=self.media)
        self.assertFalse(self.media.exists())

    def replaced(self, index: int, edit, data: bytes | None = None) -> bytes:
        """``data`` (the three-region project) with record ``index`` edited, or dropped when ``edit`` returns None."""
        data = data or self.logic
        records = project_records(data)
        kept = [edit(r.raw) if i == index else r.raw for i, r in enumerate(records)]
        return reassemble(data, [raw for raw in kept if raw is not None])

    def nth(self, tag: bytes, k: int, data: bytes | None = None) -> int:
        return [i for i, r in enumerate(project_records(data or self.logic)) if r.tag == tag][k]

    def file_field(self, k: int, at: int, value: int) -> bytes:
        def edit(raw):
            body = bytearray(raw)
            struct.pack_into("<I", body, HEADER + magic_at(raw[HEADER:]) + at, value)
            return bytes(body)
        return self.replaced(self.nth(FILE_TAG, k), edit)

    def gnos(self, edit, data: bytes | None = None) -> bytes:
        return self.replaced(self.nth(b"gnoS", 0, data), lambda raw: rec(b"gnoS", raw, edit(raw[HEADER:])), data)

    def test_a_gap_in_the_entry_counters_is_refused(self):
        def edit(raw):
            body = bytearray(raw)
            (top,) = [off for off in entry_offsets(raw[HEADER:]) if struct.unpack_from("<I", raw, HEADER + off + ENTRY_ORDINAL_AT)[0] == 8]
            struct.pack_into("<I", body, HEADER + top + ENTRY_ORDINAL_AT, 12)
            return bytes(body)
        records = project_records(self.logic)
        self.refused(self.replaced(song_container(records, arrange_run(records, None)).end, edit))

    def test_a_broken_link_chain_is_refused(self):
        self.refused(self.file_field(0, LINK_AT, 8))

    def test_an_ordinal_out_of_file_order_is_refused(self):
        self.refused(self.file_field(1, ORDINAL_AT, 1))

    def test_a_file_header_slot_out_of_order_is_refused(self):
        self.refused(self.replaced(self.nth(FILE_TAG, 2), lambda raw: with_slot(raw, 12)))

    def test_a_region_header_slot_out_of_order_is_refused(self):
        self.refused(self.replaced(self.nth(REGION_TAG, 2), lambda raw: with_slot(raw, 12)))

    def test_a_missing_region_record_is_refused(self):
        self.refused(self.replaced(self.nth(REGION_TAG, 2), lambda raw: None))

    def test_a_registry_run_short_of_a_region_is_refused(self):
        def edit(g):
            at = run_entries(g, 0x0B, TIME_STRIDE)[-1][0]
            return g[:at] + g[at + TIME_STRIDE:]
        self.refused(self.gnos(edit))

    def test_a_registry_run_with_an_extra_entry_is_refused(self):
        def edit(g):
            at = run_entries(g, 0x0B, UUID_STRIDE)[-1][0] + UUID_STRIDE
            return g[:at] + struct.pack("<II", 0x0B, 12) + bytes(UUID_STRIDE - 8) + g[at:]
        self.refused(self.gnos(edit))

    def test_a_registry_entry_without_regions_is_refused(self):
        self.refused(self.gnos(lambda g: _register(g, word=0), project_data(_goldens.path("midi-write-resave-logic"))))

    def test_a_file_name_the_project_already_holds_is_refused(self):
        self.refused(project_data(_goldens.path("audio-one-region-logic")), "already holds.*v030-tone.wav", wav="v030-tone.wav")


@_goldens.needs("audio-write-two-ours", "audio-write-two-resave-logic")
class LogicResavedImportsTest(unittest.TestCase):
    def test_logic_kept_every_audio_record_of_two_imports(self):
        ours, logic = (project_data(_goldens.path(k)) for k in ("audio-write-two-ours", "audio-write-two-resave-logic"))
        facts = [tuple(r) for r in _goldens.fact("audio-write-two-ours", "regions")]
        for data in (ours, logic):
            self.assertEqual([(r.track, r.name, r.start, r.frames, r.file.name, r.file.channels) for r in read_audio_regions(data)], facts)
            self.assertEqual(validate_project(data), [])
        self.assertEqual(payloads(logic, REGION_TAG), payloads(ours, REGION_TAG))
        self.assertEqual(file_bodies(logic), file_bodies(ours))
        self.assertEqual(headers(logic), headers(ours))
        self.assertEqual(song_entries(logic), song_entries(ours))
        self.assertEqual([k for _at, k in registry_block(logic)], [k for _at, k in registry_block(ours)])


if __name__ == "__main__":
    unittest.main()
