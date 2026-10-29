"""Silence in a long audio file, for cutting the silent stretches out of a track.

`peak_envelope` reads a WAV once into a peak per hop (10 ms): the largest magnitude of any
channel's sample in its top 16 bits, so an hour-long 24-bit file reads in seconds; `rms_envelope`
is the RMS per hop instead, through the `bandrms.swift` helper, all channels pooled and band-limited
when asked — the voice band of a vocal mic, say. A hop is quiet when its peak sits more than
``threshold_db`` under the file's loud level — the 95th-percentile hop peak, so one burst does not
set it and a cold DI reads like a hot amp — and a quiet stretch is a run of quiet hops at least
``min_gap_s`` long, in frames. Its edges then crop outward over every hop under the tighter
``edge_db`` limit — hum, string noise and room between songs sit over the gap limit but well under
the playing — stepping over a sound shorter than a click (50 ms); a sound shorter than ``min_keep_s``
left between two stretches (or one and the file's edge) is a blip between songs, and silence too.
`bleed_stretches` is the rule for a mic that is never silent while the band plays: quiet is under
the bleed floor — the 25th-percentile level while a reference plays — plus ``above_db``, read on a
running median over 300 ms, which a drum hit in the bleed is too short to move; and, given each
reference's own level, the mic is heard only over the bleed they predict — each reference scaled by
the mic's usual ratio to it, summed as power — so bleed that merely rose with the band, or with a
lead singer, is quiet too.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from logicxkit.utils.swiftrun import native_dir, run_swift
from .wavfile import IEEE_FLOAT, PCM, wav_data

FULL = 32768                                           # the top 16 bits' full scale
LOUD_PERCENTILE = 0.95
CLICK_MS = 50                                          # a sound this short does not stop an edge crop
FLOOR_PERCENTILE = 0.25
BLEED_WINDOW_MS = 300                                  # the running median a bleed level is read on
RMS_TIMEOUT = 900
EMPTY_WAV = 1024                                       # bytes: a header and no audio
ITEM = {(PCM, 16): "h", (PCM, 24): "xh", (PCM, 32): "xxh", (IEEE_FLOAT, 32): "f", (IEEE_FLOAT, 64): "d"}
Reference = tuple[list[int], list[bool]]           # a reference track's level per hop, aligned to the mic's, and whether it plays there


@dataclass(frozen=True)
class Envelope:
    peaks: list[int]           # per hop, the largest |sample| in its top 16 bits, 0..32768
    hop: int                   # frames per hop
    rate: int
    frames: int

    @cached_property
    def loud(self) -> int:
        """The 95th-percentile hop peak: the level the file plays at."""
        if not self.peaks:
            return 0
        return sorted(self.peaks)[min(len(self.peaks) - 1, int(len(self.peaks) * LOUD_PERCENTILE))]

    @property
    def loud_db(self) -> float:
        return db(self.loud)


def db(peak: int) -> float:
    return 20 * math.log10(peak / FULL) if peak else -math.inf


def peak_envelope(path: Path, hop_ms: int = 10) -> Envelope:
    w = wav_data(path)
    item = ITEM.get((w.code, w.bits))
    if item is None:
        raise ValueError(f"{path}: {w.bits}-bit {w.kind} is not a layout this reads (16, 24 or 32-bit PCM, 32 or 64-bit float)")
    hop = max(1, w.rate * hop_ms // 1000)
    frames = w.frames
    hops = frames // hop
    peaks: list[int] = []
    if hops:
        full = struct.Struct("<" + item * (hop * w.channels))
        last = struct.Struct("<" + item * ((frames - (hops - 1) * hop) * w.channels))
        for k in range(hops):
            s = last if k == hops - 1 else full
            v = s.unpack_from(w.data, k * hop * w.block)
            peak = max(-min(v), max(v))
            peaks.append(min(FULL, int(peak * (FULL - 1))) if w.code == IEEE_FLOAT else peak)
    return Envelope(peaks, hop, w.rate, frames)


def rms_envelope(path: Path, *, band: tuple[int, int] | None, hop_ms: int = 10) -> Envelope:
    """The RMS per hop as `peak_envelope` scales a peak (0..32768), all channels pooled, within
    ``band`` Hz when given."""
    args = [str(path), str(hop_ms)] + ([str(band[0]), str(band[1])] if band else [])
    code, out, err = run_swift(native_dir() / "bandrms.swift", args, timeout=RMS_TIMEOUT)
    if code != 0:
        raise ValueError(f"{path}: {err.strip() or 'the envelope helper failed'}")
    head, _, body = out.partition("\n")
    rate, hop, frames, count = (int(v) for v in head.split())
    if not frames and Path(path).stat().st_size > EMPTY_WAV:
        raise ValueError(f"{path}: the envelope helper read no frames from it; a chunk before data may be malformed")
    values = body.split()
    if len(values) != count:
        raise ValueError(f"{path}: the envelope helper wrote {len(values)} of {count} hops")
    return Envelope([min(FULL, round(float(v) * FULL)) for v in values], hop, rate, frames)


def quiet_stretches(env: Envelope, *, threshold_db: float, min_gap_s: float, min_keep_s: float,
                    edge_db: float) -> list[tuple[int, int]]:
    """``(first frame, end frame)`` of every run of quiet hops at least ``min_gap_s`` long, its edges
    cropped outward over hops under the ``edge_db`` limit, a sound shorter than ``min_keep_s`` between
    two of them (or one and the file's edge) absorbed; the last run reaches the file's end when its
    hop does."""
    loud = env.loud
    limit, edge = loud * 10 ** (threshold_db / 20), loud * 10 ** (edge_db / 20)
    quiet = [p < limit for p in env.peaks] if loud else [True] * len(env.peaks)
    return _stretches(env, quiet, edge=edge, min_gap_s=min_gap_s, min_keep_s=min_keep_s)


def bleed_stretches(env: Envelope, playing: list[bool], *, above_db: float, min_gap_s: float,
                    min_keep_s: float, window_ms: int = BLEED_WINDOW_MS,
                    references: list[Reference] | None = None, against: list[int] | None = None,
                    tilt_db: float = 0.0, tilted: list[int] | None = None,
                    gate_db: float | None = None) -> tuple[list[tuple[int, int]], float, list[float]]:
    """The stretches where the mic stays within ``gate_db`` (default ``above_db``) of its bleed
    floor — the 25th-percentile nonzero level while ``playing`` — that floor in dBFS, and the mic's
    usual ratio to each reference, all read on the running median of the hop levels over
    ``window_ms``; with nothing playing no floor can be read, so nothing is quiet, and a mic digitally silent
    wherever something plays is quiet where it is silent. With ``references``, one ``(level, plays)`` per reference
    track aligned to the mic's hops, the mic is heard only where it is also ``above_db`` over the
    bleed they predict: each reference scaled by the mic's usual ratio to it — the 25th percentile
    of mic over reference while that reference plays — and summed as power, so a lead singer's
    bleed in a backing mic, far under the lead's own mic, and the band's are each told from the
    mic's own voice. A hop no reference covers is judged on the
    floor alone. With ``against``, the mic's own level per hop in a second band, each sound left is judged at
    its peak: one that is not ``tilt_db`` louder in the band (or in ``tilted``, the mic in a band
    of the tilt's own) than in the other is silence too — a snare in a tom mic has more over 400 Hz
    than at the tom's fundamental."""
    window = max(1, round(window_ms * env.rate / 1000 / env.hop))
    level = _running_median(env.peaks, window)
    heard = sorted(p for p, on in zip(level, playing, strict=True) if on and p)
    if not heard:                                      # nothing plays, or the mic is digitally silent wherever it does
        quiet = [not p for p in level] if any(playing) else [False] * len(level)
        return _stretches(env, quiet, edge=None, min_gap_s=min_gap_s, min_keep_s=min_keep_s), -math.inf, [math.inf] * len(references or ())
    floor = heard[min(len(heard) - 1, int(len(heard) * FLOOR_PERCENTILE))]
    gate = floor * 10 ** ((above_db if gate_db is None else gate_db) / 20)
    quiet = [p < gate for p in level]
    usual: list[float] = []
    if references:
        bleed = [0.0] * len(level)                     # the predicted bleed's power per hop, in peak units squared
        for ref_level, plays in references:
            ref = _running_median(ref_level, window)
            over = sorted(db(p) - db(r) for p, r, on in zip(level, ref, plays, strict=True) if on and r and p)
            ratio = over[min(len(over) - 1, int(len(over) * FLOOR_PERCENTILE))] if over else math.inf
            usual.append(ratio)
            if over:
                scale = 10 ** (ratio / 10)
                for h, r in enumerate(ref):
                    bleed[h] += r * r * scale
        margin = 10 ** (above_db / 10)
        quiet = [q or (b > 0 and p * p < b * margin) for q, p, b in zip(quiet, level, bleed, strict=True)]
    stretches = _stretches(env, quiet, edge=None, min_gap_s=min_gap_s, min_keep_s=min_keep_s)
    if against is not None:
        other = _running_median(against, window)
        own = level if tilted is None else _running_median(tilted, window)
        quiet = [True] * len(quiet)
        for a, b in _sounds(stretches, env):
            peak = max(range(a, b), key=lambda h: level[h])
            if db(own[peak]) - db(other[peak]) >= tilt_db:
                for h in range(a, b):
                    quiet[h] = False
        stretches = _stretches(env, quiet, edge=None, min_gap_s=0, min_keep_s=0)
    return stretches, db(floor), usual


def _sounds(stretches: list[tuple[int, int]], env: Envelope) -> list[tuple[int, int]]:
    """The hop spans between ``stretches`` (frames), the sounds."""
    out, cursor = [], 0
    for a, b in stretches:
        if a // env.hop > cursor:
            out.append((cursor, a // env.hop))
        cursor = max(cursor, -(-b // env.hop))
    if cursor < len(env.peaks):
        out.append((cursor, len(env.peaks)))
    return out


def _running_median(values: list[int], window: int) -> list[int]:
    if window < 2:
        return values
    half, n = window // 2, len(values)
    out = []
    for i in range(n):
        w = sorted(values[max(0, i - half):min(n, i + half + 1)])
        out.append(w[len(w) // 2])
    return out


def _stretches(env: Envelope, quiet: list[bool], *, edge: float | None, min_gap_s: float,
               min_keep_s: float) -> list[tuple[int, int]]:
    peaks = env.peaks
    least = max(1, math.ceil(min_gap_s * env.rate / env.hop))
    blip = math.ceil(min_keep_s * env.rate / env.hop)
    click = math.ceil(CLICK_MS * env.rate / 1000 / env.hop)
    runs: list[list[int]] = []
    i = 0
    while i < len(quiet):
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < len(quiet) and quiet[j]:
            j += 1
        if j - i >= least:
            runs.append([i, j] if edge is None else [_cropped(peaks, i, -1, edge, click), _cropped(peaks, j, 1, edge, click)])
        i = j
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] < blip:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if merged and 0 < merged[0][0] < blip:
        merged[0][0] = 0
    if merged and 0 < len(quiet) - merged[-1][1] < blip:
        merged[-1][1] = len(quiet)
    return [(a * env.hop, env.frames if b == len(quiet) else b * env.hop) for a, b in merged]


def _cropped(peaks: list[int], at: int, step: int, edge: float, click: int) -> int:
    """``at`` moved by ``step`` (-1 for a run's first hop, 1 for its end) over every hop under
    ``edge``, and over a louder run shorter than ``click`` hops."""
    n = len(peaks)
    while True:
        k = at - 1 if step < 0 else at
        if not 0 <= k < n:
            return at
        if peaks[k] < edge:
            at += step
            continue
        loud_from = k
        while 0 <= loud_from < n and peaks[loud_from] >= edge:
            loud_from += step
        if abs(loud_from - k) >= click:
            return at
        at = loud_from + 1 if step < 0 else loud_from


def writable(spans: list[tuple[int, int]], spt: float) -> list[tuple[int, int]]:
    """``spans`` less any shorter than a tick (``spt`` frames), which no trim or split can write, and
    two that touch or lie less than a tick apart as one, since a cut between them would remove nothing."""
    least = math.ceil(spt)
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if b - a < least:
            continue
        if out and a - out[-1][1] < least:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def keeps(offset: int, frames: int, quiet: list[tuple[int, int]], *, pad: int | tuple[int, int]) -> list[tuple[int, int]]:
    """The spans of the region at ``offset`` lasting ``frames`` that are not quiet, each widened
    into the gaps beside it by ``pad`` frames — one figure, or (before, after) — at most half a
    gap between two spans, in file frames."""
    before_pad, after_pad = (pad, pad) if isinstance(pad, int) else pad
    lo, hi = offset, offset + frames
    cuts = sorted((max(a, lo), min(b, hi)) for a, b in quiet if b > lo and a < hi)
    spans: list[list[int]] = []
    cursor = lo
    for a, b in cuts:
        if a > cursor:
            spans.append([cursor, a])
        cursor = max(cursor, b)
    if cursor < hi:
        spans.append([cursor, hi])
    out = []
    for i, (a, b) in enumerate(spans):
        before = lo if i == 0 else spans[i - 1][1]
        after = hi if i == len(spans) - 1 else spans[i + 1][0]
        start_room = a - before if i == 0 else (a - before) // 2
        end_room = after - b if i == len(spans) - 1 else (after - b) // 2
        out.append((a - min(before_pad, start_room), b + min(after_pad, end_room)))
    return out
