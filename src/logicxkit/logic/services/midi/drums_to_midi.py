"""Drum hits in audio tracks to notes in a MIDI region, on a copy, without Logic.

Each hit track's audio regions give their hits (`onsets.py`), taken region-relative as
`quantize_drums.py` takes them and placed at song ticks at the project's one tempo; a hit
belongs to the region holding its onset, and hits that overlapping regions share count once. A
WAV whose rate, or as the record's own file whose length, differs from the region's file record
is refused. Each hit becomes a sixteenth on its term's key in the drum map (groovebin's), cut at
the next note on that key, velocity its peak in dB mapped linearly onto 1-127 from the track's
quietest hit to its loudest and then, when a band is given, onto it through groovebin's velocity
curve. A track may have its own detector floor. The notes, quantized first when a grid is given,
go through `midi_edit` into one new region on the target instrument track spanning the whole bars
that hold them.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from groovebin import transforms as gt
from groovebin.events import Note
from groovebin.maps import drum_map
from groovebin.song import Part

from ..regions.audio_regions import AudioRegion, read_audio_regions
from ..song.events import BAR_ONE, PPQ
from ..regions.flexmarkers import samples_per_tick
from .midi_edit import END_TICK, edit_region, from_part, meter_map
from .midi_write import add_region, require_instrument
from ..regions.onsets import Detector, merge_hits, onsets, read_wav
from ..regions.quantize_drums import WavFinder, _object_ids
from ..song.signature import meter
from ..song.tempo import project_tempo, read_tempo_events
from ..stream.validate import require_full_walk

SIXTEENTH = PPQ // 4
CHANNEL = 1
FULL_BAND = (1, 127, 1.0)
PEAK_MS = 20
SAME_HIT_MS = 50


@dataclass
class Report:
    target: str
    map_name: str
    grid: int | None
    hits: list[tuple[str, str, int, int]] = field(default_factory=list)      # (track, term, note, hits)
    notes: int = 0
    merged: int = 0
    start_bar: int = 0
    bars: int = 0
    floors: dict[str, float] = field(default_factory=dict)
    velocity: tuple[int, int, float] = FULL_BAND

    def lines(self) -> list[str]:
        timing = f"quantized to 1/{self.grid}" if self.grid else "the take's timing kept"
        band = "" if self.velocity == FULL_BAND else \
            f", velocities {self.velocity[0]}..{self.velocity[1]}" + (f" gamma {self.velocity[2]:g}" if self.velocity[2] != 1 else "")
        return [*(f"{track}: {n} hit(s) -> {term} (note {note}, {self.map_name})"
                  + (f"; floor {self.floors[track]:g} dB" if track in self.floors else "") for track, term, note, n in self.hits),
                f"{self.notes} note(s) in a {self.bars}-bar region on {self.target!r} from bar {self.start_bar}, {timing}{band}",
                *([f"{self.merged} note(s) on a key already struck at that tick dropped, the loudest kept"]
                  if self.merged else [])]


def note_for(map_name: str, term: str) -> int:
    """The drum map's note for ``term``; an unknown term is refused with the terms nearest it."""
    m = drum_map(map_name)
    note = m.find(term)
    if note is None:
        first = term.split()[0] if term.split() else ""
        near = [t for t in m.terms() if t.split()[0] == first] or sorted({t.split()[0] for t in m.terms()})
        raise ValueError(f"no {map_name} drum map term {term!r}; try {', '.join(near)}")
    return note


def velocities(peaks: Sequence[float]) -> list[int]:
    """Peaks (linear) -> 1-127, linear in dB from the quietest to the loudest; one level is 127."""
    db = [20 * math.log10(max(p, 1e-9)) for p in peaks]
    lo, hi = min(db, default=0.0), max(db, default=0.0)
    return [127 if hi == lo else 1 + round(126 * (d - lo) / (hi - lo)) for d in db]


def _one_tempo(data: bytes) -> float:
    bpms = {e.bpm for e in read_tempo_events(data)}
    if len(bpms) > 1:
        raise ValueError(f"the tempo track changes tempo ({min(bpms):g} to {max(bpms):g} bpm); "
                         "drums-to-midi reads one tempo and refuses tempo changes and ramps")
    return bpms.pop() if bpms else project_tempo(data)[1]


def _require_record(wav: Path, samples: list[float], rate: int, region: AudioRegion) -> None:
    """The WAV has to be the audio the region's file record describes: its rate, and its length
    when the WAV is the record's own file (a later take of the region's name has its own)."""
    record = region.file
    if record is None:
        return
    if record.rate and rate != record.rate:
        raise ValueError(f"{wav.name} is at {rate} Hz but the file record of {region.track}'s region {region.name!r} "
                         f"says {record.rate} Hz; the region's frames count at the record's rate")
    if record.frames and wav.name == record.name and len(samples) != record.frames:
        raise ValueError(f"{wav.name} holds {len(samples)} frames but the file record of {region.track}'s region "
                         f"{region.name!r} says {record.frames} frames; it is not the file the project plays")


def _track_hits(regions: list[AudioRegion], wav_of: WavFinder, bpm: float, detector: Detector) -> list[tuple[int, float]]:
    """(song tick, peak) of each hit in ``regions``, ascending; hits within 50 ms are one, the louder.
    A hit belongs to the region holding its onset, its peak read from the file past that region's end."""
    found, read = [], {}
    for region in regions:
        wav = wav_of(region)
        if wav is None or not Path(wav).exists():
            raise ValueError(f"no audio file for {region.track}'s region {region.name!r} "
                             f"({region.file.name if region.file else '?'})")
        wav = Path(wav)
        if wav not in read:
            samples, rate = read_wav(wav)
            read[wav] = samples, rate, onsets(samples, rate, detector)
        samples, rate, at = read[wav]
        _require_record(wav, samples, rate, region)
        spt = samples_per_tick(rate * 60 / bpm)
        for h in merge_hits([at], rate, offset=region.offset, length=region.frames):
            onset = region.offset + h
            following = bisect.bisect_right(at, onset)
            end = min(onset + rate * PEAK_MS // 1000, at[following] if following < len(at) else len(samples))
            found.append((region.start + round(h / spt), max((abs(v) for v in samples[onset:end]), default=0.0)))
    window = SAME_HIT_MS * bpm * PPQ / 60000
    out: list[tuple[int, float]] = []
    for t, peak in sorted(found):
        if out and t - out[-1][0] < window:
            out[-1] = (out[-1][0], max(out[-1][1], peak))
        else:
            out.append((t, peak))
    return out


def one_per_key(notes: Sequence[Note]) -> tuple[list[Note], int]:
    """One note per key and tick, the loudest, each ending by the next on its key; and how many went."""
    best: dict[tuple[int, int], Note] = {}
    for n in notes:
        if (n.tick, n.pitch) not in best or n.velocity > best[n.tick, n.pitch].velocity:
            best[n.tick, n.pitch] = n
    out, following = [], {}
    for n in sorted(best.values(), key=lambda n: (n.tick, n.pitch), reverse=True):
        out.append(replace(n, length=min(n.length, following.get(n.pitch, END_TICK) - n.tick)))
        following[n.pitch] = n.tick
    return out[::-1], len(notes) - len(best)


def drums_to_midi(data: bytes, *, hits: Sequence[tuple[str, str]], target: str, wav_of: WavFinder,
                  map_name: str = "addictive-drums-2", grid: int | None = None, detector: Detector = Detector(),
                  floors: Mapping[str, float] | None = None, velocity: tuple[int, int, float] = FULL_BAND,
                  track_count: int | None = None) -> tuple[bytes, Report]:
    """``hits``: (audio track, drum map term) pairs; ``target``: the instrument track the region
    goes on; ``wav_of`` finds a region's audio file; ``floors``: a track's own detector floor in dB;
    ``velocity``: (floor, ceiling, gamma) for the velocities. Returns (project, report)."""
    if not hits:
        raise ValueError("name at least one hit track and its term")
    floors = dict(floors or {})
    unknown = sorted(set(floors) - {t for t, _term in hits})
    if unknown:
        raise ValueError(f"a floor for {', '.join(map(repr, unknown))}, which no --hit names")
    lo, hi, gamma = velocity
    if not (1 <= lo <= hi <= 127) or not gamma > 0:
        raise ValueError(f"a velocity band of {lo}..{hi} gamma {gamma:g}: 1 <= floor <= ceiling <= 127, gamma above 0")
    tracks = [t for t, _term in hits]
    twice = sorted({t for t in tracks if tracks.count(t) > 1})
    if twice:
        raise ValueError(f"{', '.join(map(repr, twice))} named more than once; one term per track")
    notes = [note_for(map_name, term) for _t, term in hits]
    shared = sorted({n for n in notes if notes.count(n) > 1})
    if shared:
        raise ValueError(f"note(s) {', '.join(map(str, shared))} would take the hits of more than one track; one track per key")
    step = gt.grid_ticks(grid, PPQ) if grid is not None else None
    require_full_walk(data)
    bpm = _one_tempo(data)
    (target_id,) = _object_ids(data, [target], track_count)
    require_instrument(data, target_id, target, track_count)
    regions = read_audio_regions(data, track_count)
    report = Report(target, map_name, grid, floors=floors, velocity=velocity)
    placed = []
    for (track, term), object_id, note in zip(hits, _object_ids(data, tracks, track_count), notes, strict=True):
        mine = [r for r in regions if r.object_id == object_id]
        if not mine:
            raise ValueError(f"no audio regions on {track!r}")
        found = _track_hits(mine, wav_of, bpm, replace(detector, floor_db=floors[track]) if track in floors else detector)
        placed += [(t, note, v) for (t, _peak), v in zip(found, velocities([p for _t, p in found]), strict=True)]
        report.hits.append((track, term, note, len(found)))
    if not placed:
        raise ValueError(f"no hits found in the audio of {', '.join(map(repr, tracks))}")
    meters = meter_map(meter(data))                      # bar 1 at tick 0, as the song's ticks below
    part = Part(PPQ, tuple(Note(t - BAR_ONE, SIXTEENTH, CHANNEL, n, v) for t, n, v in placed))
    if velocity != FULL_BAND:
        part = gt.velocity_curve(part, floor=lo, ceiling=hi, gamma=gamma)
    if step:
        part = gt.quantize(part, step, meters)
    start = meters.bar_line(meters.bar_of(min(n.tick for n in part.notes)))
    notes, report.merged = one_per_key([replace(n, tick=n.tick - start) for n in part.notes])
    end = meters.bar_line(meters.bar_of(start + max(n.tick for n in notes)) + 1)
    lines = from_part(Part(PPQ, tuple(notes)))
    data, made = add_region(data, track=target, start=start + BAR_ONE, length=end - start, track_count=track_count)
    data = edit_region(data, made["slot"], lambda _empty: lines, track_count=track_count)
    report.notes, report.start_bar, report.bars = len(lines), meters.bar_of(start), meters.bar_of(end) - meters.bar_of(start)
    return data, report
