"""Onsets in a drum close-mic recording — where the hits start, in samples.

Peak envelope over 32-sample hops; a hit is a hop that stands `rise_db` above the quietest
hop of the previous `look_ms` (for the file's first hop, the track's quietest hop), at most
`floor_db` below the track's own peak (bleed from the other drums sits far under a close mic's
real hits), and `gap_ms` after the last one.
The position is then the first sample within 6 ms before that hop to reach `refine_ratio`
of the local peak. The defaults were tuned against the transients Logic marked on one take across four
grids (the logic README, "Flex and audio quantize", has the agreement).
"""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass
from pathlib import Path

from .wavfile import IEEE_FLOAT, PCM, wav_data

HOP = 32
LAYOUTS = {(PCM, 16): "h", (PCM, 24): None, (PCM, 32): "i", (IEEE_FLOAT, 32): "f", (IEEE_FLOAT, 64): "d"}


def read_wav(path: Path) -> tuple[list[float], int]:
    """(channel 0 as floats, sample rate) of a PCM (16/24/32-bit) or IEEE float (32/64-bit)
    WAV, extensible included; PCM is scaled to -1..1."""
    w = wav_data(path)
    if (w.code, w.bits) not in LAYOUTS:
        raise ValueError(f"{path}: {w.bits}-bit {w.kind}, {w.channels} channel(s) is not a layout this reads")
    frames, char = w.frames, LAYOUTS[w.code, w.bits]
    if char is None:
        return [int.from_bytes(w.data[i:i + 3], "little", signed=True) / float(1 << 23)
                for i in range(0, frames * w.block, w.block)], w.rate
    values = struct.unpack_from(f"<{frames * w.channels}{char}", w.data)[::w.channels]
    if w.code == IEEE_FLOAT:
        return list(values), w.rate
    full = float(1 << (w.bits - 1))
    return [v / full for v in values], w.rate


@dataclass(frozen=True)
class Detector:
    rise_db: float = 24.0
    floor_db: float = -21.0
    look_ms: int = 30
    gap_ms: int = 60
    refine_ratio: float = 0.12
    refine_back_ms: int = 6
    refine_forward_ms: int = 10


def _envelope(x: list[float]) -> list[float]:
    return [max(abs(v) for v in x[h:h + HOP]) for h in range(0, len(x) - HOP + 1, HOP)]


def onsets(x: list[float], rate: int, detector: Detector = Detector()) -> list[int]:
    """Sample positions of the hits in ``x``, ascending."""
    env = _envelope(x)
    if not env:
        return []
    peak = max(env)
    if peak <= 0:
        return []
    floor = peak * 10 ** (detector.floor_db / 20)
    ratio = 10 ** (detector.rise_db / 20)
    look = max(1, int(detector.look_ms * rate / 1000 / HOP))
    gap = max(1, int(detector.gap_ms * rate / 1000 / HOP))
    back, forward = int(detector.refine_back_ms * rate / 1000), int(detector.refine_forward_ms * rate / 1000)
    out, last, before = [], -gap, min(env)
    for h in range(len(env)):
        v = env[h]
        if v < floor or h - last < gap:
            continue
        quiet = min(env[max(0, h - look):h], default=before)
        if v >= ratio * max(quiet, 1e-9) and v >= max(env[max(0, h - 3):h], default=0.0):
            a, b = max(0, h * HOP - back), min(len(x), h * HOP + forward)
            threshold = detector.refine_ratio * max(abs(s) for s in x[a:b])
            out.append(next((i for i in range(a, b) if abs(x[i]) >= threshold), h * HOP))
            last = h
    return out


def merge_hits(tracks: list[list[int]], rate: int, *, window_ms: int = 50, offset: int = 0,
               length: int | None = None) -> list[int]:
    """One ascending list from several mics: hits within ``window_ms`` of an earlier one are
    the same hit; ``offset`` samples are taken off every position (the region's start in its
    file) and positions outside ``0 .. length`` go."""
    window = int(window_ms * rate / 1000)
    out: list[int] = []
    for p in sorted({h - offset for hits in tracks for h in hits}):
        if p < 0 or (length is not None and p >= length):
            continue
        i = bisect.bisect_left(out, p)
        if (i and p - out[i - 1] < window) or (i < len(out) and out[i] - p < window):
            continue
        out.insert(i, p)
    return out
