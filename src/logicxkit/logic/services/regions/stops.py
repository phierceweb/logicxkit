"""Where a band stops between songs, from the tracks that go quiet when it does — a bass DI, a
kick, a snare. Each track is a run of booleans over the song's 10 ms hops, True where its level
sits under its limit (`silence.quiet_stretches`' rule, a hop with no region over it quiet too);
`band_quiet` is True where every track is. A gap is a quiet run of ``min_gap_s`` or more, a
sound shorter than ``min_keep_s`` between two gaps absorbed; gaps less than ``merge_s`` of
playing apart are one stop, since a band that has stopped noodles and talks; a stop of
``min_stop_s`` or more separates songs; the playing between stops is a song when it lasts
``min_song_s``, else a bit the listing names and leaves out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Span = tuple[int, int]              # (first hop, end hop)


@dataclass(frozen=True)
class Stops:
    stops: list[Span]
    songs: list[Span]               # the playing between stops, long enough to be a song
    short: list[Span]               # playing left out, shorter than min_song_s
    hops: int


def band_quiet(tracks: list[list[bool]], hops: int) -> list[bool]:
    """True where every track is quiet; a track ends early where its regions do, quiet from there."""
    out = [True] * hops
    for track in tracks:
        for h in range(min(hops, len(track))):
            if not track[h]:
                out[h] = False
    return out


def gaps(quiet: list[bool], *, hop_s: float, min_gap_s: float, min_keep_s: float) -> list[Span]:
    least, blip = max(1, math.ceil(min_gap_s / hop_s)), math.ceil(min_keep_s / hop_s)
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
            runs.append([i, j])
        i = j
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] < blip:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def merged_stops(found: list[Span], *, hop_s: float, merge_s: float, min_stop_s: float) -> list[Span]:
    """Gaps closer than ``merge_s`` of playing apart as one stop, those of ``min_stop_s`` or more."""
    near, least = math.ceil(merge_s / hop_s), math.ceil(min_stop_s / hop_s)
    out: list[list[int]] = []
    for a, b in found:
        if out and a - out[-1][1] < near:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a >= least]


def find_stops(quiet: list[bool], *, hop_s: float, min_gap_s: float, min_keep_s: float, merge_s: float,
               min_stop_s: float, min_song_s: float) -> Stops:
    stops = merged_stops(gaps(quiet, hop_s=hop_s, min_gap_s=min_gap_s, min_keep_s=min_keep_s),
                         hop_s=hop_s, merge_s=merge_s, min_stop_s=min_stop_s)
    least = math.ceil(min_song_s / hop_s)
    songs, short = [], []
    first = next((i for i, q in enumerate(quiet) if not q), len(quiet))
    end = len(quiet) - next((i for i, q in enumerate(reversed(quiet)) if not q), len(quiet))
    cursor = first
    for a, b in stops + [(end, end)]:
        if a > cursor:
            (songs if a - cursor >= least else short).append((cursor, a))
        cursor = max(cursor, b)
    return Stops(stops, songs, short, len(quiet))
