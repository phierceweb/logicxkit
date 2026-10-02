"""A MIDI region's event lines (`midi.py` has the layouts) as a groovebin `Part` and back, so
groovebin's transforms and note maps do the arithmetic, and the region writers that apply a
change to a project by the region's sequence slot.

``EventLines`` is each event's 16-byte head with its continuation lines; `split` and `join` take
a region's `qSvE` payload apart and back without moving a byte. `to_part` keeps every line on its
note's or event's ``tag`` and `from_part` rewrites only what an edit may change — tick, pitch,
velocity, length, a two-byte message's data — filing the events as groovebin orders them: at one
tick program change, controller, notes low to high, pitch bend, the order Logic writes. Part ticks
are region-relative with 0 at the region's start (38400 in the lines).
"""

from __future__ import annotations

import struct
from collections import Counter
from collections.abc import Callable

from groovebin.events import Event, Note, ordered
from groovebin.maps import remap as remap_part
from groovebin.song import Part
from groovebin.timing import MeterMap
from groovebin.transforms import merge

from .events import BAR_ONE, END_TYPE, LINE, PPQ, events
from .stream import HEADER, project_records, reassemble
from .midi import DATA1_AT, DATA2_AT, LENGTH_AT, LENGTH_LINE, MidiRegion, read_midi
from .midi_write import _pick_region, add_region, first_event_stamped, note_lines, region_length
from .recbuild import rec
from .sequence import Triple, sequences, triple_by_slot
from .signature import Meter, meter
from .validate import require_full_walk, require_valid

EventLines = list[tuple[bytes, tuple[bytes, ...]]]

TICK_AT = 4
END_TICK = 0x3FFFFFFF
NOTE, POLY_AFTERTOUCH, CONTROLLER, PROGRAM, PRESSURE, BEND = 0x90, 0xA0, 0xB0, 0xC0, 0xD0, 0xE0
MEASURED = {PROGRAM, CONTROLLER, NOTE, BEND}      # the kinds whose same-tick order Logic's saves show
ONE_BYTE = {PROGRAM, PRESSURE}


def split(payload: bytes) -> tuple[EventLines, bytes]:
    """(the events' lines, the end marker and everything after it)."""
    lines = [(e.head, e.lines) for e in events(payload)]
    body = sum(LINE + LINE * len(ls) for _h, ls in lines)
    rest = payload[body:]
    if join(lines, rest) != payload or (rest and struct.unpack_from("<H", rest, 0)[0] != END_TYPE):
        raise ValueError("the sequence holds a continuation line that belongs to no event")
    return lines, rest


def join(lines: EventLines, rest: bytes) -> bytes:
    return b"".join(h + b"".join(ls) for h, ls in lines) + rest


def kind(head: bytes) -> int:
    return head[0] & 0xF0


NOTE_OFF = 0x80


def is_note(head: bytes) -> bool:
    return kind(head) == NOTE


def tick(head: bytes) -> int:
    return struct.unpack_from("<I", head, TICK_AT)[0]


def _put(head: bytes, at: int, value: int, fmt: str = "B") -> bytes:
    buf = bytearray(head)
    struct.pack_into(fmt, buf, at, value)
    return bytes(buf)


def to_part(lines: EventLines) -> Part:
    """The lines as a Part at 960 PPQ, each note and event tagged with its own lines."""
    notes, others = [], []
    for h, ls in lines:
        at, channel = tick(h) - BAR_ONE, (h[0] & 0x0F) + 1
        if is_note(h):
            ext = next((ln for ln in ls if ln[7] == LENGTH_LINE), None)
            length = struct.unpack_from("<I", ext, LENGTH_AT)[0] if ext else 0
            notes.append(Note(at, length, channel, h[DATA1_AT], h[DATA2_AT], tag=(h, ls)))
        elif kind(h) == NOTE_OFF:
            raise ValueError(f"a note-off line (0x80) at tick {tick(h)}: unmeasured, so the region is not edited")
        else:
            data = bytes([h[0], h[DATA1_AT]]) + (b"" if kind(h) in ONE_BYTE else bytes([h[DATA2_AT]]))
            others.append(Event(at, data, tag=(h, ls)))
    return Part(PPQ, tuple(notes), tuple(others))


def _line_of(item: Note | Event) -> tuple[bytes, tuple[bytes, ...]]:
    at = item.tick + BAR_ONE
    if at < 0:
        raise ValueError("an event would land before the start of the sequence")
    if at >= END_TICK:
        raise ValueError("an event would land past the end of the sequence")
    if isinstance(item, Note):
        if item.tag is None:
            head, ext = note_lines(tick=at, pitch=item.pitch, velocity=item.velocity, length=max(1, item.length), channel=item.channel)
            return head, (ext,)
        head, ls = item.tag
        head = _put(_put(_put(head, TICK_AT, at, "<I"), DATA1_AT, item.pitch), DATA2_AT, item.velocity)
        head = _put(head, 0, (head[0] & 0xF0) | (item.channel - 1))     # the status byte's low nibble
        ls = tuple(_put(ln, LENGTH_AT, max(1, item.length), "<I") if ln[7] == LENGTH_LINE else ln for ln in ls)
        return head, ls
    if item.tag is None:
        raise ValueError(f"writing a new {item.kind} event is unmeasured; only notes are made from nothing")
    head, ls = item.tag
    head = _put(_put(head, TICK_AT, at, "<I"), DATA1_AT, item.data[1])
    return (_put(head, DATA2_AT, item.data[2]) if len(item.data) > 2 else head), ls


def from_part(part: Part) -> EventLines:
    """The Part's notes and events as lines in Logic's order; refused when a kind whose order
    is unmeasured shares a tick with another kind, or a tick leaves the sequence."""
    items = ordered([*part.notes, *part.events])
    kinds: dict[int, set[int]] = {}
    for item in items:
        k = NOTE if isinstance(item, Note) else item.data[0] & 0xF0
        kinds.setdefault(item.tick, set()).add(k)
    for t, found in kinds.items():
        if found - MEASURED and len(found) > 1:
            raise ValueError(f"no measured order for a 0x{min(found - MEASURED):02x} event beside other kinds at "
                             f"tick {t + BAR_ONE}")
    return [_line_of(item) for item in items]


def edit(lines: EventLines, change: Callable[[Part], Part]) -> EventLines:
    return from_part(change(to_part(lines)))


def require_no_poly_aftertouch(lines: EventLines, what: str) -> None:
    """Where Logic keeps a polyphonic aftertouch event's pitch is unmeasured, so a pitch edit
    could split it from its note."""
    held = sum(kind(h) == POLY_AFTERTOUCH for h, _ls in lines)
    if held:
        raise ValueError(f"{held} polyphonic aftertouch event(s): where Logic keeps their pitch is unmeasured, "
                         f"and {what} would split them from their notes")


def remap(lines: EventLines, src: str, dst: str) -> tuple[EventLines, Counter]:
    """Every note's pitch translated from map ``src`` to ``dst``; a note with no counterpart keeps
    its pitch and is counted by pitch."""
    require_no_poly_aftertouch(lines, "a remap")
    part, unmapped = remap_part(to_part(lines), src, dst)
    return from_part(part), unmapped


def meter_map(m: Meter) -> MeterMap:
    """Logic's signatures (bar 1 at 38400) as a groovebin meter map with bar 1 at tick 0; one
    before bar 1 folds onto it."""
    changes: dict[int, tuple[int, int, int]] = {}
    for s in m.times:
        at = max(s.tick - BAR_ONE, 0)
        changes[at] = (at, s.numerator, s.denominator)
    return MeterMap(PPQ, tuple(changes[k] for k in sorted(changes)))


def _source(data: bytes, slot: int, track_count: int | None) -> tuple[list[MidiRegion], Triple, EventLines]:
    """Every region playing sequence ``slot`` (a copy only reads it), its triple and its lines."""
    hits = [r for r in read_midi(data, track_count) if r.slot == slot]
    if not hits:
        raise ValueError(f"no MIDI region plays sequence slot {slot}")
    records = project_records(data)
    t = triple_by_slot(sequences(records), slot)
    return hits, t, split(records[t.end].raw[HEADER:])[0]


def _located(data: bytes, slot: int, track_count: int | None) -> tuple[MidiRegion, Triple, EventLines]:
    hits, t, lines = _source(data, slot, track_count)
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} regions play sequence slot {slot}; an edit to one would change them all")
    return hits[0], t, lines


def _written(data: bytes, t: Triple, lines: EventLines) -> bytes:
    records = project_records(data)
    had, rest = split(records[t.end].raw[HEADER:])
    out = [r.raw for r in records]
    out[t.end] = rec(b"qSvE", records[t.end].raw, join(lines, rest))
    if lines and not had:
        out[t.start] = first_event_stamped(out[t.start])
    result = reassemble(data, out)
    require_valid(result)
    return result


def _left(old: EventLines, new: EventLines, end: int) -> tuple[str, int] | None:
    """The first event ``new`` puts outside ``[BAR_ONE, end)`` that ``old`` had inside, each
    kind's events paired in tick order: ``(which side, its tick)``."""
    for side, outside, first in (("past the end", lambda t: t >= end, min), ("before the start", lambda t: t < BAR_ONE, max)):
        for k in sorted({kind(h) for h, _ls in new}):
            was = sum(1 for h, _ls in old if kind(h) == k and outside(tick(h)))
            now = [tick(h) for h, _ls in new if kind(h) == k and outside(tick(h))]
            if len(now) > was:
                return side, first(now)
    return None


def edit_region(data: bytes, slot: int, change: Callable[[EventLines], EventLines], *,
                track_count: int | None = None) -> bytes:
    """The region on sequence ``slot`` with ``change`` applied to its event lines. An event the
    change takes out of the region's span is refused — what Logic does with it is unmeasured; one
    already outside may move."""
    require_full_walk(data)
    region, t, lines = _located(data, slot, track_count)
    require_no_offset(region)
    new = change(lines)
    length = region_length(project_records(data)[t.start].raw)
    left = _left(lines, new, BAR_ONE + length)
    if left:
        m = meter(data)
        raise ValueError(f"an event would move to bar {m.bar(region.start + left[1] - BAR_ONE):g}, {left[0]} of "
                         f"region {region.name!r} on {region.track!r} (bar {m.bar(region.start):g} to "
                         f"{m.bar(region.start + length):g}); moving an event out of its region is not supported")
    return _written(data, t, new)


def require_no_offset(region) -> None:
    """A split's second piece plays its sequence from an offset (`midi.SEQ_OFFSET_AT`); how an
    edit lands on such a region is unmeasured."""
    if region.offset:
        raise ValueError(f"region {region.name!r} on {region.track!r} plays its sequence from tick {region.offset} "
                         "(a split's second piece); editing it is not supported")


def copy_region(data: bytes, slot: int, track: str, start_tick: int,
                track_count: int | None = None) -> tuple[bytes, dict]:
    """A new region on ``track`` from absolute ``start_tick`` with the name, length and events of
    the one on sequence ``slot`` -> ``(project, add_region's report + events, loop)``. The loop
    flag is not copied; ``loop`` says whether the source had it."""
    require_full_walk(data)
    (source, *_aliases), t, lines = _source(data, slot, track_count)
    require_no_offset(source)
    length = region_length(project_records(data)[t.start].raw)
    data, report = add_region(data, track=track, start=start_tick, length=length, name=source.name or None,
                              track_count=track_count)
    if lines:
        data = _written(data, triple_by_slot(sequences(project_records(data)), report["slot"]), lines)
    return data, {**report, "events": len(lines), "loop": source.loop}


def copy_notes(data: bytes, slot: int, at_tick: int, *, track: str | None = None,
               track_count: int | None = None) -> tuple[bytes, dict]:
    """The events the region on sequence ``slot`` plays, merged into the region on ``track`` (the
    source's own by default) that holds ``at_tick``, placed so the source's start lands there."""
    require_full_walk(data)
    sources, t, lines = _source(data, slot, track_count)
    require_no_offset(sources[0])
    length = region_length(project_records(data)[t.start].raw)
    lines = [hl for hl in lines if BAR_ONE <= tick(hl[0]) < BAR_ONE + length]      # what the region plays
    tracks = sorted({r.track for r in sources}, key=str)
    if track is None and len(tracks) > 1:
        raise ValueError(f"regions on {len(tracks)} tracks play sequence slot {slot}; name the track to copy into")
    name = track or tracks[0]
    target = _pick_region(data, name, at_tick, None, track_count)
    moved = to_part(lines)
    data = edit_region(data, target.triple.slot, lambda have: edit(have, lambda p: merge(p, moved, at_tick - target.start)),
                       track_count=track_count)
    return data, {"track": name, "region": target.name, "slot": target.triple.slot, "events": len(lines)}
