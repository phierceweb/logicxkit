"""Fixtures for the drum-quantize goldens: click tracks as audio files, and readers of the
marker blocks, RBA sequences, registry pairs and entry slots a quantized project holds."""

import math
import struct
import wave
from pathlib import Path

from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.flexmarkers import HIT, MARKER
from logicxkit.logic.services.stream.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.stream.recbuild import rec
from logicxkit.logic.services.regions.regions import ENTRY, TAIL, entry_blocks, entry_offsets, song_container
from logicxkit.logic.services.stream.registry import GNOS_TAG, SLOT_TYPE, TIME_STRIDE, UUID_STRIDE, run_entries
from logicxkit.logic.services.arrange.tracklist import arrange_run

RATE = 44100
KICK, SNARE = "Audio 1", "Audio 2"


def clicks(path: Path, beats: list[float], bpm: float, seconds: float = 6.0) -> Path:
    """A 24-bit mono file with a decaying burst at each beat position."""
    x = [0.0] * int(seconds * RATE)
    spb = RATE * 60 / bpm
    for beat in beats:
        at = int(beat * spb)
        for i in range(int(0.05 * RATE)):
            if at + i < len(x):
                x[at + i] += 0.8 * math.exp(-i / (0.003 * RATE)) * (1 if i % 2 == 0 else -0.6) * min(i, 2) / 2
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(RATE)
        w.writeframes(b"".join(max(-8388607, min(8388607, int(v * 8388607))).to_bytes(3, "little", signed=True) for v in x))
    return path


def marker_blocks(data: bytes) -> dict[int, list[bytes]]:
    """object id -> the marker blocks after its entry."""
    records = project_records(data)
    song = song_container(records, arrange_run(records, None))
    payload = records[song.end].raw[HEADER:]
    body = payload[:len(payload) - TAIL]
    offsets = entry_offsets(payload)
    out = {}
    for k, off in enumerate(offsets):
        end = offsets[k + 1] if k + 1 < len(offsets) else len(body)
        oid = struct.unpack_from("<H", body, off + 16)[0]
        out[oid] = [body[i:i + MARKER] for i in range(off + ENTRY, end, MARKER)]
    return out


def rba_headers(data: bytes) -> list[bytes]:
    return [r.raw[HEADER:] for r in project_records(data) if r.tag == b"qeSM" and r.raw[HEADER + 18:HEADER + 30] == b"RBA Sequence"]


def slot_pairs(data: bytes) -> list[int]:
    (g,) = [r.raw[HEADER:] for r in project_records(data) if r.tag == GNOS_TAG]
    return [len(run_entries(g, SLOT_TYPE, stride)) for stride in (UUID_STRIDE, TIME_STRIDE)]


def song_end(data: bytes) -> int:
    records = project_records(data)
    return song_container(records, arrange_run(records, None)).end


def without_rba_bit(data: bytes) -> bytes:
    """Every flexed entry's +48 bit 7 cleared, as Logic leaves it on most entries naming a triple."""
    records = project_records(data)
    end = song_end(data)
    payload = bytearray(records[end].raw[HEADER:])
    for off, n in entry_blocks(bytes(payload)):
        if n:
            payload[off + 48] &= 0x7F
    raws = [r.raw for r in records]
    raws[end] = rec(b"qSvE", raws[end], bytes(payload))
    return reassemble(data, raws)


def anchors_only(data: bytes, track: str) -> bytes:
    """``track``'s region keeps its entry and its two anchors, its hit blocks gone: the first
    quantize's form for every member but the reference."""
    oid = next(r.object_id for r in read_audio_regions(data) if r.track == track)
    records = project_records(data)
    end = song_end(data)
    payload = records[end].raw[HEADER:]
    body, tail = bytearray(payload[:len(payload) - TAIL]), payload[len(payload) - TAIL:]
    for off, n in entry_blocks(payload):
        if struct.unpack_from("<H", payload, off + 16)[0] == oid and n > 2:
            first, last = off + ENTRY, off + ENTRY + (n - 1) * MARKER
            body = body[:first + MARKER] + body[last:]
            break
    raws = [r.raw for r in records]
    raws[end] = rec(b"qSvE", raws[end], bytes(body) + tail)
    return reassemble(data, raws)


def entry_slots(data: bytes) -> list[int]:
    records = project_records(data)
    payload = records[song_end(data)].raw[HEADER:]
    return [struct.unpack_from("<I", payload, off + 32)[0] for off, n in entry_blocks(payload) if n]


def hit_targets(blocks: list[bytes]) -> list[float]:
    return [struct.unpack_from("<i", b, 12)[0] + struct.unpack_from("<H", b, 10)[0] / 0x10000 for b in blocks if b[6] == HIT]
