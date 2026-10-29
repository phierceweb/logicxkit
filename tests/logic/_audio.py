"""The synthetic audio the command tests import: 24-bit mono files at 44.1 kHz shaped as the
sound a rule is about — sound, gaps, hum, bleed, a tom and a snare."""

import math
import random
import struct
from pathlib import Path

THREE = "tracks-three-audio-logic"            # Audio 1, 2 and 3 at 120 bpm, 44100 Hz
RATE = 44100
SPT = RATE * 60 / 120 / 960                   # frames per tick at 120 bpm


def riff(path: Path, frames: bytes, channels: int = 1) -> Path:
    """A 24-bit PCM file at `RATE` holding ``frames``, interleaved when ``channels`` > 1."""
    fmt = struct.pack("<HHIIHH", 1, channels, RATE, RATE * 3 * channels, 3 * channels, 24)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def sound_gap_sound(path: Path, *, sound: float = 1.0, gap: float | tuple[float, float] = 3.0, level: float = 0.5,
                    idle: float = 0.001) -> Path:
    """A 24-bit mono file: three ``sound``-second stretches at ``level`` with ``gap`` seconds at ``idle``
    (-60 dBFS) between them — one figure, or the two gaps."""
    gaps = (gap, gap) if isinstance(gap, (int, float)) else gap
    n_sound = int(sound * RATE)
    x = [level] * n_sound + [idle] * int(gaps[0] * RATE) + [level] * n_sound + [idle] * int(gaps[1] * RATE) + [level] * n_sound
    frames = b"".join((round(v * 8388607) * (1 if i % 2 == 0 else -1)).to_bytes(3, "little", signed=True) for i, v in enumerate(x))
    return riff(path, frames)


def sound_hum_gap(path: Path, *, sound: float = 1.0, hum: float = 1.0, gap: float = 3.0) -> Path:
    """Sound, then ``hum`` seconds 22 dB under it, the gap, the hum again, the sound again."""
    n_sound, n_hum, n_gap = int(sound * RATE), int(hum * RATE), int(gap * RATE)
    quiet = 0.5 / 10 ** (22 / 20)
    x = [0.5] * n_sound + [quiet] * n_hum + [0.001] * n_gap + [quiet] * n_hum + [0.5] * n_sound
    frames = b"".join((round(v * 8388607) * (1 if i % 2 == 0 else -1)).to_bytes(3, "little", signed=True) for i, v in enumerate(x))
    return riff(path, frames)


def vocal_mic(path: Path, *, seconds: float = 10.0, sings: tuple[tuple[float, float], ...] = ((2, 4), (6, 8))) -> Path:
    """Bleed at -45 dBFS RMS throughout (uniform noise), a 1 kHz tone at -20 dBFS while the singer sings."""
    noise = random.Random(1)
    x = [0.0097 * (2 * noise.random() - 1) for _ in range(int(seconds * RATE))]
    for a, b in sings:
        for i in range(int(a * RATE), int(b * RATE)):
            x[i] += 0.141 * math.sin(2 * math.pi * 1000 * i / RATE)
    return riff(path, b"".join(round(v * 8388607).to_bytes(3, "little", signed=True) for v in x))


def band_playing(path: Path, seconds: float = 10.0) -> Path:
    """A reference mic: a 1 kHz tone at -20 dBFS the whole way, the band playing throughout."""
    x = [0.141 * math.sin(2 * math.pi * 1000 * i / RATE) for i in range(int(seconds * RATE))]
    return riff(path, b"".join(round(v * 8388607).to_bytes(3, "little", signed=True) for v in x))


def tom_mic(path: Path, *, seconds: float = 8.0) -> Path:
    """Bleed at -45 dBFS; an 80 Hz tone burst at 2 s (a tom) and a burst of wideband noise at 5 s (a
    snare), each 0.4 s and 25 dB over the bleed."""
    noise = random.Random(2)
    x = [0.0097 * (2 * noise.random() - 1) for _ in range(int(seconds * RATE))]
    for i in range(int(2 * RATE), int(2.4 * RATE)):
        x[i] += 0.17 * math.sin(2 * math.pi * 80 * i / RATE)
    for i in range(int(5 * RATE), int(5.4 * RATE)):
        x[i] += 0.17 * (2 * noise.random() - 1)
    return riff(path, b"".join(max(-8388607, min(8388607, round(v * 8388607))).to_bytes(3, "little", signed=True) for v in x))


def silent(path: Path, seconds: float = 5.0) -> Path:
    return riff(path, bytes(3 * int(seconds * RATE)))


def tone(path: Path, seconds: float = 2.0) -> Path:
    """A 24-bit mono square wave."""
    frames = b"".join((8000 if i % 2 else -8000).to_bytes(3, "little", signed=True) for i in range(int(seconds * RATE)))
    return riff(path, frames)
