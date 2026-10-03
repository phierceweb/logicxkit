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

HOP = 32
PCM, IEEE_FLOAT, EXTENSIBLE = 0x0001, 0x0003, 0xFFFE
FMT_BASIC, FMT_EXTENSIBLE = 16, 40
CB_SIZE_AT, SUBFORMAT_AT, EXTENSION = 16, 24, 22
GUID_TAIL = bytes.fromhex("000000001000800000aa00389b71")      # KSDATAFORMAT_SUBTYPE_* after its code
LAYOUTS = {(PCM, 16): "h", (PCM, 24): None, (PCM, 32): "i", (IEEE_FLOAT, 32): "f", (IEEE_FLOAT, 64): "d"}


def _format_code(path: Path, fmt: bytes) -> int:
    """PCM or IEEE float; an extensible fmt resolves through its SubFormat GUID."""
    code = struct.unpack_from("<H", fmt, 0)[0]
    if code in (PCM, IEEE_FLOAT):
        return code
    if code != EXTENSIBLE:
        raise ValueError(f"{path}: WAV format code 0x{code:04x} is not PCM or IEEE float")
    cb = struct.unpack_from("<H", fmt, CB_SIZE_AT)[0] if len(fmt) >= CB_SIZE_AT + 2 else 0
    if len(fmt) < FMT_EXTENSIBLE or cb < EXTENSION:
        raise ValueError(f"{path}: WAVE_FORMAT_EXTENSIBLE with a {len(fmt)}-byte fmt chunk and cbSize {cb}")
    guid = fmt[SUBFORMAT_AT:SUBFORMAT_AT + 16]
    if guid[2:] != GUID_TAIL:
        raise ValueError(f"{path}: WAVE_FORMAT_EXTENSIBLE SubFormat GUID {guid.hex()} is not a KSDATAFORMAT_SUBTYPE")
    code = struct.unpack_from("<H", guid, 0)[0]
    if code not in (PCM, IEEE_FLOAT):
        raise ValueError(f"{path}: WAVE_FORMAT_EXTENSIBLE SubFormat 0x{code:04x} is not PCM or IEEE float")
    return code


def read_wav(path: Path) -> tuple[list[float], int]:
    """(channel 0 as floats, sample rate) of a PCM (16/24/32-bit) or IEEE float (32/64-bit)
    WAV, extensible included; PCM is scaled to -1..1. Logic pads no chunk after ``data``, so
    odd sizes are stepped over by content, not by the RIFF rule."""
    b = Path(path).read_bytes()
    k, fmt, data = 12, None, None
    while k + 8 <= len(b):
        if not all(32 <= c < 127 for c in b[k:k + 4]):
            k += 1                                  # a pad byte after an odd chunk
        tag, n = b[k:k + 4], struct.unpack_from("<I", b, k + 4)[0]
        if not all(32 <= c < 127 for c in tag) or k + 8 + n > len(b):
            break
        if tag == b"fmt ":
            fmt = b[k + 8:k + 8 + n]
        elif tag == b"data":
            data = b[k + 8:k + 8 + n]
            break
        k += 8 + n
    if fmt is None or data is None or len(fmt) < FMT_BASIC:
        raise ValueError(f"{path}: not a WAV with a fmt and a data chunk")
    code = _format_code(path, fmt)
    _code, channels, rate, _bps, block, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if (code, bits) not in LAYOUTS or not channels or block != channels * bits // 8:
        kind = "float" if code == IEEE_FLOAT else "PCM"
        raise ValueError(f"{path}: {bits}-bit {kind}, {channels} channel(s) is not a layout this reads")
    frames, char = len(data) // block, LAYOUTS[code, bits]
    if char is None:
        return [int.from_bytes(data[i:i + 3], "little", signed=True) / float(1 << 23)
                for i in range(0, frames * block, block)], rate
    values = struct.unpack_from(f"<{frames * channels}{char}", data)[::channels]
    if code == IEEE_FLOAT:
        return list(values), rate
    full = float(1 << (bits - 1))
    return [v / full for v in values], rate


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
