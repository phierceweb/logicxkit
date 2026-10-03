"""Flex markers and the per-region quantize state — what Logic 12.3.1 writes on an audio
quantize (measured on a drum take, 2026-09-13; the logic README, "Flex and audio quantize").

A flexed region's 80-byte song-container entry is followed by 80-byte **marker blocks**
(byte 7 = 0xAA): `+0` i32 the source in samples from the region start, `+6` the kind (`07`
start anchor one beat before the region, `03` end anchor at its length plus 1024, `01` a
hit, `05` a hit with Quantize Off), `+10` u16 the target's fraction, `+12` i32 the target in
ticks (`PPQ` per quarter), `0x88` at `+23`, `+39`, `+55`, `+71`. A quantized entry has `+13` = 1, `+15` bit 4 (flex on),
`+48` bit 7 and `+32` = the slot of its **RBA Sequence** triple (packaged
`rba-sequence-12.3.1.json`): `+8` id, `+88` u16 fraction and `+90` u32 length in ticks,
`+102` i16 the Quantize value (0 Off; 1/d is -2·(7 - log2 d), measured for 1/4 to 1/32),
`+234` the track object, `+242` the arrange row negated. Across Logic's saves only `+32` marks
a quantized entry reliably.
"""

from __future__ import annotations

import json
import math
import struct

from ....utils.data import data_file
from ..song.events import PPQ
from ..stream.stream import HEADER
from ..stream.recbuild import with_owner, with_slot
from .regions import ENTRY
from ..stream.sequence import Triple, sequences

_DATA = "rba-sequence-12.3.1.json"
MARKER = 80
START, END, HIT, OFF = 0x07, 0x03, 0x01, 0x05
KIND_AT, KIND_MARK = 6, 0xAA
SOURCE_AT, FRACTION_AT, TARGET_AT = 0, 10, 12
END_TAIL = 1024                                   # samples past the region's last frame
ENTRY_QUANTIZED_AT, ENTRY_FLAGS_AT, ENTRY_SLOT_AT, ENTRY_RBA_AT = 13, 15, 32, 48
FLEX_BIT, RBA_BIT = 0x10, 0x80
RBA_ID_AT, RBA_LENGTH_AT, RBA_CODE_AT, RBA_OBJECT_AT, RBA_ROW_AT = 8, 88, 102, 234, 242
RBA_NAME_AT, RBA_NAME = 18, b"RBA Sequence"
GRIDS = (4, 8, 16, 32)


def _template() -> dict[str, bytes]:
    d = json.loads(data_file("logic", _DATA).read_text())
    return {k: bytes.fromhex(v) for k, v in d.items() if k != "_"}


def samples_per_tick(samples_per_beat: float) -> float:
    return samples_per_beat / PPQ


def ticks_of(samples: float, spt: float) -> tuple[int, int]:
    """(tick word, u16 fraction) as Logic stores a non-integer tick: whole ticks, then the
    part of the next one in 65536ths."""
    value = samples / spt
    whole = math.floor(value)
    return whole, min(0xFFFF, round((value - whole) * 0x10000))


def marker_block(source: int, target: int, kind: int, fraction: int = 0) -> bytes:
    b = bytearray(_template()["hit"])
    b[:16] = bytes(16)
    struct.pack_into("<i", b, SOURCE_AT, source)
    b[KIND_AT], b[KIND_AT + 1] = kind, KIND_MARK
    struct.pack_into("<H", b, FRACTION_AT, fraction)
    struct.pack_into("<i", b, TARGET_AT, target)
    return bytes(b)


def block_fields(block: bytes) -> tuple[int, int, int, int]:
    """(source samples, kind, target ticks, target fraction) of a marker block."""
    return (struct.unpack_from("<i", block, SOURCE_AT)[0], block[KIND_AT],
            struct.unpack_from("<i", block, TARGET_AT)[0], struct.unpack_from("<H", block, FRACTION_AT)[0])


def anchors(*, frames: int, samples_per_beat: float) -> tuple[bytes, bytes]:
    """The start anchor one beat before the region and the end anchor at its last frame;
    only an unquantized flexed region keeps its end anchor ``END_TAIL`` samples later."""
    ticks, fraction = ticks_of(frames, samples_per_tick(samples_per_beat))
    return (marker_block(-round(samples_per_beat), -PPQ, START),
            marker_block(frames, ticks, END, fraction))


def snap(source: int, spt: float, grid: int) -> int:
    """The grid tick nearest ``source`` (1/``grid`` notes; PPQ * 4 / grid ticks apart)."""
    step = PPQ * 4 // grid
    return round(source / spt / step) * step


def quantize_code(grid: int) -> int:
    if grid == 0:
        return 0
    if grid not in GRIDS:
        raise ValueError(f"a measured grid: 1/{', 1/'.join(map(str, GRIDS[:-1]))} or 1/{GRIDS[-1]}, or 0 for Off")
    return -2 * (7 - int(math.log2(grid)))


def grid_of(code: int) -> int | None:
    """The 1/d grid ``quantize_code`` gives ``code``; 0 for Off, None for a value it never writes."""
    if code == 0:
        return 0
    grid = 2 ** (7 + code // 2) if code % 2 == 0 and -14 <= code < 0 else None
    return grid if grid in GRIDS else None


def rba_sequences(records) -> dict[int, Triple]:
    """Slot -> the RBA Sequence triple in it."""
    return {t.slot: t for t in sequences(records)
            if records[t.start].raw[HEADER + RBA_NAME_AT:HEADER + RBA_NAME_AT + len(RBA_NAME)] == RBA_NAME}


def flexed_entry(entry: bytes, *, slot: int) -> bytes:
    """``entry`` marked flexed and quantized, its sequence slot pointing at the RBA triple."""
    e = bytearray(entry[:ENTRY])
    e[ENTRY_QUANTIZED_AT] = 1
    e[ENTRY_FLAGS_AT] |= FLEX_BIT
    e[ENTRY_RBA_AT] |= RBA_BIT
    struct.pack_into("<I", e, ENTRY_SLOT_AT, slot)
    return bytes(e)


def hit_blocks(hits: list[int], *, spt: float, grid: int) -> list[bytes]:
    """One block per hit (samples from the region start), targets on the grid, ascending;
    hits sharing a target keep the one nearest it, as Logic does on load."""
    nearest: dict[int, int] = {}
    for h in sorted(hits):
        target = snap(h, spt, grid)
        if target not in nearest or abs(h / spt - target) < abs(nearest[target] / spt - target):
            nearest[target] = h
    return [marker_block(h, target, HIT) for target, h in sorted(nearest.items())]


def rba_triple(*, seq_id: int, slot: int, length_ticks: int, fraction: int, code: int,
               track_object: int, row: int) -> tuple[bytes, bytes, bytes]:
    """The RBA Sequence records (qeSM, karT, qSvE) for one region."""
    t = _template()
    p = bytearray(t["qesm_payload"])
    struct.pack_into("<I", p, RBA_ID_AT, seq_id)
    struct.pack_into("<H", p, RBA_LENGTH_AT, fraction)
    struct.pack_into("<I", p, RBA_LENGTH_AT + 2, length_ticks)
    struct.pack_into("<h", p, RBA_CODE_AT, code)
    struct.pack_into("<I", p, RBA_OBJECT_AT, track_object)
    struct.pack_into("<h", p, RBA_ROW_AT, -row)
    qesm = with_slot(t["qesm_header"] + bytes(p), slot)
    marker = with_slot(t["marker"], slot)
    qsve = with_owner(with_slot(t["qsve_header"] + t["qsve_tail"], slot), seq_id)
    assert len(qesm) - HEADER == len(p)
    return qesm, marker, qsve
