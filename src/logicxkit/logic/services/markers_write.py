"""Edit the marker track — add, rename, move or delete a marker (`markers.py` has the layout;
`arrangement_write` the pieces shared with sections). A new marker is a 48-byte 0x12 event in
tick order on the marker sequence with a plain name record on the lowest free text slot; a
rename rebuilds the record plain; a delete takes the event and its record. DERIVED until
Logic re-saves one of ours."""

from __future__ import annotations

import struct

from .arrangement import SECTION_TYPE, TEXT_SLOT_AT, TEXT_TAG, marker_sequence
from .arrangement_write import _data_line, _rewrite_events, free_text_slot, new_section_event, new_text_record, plain_text_payload
from .events import LINE
from .stream import project_records, reassemble
from .markers import TO_NEXT, Marker, read_markers
from .recbuild import rec, slot_of


def _marker_at(data: bytes, number: int) -> Marker:
    markers = read_markers(data)
    if not 1 <= number <= len(markers):
        raise ValueError(f"marker {number}: the song has {len(markers)} marker(s)")
    return markers[number - 1]


def _sequence(records) -> int:
    t = marker_sequence(records)
    if t is None:
        raise ValueError("the song has no marker track; Logic writes one into every project it saves")
    return t.end


def _match(hl, m: Marker) -> bool:
    """The event at ``m``'s tick naming ``m``'s text record (two markers can share a bar)."""
    head, lines = hl
    return (struct.unpack_from("<HHI", head, 0)[:3:2] == (SECTION_TYPE, m.tick)
            and struct.unpack_from("<I", _data_line(lines), TEXT_SLOT_AT)[0] == m.text_slot)


def add_marker(data: bytes, name: str, *, tick: int, length: int = TO_NEXT) -> bytes:
    """A marker ``name`` at absolute ``tick``, running ``length`` ticks (1: to the next marker)."""
    if tick < 0 or length < 1:
        raise ValueError("a marker needs a position and a length of at least one tick")
    records = project_records(data)
    i = _sequence(records)
    slot = free_text_slot(records)
    text = new_text_record(name, slot)
    head = bytearray(LINE)
    struct.pack_into("<HHI", head, 0, SECTION_TYPE, 0, tick)
    event = new_section_event(bytes(head), start=tick, length=length, kind=0, slot=slot)
    texts = [(k, slot_of(r.raw)) for k, r in enumerate(records) if r.tag == TEXT_TAG]
    after = next((k for k, s in reversed(texts) if s < slot), None)
    at = after + 1 if after is not None else (texts[0][0] if texts else len(records))
    out = [r.raw for r in records]
    out.insert(at, text)
    out = reassemble(data, out)

    def edit(hl):
        hl.append((bytearray(event[:LINE]), [bytearray(event[LINE:2 * LINE]), bytearray(event[2 * LINE:])]))
        return hl
    return _rewrite_events(out, edit, at=i + 1 if at <= i else i)


def rename_marker(data: bytes, number: int, name: str) -> bytes:
    m = _marker_at(data, number)
    records = project_records(data)
    out = [rec(TEXT_TAG, r.raw, plain_text_payload(name)) if r.tag == TEXT_TAG and slot_of(r.raw) == m.text_slot else r.raw
           for r in records]
    return reassemble(data, out)


def move_marker(data: bytes, number: int, tick: int) -> bytes:
    m = _marker_at(data, number)
    if tick < 0:
        raise ValueError("a marker's position is at or after tick 0")

    def edit(evs):
        for hl in evs:
            if _match(hl, m):
                struct.pack_into("<I", hl[0], 4, tick)
        return evs
    return _rewrite_events(data, edit, at=_sequence(project_records(data)))


def delete_marker(data: bytes, number: int) -> bytes:
    """Marker ``number`` and its name record taken off, as Logic's delete does."""
    m = _marker_at(data, number)
    records = project_records(data)
    i = _sequence(records)
    kept = [r.raw for r in records if not (r.tag == TEXT_TAG and slot_of(r.raw) == m.text_slot)]
    gone = len(records) - len(kept)
    text_before = any(r.tag == TEXT_TAG and slot_of(r.raw) == m.text_slot for r in records[:i])
    data = reassemble(data, kept)
    return _rewrite_events(data, lambda evs: [hl for hl in evs if not _match(hl, m)], at=i - gone if text_before else i)
