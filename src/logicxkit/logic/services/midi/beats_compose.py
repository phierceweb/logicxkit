"""A drum part over the arrangement: one region per section, planned by groovebin's
`library.compose` over the song's sections and meter map, written through `beats_place`."""

from __future__ import annotations

from groovebin.library.compose import Section, SectionPlan, plan_sections
from groovebin.library.pattern import Pattern

from ..song.arrangement import read_sections
from .beats_place import place_notes
from ..song.events import BAR_ONE
from .midi_edit import END_TICK, meter_map
from ..song.signature import meter


def plan(data: bytes, patterns: list[Pattern], *, fills: bool = False) -> list[SectionPlan]:
    """What each arrangement section gets, on groovebin's timeline (bar 1 at tick 0); nothing is
    written. A section with no room before the sequence's end is skipped."""
    sections = [Section(s.name, s.start - BAR_ONE, s.length) for s in read_sections(data)]
    plans = plan_sections(sections, meter_map(meter(data)), patterns, fills=fills)
    for p in plans:
        if p.beat is not None and p.section.start + p.section.length >= END_TICK - BAR_ONE:
            p.skipped = f"a section of {p.section.length} ticks from tick {p.section.start + BAR_ONE} has no room for a region"
            p.beat = None
    return plans


def compose(data: bytes, plans: list[SectionPlan], *, track: str, track_count: int | None) -> tuple[bytes, list[dict]]:
    """A region per planned section, named after its pattern -> (project, place_notes' reports)."""
    reports = []
    for p in plans:
        if p.beat is None:
            continue
        data, report = place_notes(data, track=track, start_tick=p.section.start + BAR_ONE, notes=p.notes,
                                   bars_ticks=p.section.length, name=p.beat.name, track_count=track_count)
        reports.append(report)
    return data, reports
