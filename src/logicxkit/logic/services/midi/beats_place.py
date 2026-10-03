"""Patterns from a groovebin library laid into a project: one MIDI region per placement through
`midi_write.add_region`, its notes filled in through `midi_edit`. Notes are groovebin's, ticks
from the pattern's start at 960 PPQ. A region never grows to hold a note: one starting at or past
the region's end is dropped and counted. The tempo is never touched."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from groovebin.events import Note
from groovebin.library.generate import Phrase
from groovebin.library.pattern import Pattern, fit, repeated
from groovebin.maps import remap
from groovebin.song import Part
from groovebin.transforms import merge, scale_velocity

from ..song.events import BAR_ONE, PPQ
from .midi_edit import END_TICK, edit, edit_region
from .midi_write import add_region
from ..song.signature import Meter, meter
from .midi_edit import meter_map


def lay_over(m: Meter, bar: int, bars: tuple[tuple[int, int], ...], times: int = 1,
             noun: str = "pattern") -> tuple[int, int]:
    """(absolute start tick, length) of ``bars`` laid ``times`` over the project from display bar
    ``bar``; refused at the first bar whose meter is not the project's there."""
    start, length = fit(meter_map(m), bar, bars, times=times, noun=noun)
    if start + length >= END_TICK - BAR_ONE:
        raise ValueError(f"bar {bar} for {len(bars) * times} bar(s) runs past the end of the sequence")
    return start + BAR_ONE, length


def note_part(notes: Iterable[Note], *, velocity: float = 1.0,
              remap_maps: tuple[str, str] | None = None) -> tuple[Part, Counter]:
    """The notes as a Part, velocities scaled and drum notes translated -> (part, unmapped pitches)."""
    part = Part(PPQ, tuple(notes))
    if any(n.tick < 0 for n in part.notes):
        raise ValueError(f"a note at tick {min(n.tick for n in part.notes)} is before the pattern's start")
    if velocity != 1.0:
        part = scale_velocity(part, velocity)
    unmapped: Counter = Counter()
    if remap_maps:
        part, unmapped = remap(part, *remap_maps)
    return part, unmapped


def place_notes(data: bytes, *, track: str, start_tick: int, notes: Iterable[Note], bars_ticks: int,
                name: str, track_count: int | None, velocity: float = 1.0,
                remap_maps: tuple[str, str] | None = None) -> tuple[bytes, dict]:
    """A MIDI region on instrument track ``track`` from absolute ``start_tick`` (bar 1 at 38400)
    for ``bars_ticks``, holding ``notes`` from its start -> (project, `add_region`'s report with
    ``notes``, ``dropped`` and ``unmapped`` {pitch: count})."""
    if start_tick + bars_ticks >= END_TICK:
        raise ValueError(f"a region of {bars_ticks} ticks from tick {start_tick} runs past the end of the sequence")
    notes = list(notes)
    kept = [n for n in notes if n.tick < bars_ticks]
    part, unmapped = note_part(kept, velocity=velocity, remap_maps=remap_maps)
    data, report = add_region(data, track=track, start=start_tick, length=bars_ticks, name=name, track_count=track_count)
    if part.notes:
        data = edit_region(data, report["slot"], lambda have: edit(have, lambda p: merge(p, part, 0)), track_count=track_count)
    return data, {**report, "notes": len(part.notes), "dropped": len(notes) - len(kept),
                  "unmapped": dict(sorted(unmapped.items()))}


def place(data: bytes, p: Pattern, *, track: str, bar: int, track_count: int | None, repeat: int = 1,
          velocity: float = 1.0, remap_maps: tuple[str, str] | None = None) -> tuple[bytes, dict]:
    """``p`` laid ``repeat`` times back to back in one region from display bar ``bar``."""
    if repeat < 1:
        raise ValueError(f"--repeat {repeat}: at least once")
    start, length = lay_over(meter(data), bar, p.bars, repeat)
    notes, dropped = repeated(p.notes, p.ticks, repeat)
    data, report = place_notes(data, track=track, start_tick=start, notes=notes, bars_ticks=length, name=p.name,
                               track_count=track_count, velocity=velocity, remap_maps=remap_maps)
    return data, {**report, "dropped": report["dropped"] + dropped, "bars": len(p.bars) * repeat}


def place_phrase(data: bytes, ph: Phrase, *, track: str, bar: int, track_count: int | None) -> tuple[bytes, dict]:
    """``ph`` as one region on instrument track ``track`` from display bar ``bar``, the project's
    meter there held to the phrase's."""
    start, length = lay_over(meter(data), bar, (ph.sig,) * len(ph.picks), noun="phrase")
    return place_notes(data, track=track, start_tick=start, notes=ph.notes, bars_ticks=length,
                       name=f"Generated {ph.seed}", track_count=track_count)
