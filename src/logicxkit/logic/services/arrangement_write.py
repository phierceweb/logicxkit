"""Edit the arrangement track — rename, move, resize or delete a section. Written from the
read layout (`arrangement.py`); Logic has not re-saved one yet, so DERIVED.

A section's name record (`qSxT`) is rebuilt plain: payload size as u32 at +0 and +20, 98 at
+16 (where the text starts), 0x11 at +24 with 1 at +27 (a NUL-terminated string; an RTF one
carries 0x13), the name at +98 with its NUL, padded to an even length. Logic's re-save of a
renamed section kept the record byte for byte (2026-09-06). A new section is what Logic's
own add wrote: a text record on the lowest free multiple-of-4
slot among the `qSxT` records — a slot space of their own, not the registry's — with the
head in `data/section-text-12.3.1.json`, placed in slot order among them, and a 48-byte event
in tick order. Logic's re-save of one of ours kept both.
"""

from __future__ import annotations

import json
import struct

from .arrangement import (
    KINDS,
    LENGTH_AT,
    SECTION_TYPE,
    TEXT_NAME_AT,
    TEXT_SLOT_AT,
    TEXT_TAG,
    KIND_AT,
    Section,
    read_sections,
    section_sequence,
)
from .events import DATA_LINE, LINE, events
from .insert import HEADER, project_records, reassemble
from .recbuild import rec, slot_of, with_slot

PLAIN = 0x01000011
_SIZE_AT, _TEXT_AT_AT, _SIZE2_AT, _FORM_AT = 0, 16, 20, 24
_TEXT_DATA = "section-text-12.3.1.json"    # under the data root, `utils.data`


def plain_text_payload(name: str) -> bytes:
    text = name.encode("utf-8") + b"\0"
    text += b"\0" * (len(text) % 2)
    p = bytearray(TEXT_NAME_AT) + text
    for at in (_SIZE_AT, _SIZE2_AT):
        struct.pack_into("<I", p, at, len(p))
    struct.pack_into("<I", p, _TEXT_AT_AT, TEXT_NAME_AT)
    struct.pack_into("<I", p, _FORM_AT, PLAIN)
    return bytes(p)


def _section_at(data: bytes, number: int) -> Section:
    sections = read_sections(data)
    if not 1 <= number <= len(sections):
        raise ValueError(f"section {number}: the song has {len(sections)} section(s)")
    return sections[number - 1]


def rename_section(data: bytes, number: int, name: str) -> bytes:
    """Section ``number`` (1-based, time order) renamed; its text record rebuilt plain."""
    s = _section_at(data, number)
    records = project_records(data)
    out = []
    for r in records:
        if r.tag == TEXT_TAG and slot_of(r.raw) == s.text_slot:
            out.append(rec(TEXT_TAG, r.raw, plain_text_payload(name)))
        else:
            out.append(r.raw)
    return reassemble(data, out)


def _rewrite_events(data: bytes, edit) -> bytes:
    """``edit(list of (head, lines)) -> list`` over the arrangement sequence's events; the
    payload is rebuilt in tick order with its end marker kept."""
    records = project_records(data)
    i = section_sequence(records)
    if i is None:
        raise ValueError("the song has no arrangement track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    body = sum(len(e.head) + LINE * len(e.lines) for e in evs)
    tail = payload[body:]
    kept = edit([(bytearray(e.head), [bytearray(ln) for ln in e.lines]) for e in evs])
    kept.sort(key=lambda hl: struct.unpack_from("<I", hl[0], 4)[0])
    new = b"".join(bytes(h) + b"".join(bytes(ln) for ln in lines) for h, lines in kept) + tail
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, new)
    return reassemble(data, out)


def _match(head: bytearray, s: Section) -> bool:
    return struct.unpack_from("<II", head, 0) == (SECTION_TYPE, s.start)


def _data_line(lines: list[bytearray]) -> bytearray:
    return next(ln for ln in lines if ln[7] == DATA_LINE)


def move_section(data: bytes, number: int, start: int) -> bytes:
    """Section ``number`` starting at tick ``start``."""
    s = _section_at(data, number)

    def edit(evs):
        for head, _lines in evs:
            if _match(head, s):
                struct.pack_into("<I", head, 4, start)
        return evs
    return _rewrite_events(data, edit)


def resize_section(data: bytes, number: int, length: int) -> bytes:
    """Section ``number`` lasting ``length`` ticks."""
    s = _section_at(data, number)
    if length <= 0:
        raise ValueError("a section's length must be positive")

    def edit(evs):
        for head, lines in evs:
            if _match(head, s):
                struct.pack_into("<I", _data_line(lines), LENGTH_AT, length)
        return evs
    return _rewrite_events(data, edit)


def delete_section(data: bytes, number: int) -> bytes:
    """Section ``number`` taken off the track; its text record stays (an unreferenced name)."""
    s = _section_at(data, number)
    return _rewrite_events(data, lambda evs: [hl for hl in evs if not _match(hl[0], s)])


def _text_bytes(name: str) -> bytes:
    text = name.encode("utf-8") + b"\0"
    return text + b"\0" * (len(text) % 2)


def new_text_record(name: str, slot: int) -> bytes:
    """A section's name record as Logic makes one, on ``slot``."""
    from ...utils.data import data_file
    spec = json.loads(data_file("logic", _TEXT_DATA).read_text())
    p = bytearray(bytes.fromhex(spec["head"])) + _text_bytes(name)
    p[_FORM_AT + 3] = 1                       # Logic's re-save sets it, on a fresh record too
    for at in (_SIZE_AT, _SIZE2_AT):
        struct.pack_into("<I", p, at, len(p))
    raw = rec(TEXT_TAG, bytes.fromhex(spec["header"]) + bytes(p), bytes(p))
    return with_slot(raw, slot)


def free_text_slot(records) -> int:
    used = {slot_of(r.raw) for r in records if r.tag == TEXT_TAG}
    slot = 0
    while slot in used:
        slot += 4
    return slot


def new_section_event(template_head: bytes, *, start: int, length: int, kind: int, slot: int) -> bytes:
    head = bytearray(template_head)
    struct.pack_into("<I", head, 4, start)
    head[15] = 0
    data = bytearray(LINE)
    struct.pack_into("<I", data, TEXT_SLOT_AT, slot)
    data[7] = DATA_LINE
    struct.pack_into("<I", data, KIND_AT, kind)
    struct.pack_into("<I", data, LENGTH_AT, length)
    tail = bytearray(LINE)
    tail[7] = DATA_LINE
    return bytes(head) + bytes(data) + bytes(tail)


def add_section(data: bytes, name: str, *, start: int, length: int, kind: int = 0) -> bytes:
    """A new section ``name`` from tick ``start`` for ``length`` ticks, of ``kind``."""
    if length <= 0 or start < 0:
        raise ValueError("a section needs a positive length and a position")
    if kind not in KINDS:
        raise ValueError(f"kind {kind} is not one of {sorted(KINDS)}")
    records = project_records(data)
    i = section_sequence(records)
    if i is None:
        raise ValueError("the song has no arrangement track")
    evs = events(records[i].raw[HEADER:])
    if not evs:
        raise ValueError("the arrangement track has no section to pattern the event on")
    slot = free_text_slot(records)
    text = new_text_record(name, slot)
    event = new_section_event(evs[0].head, start=start, length=length, kind=kind, slot=slot)
    texts = [(k, slot_of(r.raw)) for k, r in enumerate(records) if r.tag == TEXT_TAG]
    after = next((k for k, s in reversed(texts) if s < slot), None)
    at = after + 1 if after is not None else texts[0][0]
    out = [r.raw for r in records]
    out.insert(at, text)
    out = reassemble(data, out)

    def edit(hl):
        hl.append((bytearray(event[:LINE]), [bytearray(event[LINE:2 * LINE]), bytearray(event[2 * LINE:])]))
        return hl
    return _rewrite_events(out, edit)
