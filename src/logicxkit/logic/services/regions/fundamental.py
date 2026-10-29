"""A drum's fundamental from its own file: the frequency with the most power over the mic's
loudest moments, searched in 5 Hz steps between ``low`` and ``high``. Each moment is a
4096-frame Hann-windowed frame at one of the loudest hops of ``env`` (hops at least 100 ms apart,
so one hit does not set it), the channels averaged; the power at each candidate is the squared
dot products with its cosine and sine."""

from __future__ import annotations

import math
import struct
from pathlib import Path

from .silence import ITEM, Envelope
from .wavfile import wav_data

FRAME = 4096
SPACING_MS = 100
_WINDOW = [0.5 - 0.5 * math.cos(2 * math.pi * i / FRAME) for i in range(FRAME)]


def fundamental(path: Path, env: Envelope, *, low: int = 50, high: int = 350, hits: int = 200, step: int = 5) -> float:
    w = wav_data(path)
    item = ITEM.get((w.code, w.bits))
    if item is None:
        raise ValueError(f"{path}: {w.bits}-bit {w.kind} is not a layout this reads")
    frame = struct.Struct("<" + item * (FRAME * w.channels))
    spacing = max(1, SPACING_MS * env.rate // 1000 // env.hop)
    chosen: list[int] = []
    for hop in sorted(range(len(env.peaks)), key=lambda h: -env.peaks[h]):
        start = hop * env.hop
        if start + FRAME > w.frames:
            continue
        if all(abs(hop - c) >= spacing for c in chosen):
            chosen.append(hop)
        if len(chosen) >= hits:
            break
    if not chosen:
        raise ValueError(f"{path}: too short to read a fundamental from")
    frames = []
    for hop in chosen:
        values = frame.unpack_from(w.data, hop * env.hop * w.block)
        mono = values if w.channels == 1 else [sum(values[i:i + w.channels]) / w.channels for i in range(0, len(values), w.channels)]
        frames.append([v * win for v, win in zip(mono, _WINDOW, strict=True)])
    best, best_power = low, -1.0
    for hz in range(low, high + 1, step):
        cos = [math.cos(2 * math.pi * hz * i / w.rate) for i in range(FRAME)]
        sin = [math.sin(2 * math.pi * hz * i / w.rate) for i in range(FRAME)]
        power = sum(math.sumprod(f, cos) ** 2 + math.sumprod(f, sin) ** 2 for f in frames)
        if power > best_power:
            best, best_power = hz, power
    if best_power <= 0:
        raise ValueError(f"{path}: silent at its loudest moments; no fundamental to read")
    if best in (low, high):
        raise ValueError(f"{path}: its loudest moments peak at the search's edge ({best} Hz); no fundamental between {low} and {high} Hz")
    return float(best)
