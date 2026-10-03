"""An audio region's fades, in the last sixteen bytes of its song-container entry (`regions.py`),
measured on Logic's Region inspector edits of one region (2026-09-15, the `regions-a15-…` goldens):

    +65   u8    Fade-In type: 0 In, 1 Speed Up        +75   u8    Fade-Out curve, -99..99
    +67   u8    Fade-Out type: 0 or 3 Out, 4 X,       +76   u16   Fade-In, ms
                5 EqP, 6 X S (`regions-b*` goldens)   +79   u8    Fade-In curve
    +72   u16   Fade-Out, ms

A crossfade is the underneath region's fade-out with +66 = 0x20 on it and 0x80 on the region
over it (`region_params.py`); +68 changes when Logic edits the length and is kept as found.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

IN_TYPE_AT, OUT_TYPE_AT, OUT_MS_AT, OUT_CURVE_AT, IN_MS_AT, IN_CURVE_AT = 65, 67, 72, 75, 76, 79
CROSSFADE_AT = slice(66, 69)
CROSS_OUT, CROSS_IN = (66, 0x20), (66, 0x80)         # (offset, bit): the fade-out side, the fade-in side
IN_TYPES = {0: "in", 1: "speed-up"}
OUT_TYPES = {0: "out", 3: "out", 4: "x", 5: "eqp", 6: "xs"}
OUT_CODES = {"out": 0, "x": 4, "eqp": 5, "xs": 6}
OUT_CLEARED = 3                                        # what Logic wrote for Out on a region that had a crossfade
MAX_MS, MAX_CURVE = 0xFFFF, 99


@dataclass(frozen=True)
class Fade:
    in_ms: int = 0
    in_curve: int = 0
    in_type: int = 0
    out_ms: int = 0
    out_curve: int = 0
    out_type: str = "out"

    def __str__(self) -> str:
        parts = []
        if self.in_ms:
            parts.append(f"in {self.in_ms} ms" + (f" curve {self.in_curve}" if self.in_curve else "")
                         + (f" {IN_TYPES.get(self.in_type, self.in_type)}" if self.in_type else ""))
        kind = f" {self.out_type}" if self.out_type in OUT_CODES and self.out_type != "out" else ""
        if self.out_ms or kind:
            parts.append(f"out {self.out_ms} ms" + (f" curve {self.out_curve}" if self.out_curve else "") + kind)
        return ", ".join(parts)


def _curve(b: int) -> int:
    return b - 256 if b > 127 else b


def read_fade(entry: bytes) -> Fade:
    return Fade(struct.unpack_from("<H", entry, IN_MS_AT)[0], _curve(entry[IN_CURVE_AT]), entry[IN_TYPE_AT],
                struct.unpack_from("<H", entry, OUT_MS_AT)[0], _curve(entry[OUT_CURVE_AT]),
                OUT_TYPES.get(entry[OUT_TYPE_AT], str(entry[OUT_TYPE_AT])))


def crossfade_bytes(entry: bytes) -> bytes:
    return entry[CROSSFADE_AT]


def check_fade(fade: Fade) -> None:
    for ms in (fade.in_ms, fade.out_ms):
        if not 0 <= ms <= MAX_MS:
            raise ValueError(f"a fade of {ms} ms: 0 to {MAX_MS}")
    for curve in (fade.in_curve, fade.out_curve):
        if not -MAX_CURVE <= curve <= MAX_CURVE:
            raise ValueError(f"a fade curve of {curve}: -{MAX_CURVE} to {MAX_CURVE}")
    if fade.in_type not in IN_TYPES:
        raise ValueError(f"fade-in type {fade.in_type}: " + ", ".join(f"{k} {v}" for k, v in IN_TYPES.items()))
    if fade.out_type not in OUT_CODES and not fade.out_type.isdigit():
        raise ValueError(f"fade-out type {fade.out_type!r}: out, x, eqp or xs")


def with_fade(entry: bytes, fade: Fade) -> bytes:
    """``entry`` carrying ``fade``: the crossfade side bits and +68 are kept, Out on a crossfaded region is
    written as Logic wrote it (3), and an unmeasured type (digits from `read_fade`) leaves +67 as found."""
    check_fade(fade)
    e = bytearray(entry)
    struct.pack_into("<H", e, IN_MS_AT, fade.in_ms)
    struct.pack_into("<H", e, OUT_MS_AT, fade.out_ms)
    e[IN_CURVE_AT], e[OUT_CURVE_AT], e[IN_TYPE_AT] = fade.in_curve & 0xFF, fade.out_curve & 0xFF, fade.in_type
    code = OUT_CODES.get(fade.out_type)
    if code is not None:
        e[OUT_TYPE_AT] = OUT_CLEARED if code == 0 and e[CROSS_OUT[0]] & CROSS_OUT[1] else code
    return bytes(e)
