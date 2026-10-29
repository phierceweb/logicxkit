"""The WAV chunk walk behind the envelope readers: odd chunks, pad bytes and a truncated file."""

import struct
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from logicxkit.logic.services.regions.wavfile import EXTENSIBLE, GUID_TAIL, IEEE_FLOAT, PCM, wav_data

FMT = struct.pack("<HHIIHH", 1, 1, 44100, 44100 * 3, 3, 24)


def extensible(code: int, channels: int = 2, bits: int = 24, *, tail: bytes = GUID_TAIL, cb: int = 22) -> bytes:
    block = channels * bits // 8
    return (struct.pack("<HHIIHH", EXTENSIBLE, channels, 44100, 44100 * block, block, bits)
            + struct.pack("<HHI", cb, bits, 3) + struct.pack("<H", code) + tail)


def chunk(tag: bytes, body: bytes, pad: bool = True) -> bytes:
    return tag + struct.pack("<I", len(body)) + body + (b"\0" if pad and len(body) % 2 else b"")


def riff(path: Path, *chunks: bytes) -> Path:
    body = b"WAVE" + b"".join(chunks)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


class WavDataTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_an_odd_chunk_before_data_is_stepped_over_with_or_without_its_pad(self):
        for pad in (True, False):
            path = riff(self.dir / f"odd{pad}.wav", chunk(b"fmt ", FMT), chunk(b"LIST", b"abc", pad), chunk(b"data", bytes(300)))
            self.assertEqual(wav_data(path).frames, 100)

    def test_a_pad_byte_with_too_little_after_it_for_a_chunk_ends_the_walk(self):
        path = riff(self.dir / "tail.wav", chunk(b"fmt ", FMT), chunk(b"junk", b"a") + bytes(7))
        with self.assertRaisesRegex(ValueError, "not a WAV with a fmt and a data chunk"):
            wav_data(path)

    def test_a_data_chunk_claiming_more_than_the_file_holds_is_named(self):
        path = riff(self.dir / "cut.wav", chunk(b"fmt ", FMT), b"data" + struct.pack("<I", 600) + bytes(300))
        with self.assertRaisesRegex(ValueError, "data chunk claims 600 bytes but the file ends 300 bytes short"):
            wav_data(path)

    def test_an_extensible_header_resolves_through_its_subformat(self):
        pcm = riff(self.dir / "ext24.wav", chunk(b"fmt ", extensible(PCM)), chunk(b"data", bytes(600)))
        self.assertEqual((wav_data(pcm).code, wav_data(pcm).channels, wav_data(pcm).bits, wav_data(pcm).frames), (PCM, 2, 24, 100))
        flt = riff(self.dir / "extf.wav", chunk(b"fmt ", extensible(IEEE_FLOAT, 1, 32)), chunk(b"data", bytes(400)))
        self.assertEqual((wav_data(flt).code, wav_data(flt).bits, wav_data(flt).frames), (IEEE_FLOAT, 32, 100))

    def test_each_header_refusal_names_its_cause(self):
        cases = (
            ("code", struct.pack("<HHIIHH", 0x55, 1, 44100, 44100 * 3, 3, 24), "format code 0x0055 is not PCM or IEEE float"),
            ("short", struct.pack("<HHIIHH", EXTENSIBLE, 1, 44100, 44100 * 3, 3, 24) + struct.pack("<H", 0),
             "WAVE_FORMAT_EXTENSIBLE with a 18-byte fmt chunk and cbSize 0"),
            ("cb", extensible(PCM, cb=20), "WAVE_FORMAT_EXTENSIBLE with a 40-byte fmt chunk and cbSize 20"),
            ("guid", extensible(PCM, tail=bytes(14)), "SubFormat GUID 0100" + "00" * 14 + " is not a KSDATAFORMAT_SUBTYPE"),
            ("sub", extensible(0x55), "SubFormat 0x0055 is not PCM or IEEE float"),
            ("block", struct.pack("<HHIIHH", PCM, 1, 44100, 44100 * 4, 4, 24), "24-bit, 1 channel(s) in 4-byte frames is not a WAV layout this reads"),
        )
        for name, fmt, why in cases:
            with self.subTest(name), self.assertRaisesRegex(ValueError, why.replace("(", "\\(").replace(")", "\\)")):
                wav_data(riff(self.dir / f"{name}.wav", chunk(b"fmt ", fmt), chunk(b"data", bytes(600))))

    def test_an_empty_data_chunk_reads_as_no_frames(self):
        self.assertEqual(wav_data(riff(self.dir / "empty.wav", chunk(b"fmt ", FMT), chunk(b"data", b""))).frames, 0)


if __name__ == "__main__":
    unittest.main()
