"""A channel's plug-in parameter lanes follow its slots. A point's type word names its insert —
0x50 plus the slot position, empty slots counted (`automation`) — so a writer that moves a slot
moves the points on it, and one that removes a plug-in takes its points out. They sit in the
automation folder of the Environment object the channel is bound to, and in any region
automation naming that object."""

from __future__ import annotations

import struct

from .automation import (
    FADER_POINT,
    FOLDER_NAME,
    PARAM_LAST,
    QESM_OBJECT_AT,
    REFERENCE,
    ROOT_NAME,
    Lane,
    named,
    param_slot,
    read_automation,
)
from .automation_write import _order
from .binding import bound_objects
from .events import LINE, events
from .stream import HEADER, project_records, reassemble
from .recbuild import rec
from .sequence import sequences


def channel_object(data: bytes, owner: int) -> int | None:
    """The Environment object a channel is bound to, whose automation folder holds its lanes."""
    return bound_objects(data).get(owner)


def insert_lanes(data: bytes, owner: int, insert: int) -> list[Lane]:
    """The channel's own parameter lanes on ``insert`` (not a region's)."""
    obj = channel_object(data, owner)
    return [lane for a in read_automation(data) if obj is not None and a.track_object == obj
            for lane in a.lanes if lane.slot == insert and not lane.region]


def move_lanes(data: bytes, owner: int, moves: dict[int, int | None]) -> tuple[bytes, dict[str, int]]:
    """The channel's parameter points on insert ``i`` moved to ``moves[i]``, dropped where that is
    None; points on other inserts stay -> ``(project, {"moved": n, "dropped": n})``."""
    counts = {"moved": 0, "dropped": 0}
    obj = channel_object(data, owner)
    if obj is None or not moves:
        return data, counts
    last = PARAM_LAST - FADER_POINT
    for to in moves.values():
        if to is not None and not 1 <= to <= last:
            raise ValueError(f"insert {to} has no automation address (1 to {last}); its lanes cannot follow it")
    records = project_records(data)
    out = [r.raw for r in records]
    for end, folder in _sequence_ends(records, obj):
        payload = records[end].raw[HEADER:]
        evs = events(payload)
        body = sum(LINE + LINE * len(e.lines) for e in evs)
        kept, changed = [], False
        for e in evs:
            raw = e.head + b"".join(e.lines)
            slot = param_slot(e.type)
            if slot in moves:
                changed = True
                if moves[slot] is None:
                    counts["dropped"] += 1
                    continue
                head = bytearray(raw)
                struct.pack_into("<H", head, 0, (e.type & ~0xFF) | (FADER_POINT + moves[slot]))
                raw = bytes(head)
                counts["moved"] += 1
            kept.append(raw)
        if changed:
            if folder:                              # a folder keeps Logic's order; the insert is part of it
                kept.sort(key=_order)
            out[end] = rec(records[end].tag, records[end].raw, b"".join(kept) + payload[body:])
    return (reassemble(data, out) if counts["moved"] or counts["dropped"] else data), counts


def _sequence_ends(records, obj: int) -> list[tuple[int, bool]]:
    """(the points record, is the track's folder) of every sequence holding ``obj``'s automation:
    its folder, and an unreferenced sequence naming it (a region's own automation)."""
    triples = sequences(records)
    referenced = set()
    for t in triples:
        for e in events(records[t.end].raw[HEADER:]):
            if e.type == REFERENCE:
                referenced.add(struct.unpack_from("<I", e.data, 0)[0])
    out = []
    for t in triples:
        q = records[t.start].raw[HEADER:]
        if len(q) < QESM_OBJECT_AT + 4 or struct.unpack_from("<I", q, QESM_OBJECT_AT)[0] != obj:
            continue
        folder = bool(named(q, FOLDER_NAME))
        if folder or not (t.slot in referenced or named(q, ROOT_NAME)):
            out.append((t.end, folder))
    return out
