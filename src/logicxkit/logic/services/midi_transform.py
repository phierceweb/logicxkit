"""Logic's Transform window over one MIDI region: a selection by note field — position in song
bars, pitch, velocity, length, channel — and groovebin's operations and presets on the selected
notes, written back through `midi_edit` so unselected notes and every other event keep their
bytes. The arithmetic is groovebin's; this maps the region onto its timeline and refuses what
would need the region's controller, bend and program events moved."""

from __future__ import annotations

import random
from dataclasses import dataclass

from groovebin.transforms import BY_NAME, Range, apply_all, position_ticks, run, select

from .events import BAR_ONE
from .midi import MidiRegion
from .midi_edit import EventLines, edit, edit_region, is_note, meter_map, require_no_poly_aftertouch
from .signature import Meter, meter

Step = tuple[str, object]          # ("ops", [Operation, …]) or ("preset", (name, value))
RETIMES = ("reverse-position", "swing")    # presets that move notes past the events; humanize too when pos > 0


@dataclass(frozen=True)
class Transform:
    select: dict[str, Range]        # by note field; a position Range is in song bars
    steps: tuple[Step, ...]

    @property
    def moves_notes_past_events(self) -> bool:
        """Any step that moves a note's tick, whatever the operation: the events keep theirs."""
        for kind, payload in self.steps:
            if kind == "ops":
                if any(o.field == "tick" for o in payload):
                    return True
            elif payload[0] == "humanize":
                if (payload[1] or BY_NAME["humanize"].default)[0]:
                    return True
            elif payload[0] in RETIMES:
                return True
        return False


@dataclass(frozen=True)
class Report:
    selected: int
    notes: int


def conditions(transform: Transform, m: Meter, region: MidiRegion) -> dict[str, Range]:
    """The transform's ranges in the region's units: position bars -> ticks from the region's start."""
    meters = meter_map(m)
    return {f: (position_ticks(r, meters, start=region.start - BAR_ONE) if f == "tick" else r)
            for f, r in transform.select.items()}


def transformed(lines: EventLines, transform: Transform, m: Meter, region: MidiRegion,
                rng: random.Random) -> tuple[EventLines, Report]:
    """``lines`` with the transform applied to the notes the selection picks (every note without one)."""
    require_no_poly_aftertouch(lines, "a transform")
    others = sum(not is_note(h) for h, _ls in lines)
    if others and transform.moves_notes_past_events:
        raise ValueError(f"the region holds {others} controller, bend or program event(s); retiming the notes "
                         "would leave them in place")
    where, meters, start = conditions(transform, m, region), meter_map(m), region.start - BAR_ONE
    picked: list[int] = []

    def change(part):
        # One selection for every pass, carried by each note's tag: a pass can move and reorder the
        # notes, so neither re-picking nor an index mask would name the same notes. None is every note.
        selected = None if not where else select(part, **where)
        chosen = None if selected is None else {part.notes[i].tag for i in selected}
        picked.append(len(part.notes) if selected is None else len(selected))
        for kind, payload in transform.steps:
            mask = None if chosen is None else frozenset(k for k, n in enumerate(part.notes) if n.tag in chosen)
            part = apply_all(part, mask, payload, seed=rng, meters=meters, start=start) if kind == "ops" else \
                run(part, mask, payload[0], payload[1], seed=rng, meters=meters, start=start)
        return part
    new = edit(lines, change)
    return new, Report(picked[0], sum(is_note(h) for h, _ls in lines))


def apply_transform(data: bytes, region: MidiRegion, transform: Transform, *, rng: random.Random,
                    track_count: int | None = None) -> tuple[bytes, Report]:
    """``region`` transformed in place through the integrity gate -> (project, report)."""
    m, reports = meter(data), []

    def change(lines: EventLines) -> EventLines:
        new, report = transformed(lines, transform, m, region, rng)
        reports.append(report)
        return new
    data = edit_region(data, region.slot, change, track_count=track_count)
    return data, reports[0]
