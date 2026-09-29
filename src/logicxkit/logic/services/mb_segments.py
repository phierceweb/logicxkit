"""The spectrum laid out as at most N stretches for a multiband target (`translate_mb`): each
stretch a source band or none, slivers joined to a neighbour, past the count the narrowest merged."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .translate_mb import MBand

SLIVER = 2 / 3                       # octaves: an empty stretch narrower than this is nobody's band


def _hz(f: float) -> str:
    return f"{f / 1000:.2f} kHz" if f >= 999.95 else f"{f:.0f} Hz"


def segments(bands: list[MBand], edges: tuple[float, float], count: int, source: str, target: str,
             notes: list[str]) -> list[tuple[float, float, MBand | None]]:
    """The spectrum between ``edges`` as at most ``count`` stretches, each a source band or none;
    an empty stretch under two thirds of an octave joins the band beside it, and past the count
    the narrowest empty stretch joins a neighbour, then the narrowest band."""
    lo_edge, hi_edge = edges
    segs: list[list] = []
    cursor = lo_edge
    for b in sorted(bands, key=lambda b: b.low):
        low, high = max(b.low, lo_edge), min(b.high, hi_edge)
        if low > cursor and math.log2(low / cursor) >= SLIVER:
            segs.append([cursor, low, None])
        elif low > cursor:
            low = cursor                                 # a sliver: the band reaches down to it
        segs.append([low, high, b])
        cursor = max(cursor, high)
    if cursor < hi_edge and math.log2(hi_edge / cursor) >= SLIVER:
        segs.append([cursor, hi_edge, None])
    elif segs:
        segs[-1][1] = max(segs[-1][1], hi_edge)
    while len(segs) > count:
        gaps = [i for i, s in enumerate(segs) if s[2] is None]
        i = min(gaps or range(len(segs)), key=lambda i: math.log2(segs[i][1] / segs[i][0]))
        lo, hi, b = segs[i]
        j = i + 1 if i + 1 < len(segs) else i - 1
        side = "above" if j > i else "below"
        if b is None:
            notes.append(f"{_hz(lo)}-{_hz(hi)}, no band in {source}: joins the band {side} in {target}")
        else:
            notes.append(f"band {b.number} {b.label()}: {target} has {count} bands; dropped, its range joins the band {side}")
        segs[j][0], segs[j][1] = min(segs[j][0], lo), max(segs[j][1], hi)
        del segs[i]
    return [tuple(s) for s in segs]
