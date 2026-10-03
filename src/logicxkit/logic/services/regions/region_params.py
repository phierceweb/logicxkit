"""An audio region's Gain, Delay, Transpose, Fine Tune and Reverse, and a region's colour — the
Region inspector's rows beyond the fades — in its song-container entry (`regions.py`) and its
records, measured on Logic's own edits of one blank-born project (2026-09-15, the `regions-b*`
goldens); `region_params_write.py` writes them and the crossfade:

    +48   bits 0-4  gain: a signed 5-bit remainder      +52   i8    gain: tens (dB = 10·tens + remainder)
    +48   bit 5     Reverse                             +53   i8    Transpose, semitones
    +50   i8        Fine Tune, cents                    +60   i32   Delay, ticks

Logic truncates the tens toward zero (−17 dB is −1, −7). Transpose on an unflexed region made Logic
switch the track to Flex Pitch (two marker blocks after the entry, the channel's flex bytes, +48
bit 7); the writer sets the entry's field alone. A region's colour is a palette index — the
`gRuA` record's payload `+3` for audio, the `qeSM`'s ninth byte past the padded name for MIDI —
and a region born on a track carries the track's.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

GAIN_AT, FINE_AT, GAIN_TENS_AT, TRANSPOSE_AT, DELAY_AT = 48, 50, 52, 53, 60
REVERSE_BIT, GAIN_MASK = 0x20, 0x1F
REGION_COLOUR_AT = 3
GAIN_RANGE, TRANSPOSE_RANGE, FINE_RANGE, DELAY_RANGE = 30, 24, 50, 999_999
MS_PER_MINUTE = 60_000


@dataclass(frozen=True)
class RegionParams:
    gain: int = 0            # dB
    delay: int = 0           # ticks
    transpose: int = 0       # semitones
    fine_tune: int = 0       # cents
    reverse: bool = False

    def __str__(self) -> str:
        parts = [f"gain {self.gain:+d} dB" if self.gain else "", f"delay {self.delay:+d}" if self.delay else "",
                 f"transpose {self.transpose:+d}" if self.transpose else "", f"fine {self.fine_tune:+d}" if self.fine_tune else "",
                 "reverse" if self.reverse else ""]
        return ", ".join(p for p in parts if p)


def _i8(b: int) -> int:
    return b - 256 if b > 127 else b


def _sext5(b: int) -> int:
    return b - 32 if b > 15 else b


def read_params(entry: bytes) -> RegionParams:
    return RegionParams(10 * _i8(entry[GAIN_TENS_AT]) + _sext5(entry[GAIN_AT] & GAIN_MASK),
                        struct.unpack_from("<i", entry, DELAY_AT)[0], _i8(entry[TRANSPOSE_AT]), _i8(entry[FINE_AT]),
                        bool(entry[GAIN_AT] & REVERSE_BIT))


RANGES = (("gain", "gain", GAIN_RANGE), ("transpose", "transpose", TRANSPOSE_RANGE),
          ("fine tune", "fine_tune", FINE_RANGE), ("delay", "delay", DELAY_RANGE))


def check_params(p: RegionParams, had: RegionParams | None = None) -> None:
    """Each field outside Logic's range, except one ``had`` already holds: a single-field edit writes
    the rest back as read."""
    for name, attr, limit in RANGES:
        value = getattr(p, attr)
        if not -limit <= value <= limit and (had is None or value != getattr(had, attr)):
            raise ValueError(f"a {name} of {value}: -{limit} to {limit}")


def with_params(entry: bytes, p: RegionParams) -> bytes:
    """``entry`` carrying ``p``; the flex bit and every other byte are kept."""
    check_params(p, read_params(entry))
    tens = int(p.gain / 10)
    e = bytearray(entry)
    e[GAIN_AT] = (e[GAIN_AT] & ~(GAIN_MASK | REVERSE_BIT)) | ((p.gain - 10 * tens) & GAIN_MASK) | (REVERSE_BIT if p.reverse else 0)
    e[GAIN_TENS_AT], e[TRANSPOSE_AT], e[FINE_AT] = tens & 0xFF, p.transpose & 0xFF, p.fine_tune & 0xFF
    struct.pack_into("<i", e, DELAY_AT, p.delay)
    return bytes(e)
