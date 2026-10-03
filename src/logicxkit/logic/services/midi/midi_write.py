"""Write a MIDI region, and notes into one — what Logic's Pencil click and Event List Create
wrote on a blank project (2026-09-13, the public `midi-*` goldens; `midi.py` has the layouts).

A new region is Logic's own (packaged `midi-region-12.3.1.json`): its sequence triple goes after
the last table-slotted triple with a fresh id and the next free slot, its name re-stamped at
`+16`, its length at `+60` and its track object at `+204` past the name's padded end (the words
after the name move with it, as the longer names in the `sessionplayer-*` and
`midi-import-resave` goldens show); the song container gets the 80-byte entry in tick order
(`+4` the start with bar 1 at 34560, `+16` the object, `+20` the row, `+32` the slot); the
registry gets the slot pair. A note is two 16-byte lines spliced into the region's sequence in
tick order; the first event also sets three words Logic set once and never moved again (`+123`
= 84, `+172` = 44, `+192` = 1 past the name's end — meaning unmeasured, values as written).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

from ....utils.data import data_file
from ..song.events import BAR_ONE, LINE, events
from ..stream.stream import HEADER, project_records, reassemble
from .midi import (
    ENTRY_SLOT_AT, ENTRY_TICK_AT, LENGTH_AFTER_NAME, MIDI_ENTRY, NAME_AT, REGION_BAR_ONE, _is_midi, _name, region_length,
    sequence_offset,
)
from ..stream.recbuild import rec, with_owner, with_slot
from ..regions.regions import TAIL, TRACK_OBJECT_AT, TRACK_ROW_AT, _rows, entry_offsets, song_container
from ..stream.registry import GNOS_TAG, register_slot
from ..stream.sequence import QESM_ID_AT, Triple, free_seq_id, free_table_slot, index_table, sequences, triple_by_slot
from ..song.signature import meter
from ..arrange.stacks import read_tracks
from ..arrange.tracklist import arrange_run
from ..arrange.trackname import one_object, rows_named
from ..stream.validate import require_full_walk, require_valid

_DATA = "midi-region-12.3.1.json"
TRACK_AFTER_NAME = 204
FIRST_EVENT_STAMPS = {123: 84, 172: 44, 192: 1}      # after the name's end
NOTE_ON, NOTE_EXT = 0x90, 0x89
SELECTED_BIT = 0x80


def entry_tick(tick: int) -> int:
    """A song-container entry's `+4` for an absolute tick (bar 1 at 38400)."""
    return tick - BAR_ONE + REGION_BAR_ONE


def note_lines(*, tick: int, pitch: int, velocity: int, length: int, channel: int) -> tuple[bytes, bytes]:
    """The head and continuation line of a note at absolute ``tick`` (region-relative once
    the region start is subtracted by the caller)."""
    if not 0 <= pitch <= 127:
        raise ValueError(f"pitch {pitch} is not 0-127")
    if not 1 <= velocity <= 127:
        raise ValueError(f"velocity {velocity} is not 1-127")
    if not 1 <= channel <= 16:
        raise ValueError(f"channel {channel} is not 1-16")
    if length <= 0:
        raise ValueError("a note's length is at least one tick")
    if length >= 1 << 32:
        raise ValueError(f"a note's length of {length} ticks does not fit its 32-bit field")
    head = bytearray(LINE)
    head[0] = NOTE_ON | (channel - 1)
    struct.pack_into("<I", head, 4, tick)
    head[11], head[12], head[15] = velocity, pitch, 0x01
    ext = bytearray(LINE)
    ext[0], ext[7] = 0x40, NOTE_EXT
    struct.pack_into("<I", ext, 12, length)
    return bytes(head), bytes(ext)


def _template() -> dict[str, bytes]:
    t = json.loads(data_file("logic", _DATA).read_text())
    return {role: bytes.fromhex(r.get("header", "")) + bytes.fromhex(r["payload"]) for role, r in t["records"].items()}


def name_end(qesm_payload: bytes) -> int:
    """Where the words after a region's padded name begin."""
    n = struct.unpack_from("<H", qesm_payload, NAME_AT)[0]
    return NAME_AT + 2 + n + (n & 1)


def _with_name(qesm: bytes, name: str) -> bytes:
    """``qesm`` named ``name`` — UTF-8, padded to even, as Logic's rename to `Pad — é` wrote."""
    p = qesm[HEADER:]
    text = name.encode("utf-8")
    if len(text) > 0xFFFF:
        raise ValueError("a region's name is at most 65535 bytes of UTF-8")
    new = p[:NAME_AT] + struct.pack("<H", len(text)) + text + (b"\0" if len(text) & 1 else b"") + p[name_end(p):]
    return rec(b"qeSM", qesm, new)


KINDS = {"Audio ": "an audio track", "Aux ": "an aux track", "Output": "an output track", "Sub ": "a folder stack",
         "Bus ": "a bus track"}


def require_instrument(data: bytes, object_id: int, track: str, track_count: int | None) -> None:
    """Refuse a track object not bound to an ``Inst N`` channel: a MIDI region moves only
    between software instrument tracks (Logic Pro manual, Move regions)."""
    label = next((r["label"] for r in read_tracks(data, track_count) if r["object_id"] == object_id), None) or ""
    if not label.startswith("Inst "):
        kind = next((k for prefix, k in KINDS.items() if label.startswith(prefix)), "not an instrument track")
        raise ValueError(f"{track!r} is {kind} ({label or 'no mixer channel'}); "
                         "a MIDI region goes only on a software instrument track")


def _track(data: bytes, track: str, track_count: int | None) -> tuple[int, int]:
    """(object id, 1-based arrange row) of the track ``track`` names (`trackname.one_object`)."""
    object_id = one_object(read_tracks(data, track_count), track)
    records = project_records(data)
    return object_id, _rows(records, arrange_run(records, track_count))[object_id]


def add_region(data: bytes, *, track: str, start: int, length: int, name: str | None = None,
               track_count: int | None = None) -> tuple[bytes, dict]:
    """An empty MIDI region on ``track`` from absolute tick ``start`` (bar 1 at 38400) for
    ``length`` ticks -> ``(project, {track, object_id, slot, seq_id, start, length})``."""
    if length <= 0 or start < BAR_ONE - (BAR_ONE - REGION_BAR_ONE):
        raise ValueError("a region needs a positive length and a start at or after bar 0")
    require_full_walk(data)
    records = project_records(data)
    object_id, row = _track(data, track, track_count)
    require_instrument(data, object_id, track, track_count)
    name = name or next(r["name"] for r in read_tracks(data, track_count) if r["object_id"] == object_id)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None:
        raise ValueError("no song container to place the region in")
    seqs = sequences(records)
    slot = free_table_slot(records[index_table(records)].raw[HEADER:], seqs)
    seq_id = free_seq_id(seqs)
    t = _template()
    qesm = bytearray(_with_name(with_slot(t["qesm"], slot), name))
    end = HEADER + name_end(qesm[HEADER:])
    struct.pack_into("<I", qesm, HEADER + QESM_ID_AT, seq_id)
    struct.pack_into("<I", qesm, end + LENGTH_AFTER_NAME, length)
    struct.pack_into("<I", qesm, end + TRACK_AFTER_NAME, object_id)
    marker = with_slot(t["marker"], slot)
    qsve = with_slot(with_owner(t["qsve"], seq_id), slot)
    entry = bytearray(t["entry"])
    struct.pack_into("<I", entry, ENTRY_TICK_AT, entry_tick(start))
    struct.pack_into("<H", entry, TRACK_OBJECT_AT, object_id)
    struct.pack_into("<H", entry, TRACK_ROW_AT, row)
    struct.pack_into("<I", entry, ENTRY_SLOT_AT, slot)
    anchor = max(t_.end for t_ in seqs if t_.slot < 1024 and t_.start > song.start)
    out = []
    for i, r in enumerate(records):
        raw = r.raw
        if i == song.end:
            raw = rec(b"qSvE", raw, _place_entry(raw[HEADER:], bytes(entry)))
        elif r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, register_slot(raw[HEADER:], slot=slot))
        out.append(raw)
        if i == anchor:
            out += [bytes(qesm), marker, qsve]
    result = reassemble(data, out)
    require_valid(result)
    return result, {"track": track, "name": name, "object_id": object_id, "slot": slot, "seq_id": seq_id,
                    "start": start, "length": length}


def _place_entry(payload: bytes, entry: bytes) -> bytes:
    """``entry`` among the container's entries in tick order, before the tail; a flexed
    entry travels with its marker blocks."""
    body, tail = payload[:len(payload) - TAIL], payload[len(payload) - TAIL:]
    offsets = entry_offsets(payload)
    chunks = [body[off:(offsets[k + 1] if k + 1 < len(offsets) else len(body))] for k, off in enumerate(offsets)]
    tick = struct.unpack_from("<I", entry, ENTRY_TICK_AT)[0]
    at = next((k for k, c in enumerate(chunks) if struct.unpack_from("<I", c, ENTRY_TICK_AT)[0] > tick), len(chunks))
    chunks.insert(at, entry)
    return b"".join(chunks) + tail


@dataclass(frozen=True)
class TrackRegion:
    name: str
    start: int                 # absolute tick, bar 1 at 38400
    length: int                # ticks
    triple: Triple
    offset: int = 0            # ticks into its sequence the region plays from (`midi.SEQ_OFFSET_AT`)


def track_regions(data: bytes, track: str, track_count: int | None = None) -> list[TrackRegion]:
    """The MIDI regions `read_midi` reads on every track named ``track``, found by the entry's
    type and track object, in the song container's order."""
    object_ids = {r["object_id"] for r in rows_named(read_tracks(data, track_count), track)}
    if not object_ids:
        raise ValueError(f"no track named {track!r}")
    records = project_records(data)
    song = song_container(records, arrange_run(records, track_count))
    if song is None:
        return []
    payload, seqs, out = records[song.end].raw[HEADER:], sequences(records), []
    for off in entry_offsets(payload):
        kind, oid = struct.unpack_from("<H", payload, off)[0], struct.unpack_from("<H", payload, off + TRACK_OBJECT_AT)[0]
        if kind != MIDI_ENTRY or oid not in object_ids:
            continue
        t = triple_by_slot(seqs, struct.unpack_from("<I", payload, off + ENTRY_SLOT_AT)[0])
        if t is None or not all(_is_midi(e) for e in events(records[t.end].raw[HEADER:])):
            continue
        length = region_length(records[t.start].raw)
        start = struct.unpack_from("<I", payload, off + ENTRY_TICK_AT)[0] - REGION_BAR_ONE + BAR_ONE
        out.append(TrackRegion(_name(records[t.start].raw), start, length, t, sequence_offset(records[t.start].raw)))
    return out


def _spans(data: bytes, regions: list[TrackRegion]) -> str:
    m = meter(data)
    return ", ".join(f"{r.name!r} at bar {m.bar(r.start):g} for {m.bar(r.start + r.length) - m.bar(r.start):g} bar(s)"
                     for r in regions) or "none"


def _pick_region(data: bytes, track: str, tick: int, region_start: int | None, track_count: int | None) -> TrackRegion:
    """The region on ``track`` whose span holds ``tick``, or the one starting at ``region_start``."""
    regions = track_regions(data, track, track_count)
    if region_start is not None:
        hits = [r for r in regions if r.start == region_start]
        if len(hits) != 1:
            raise ValueError(f"no MIDI region on {track!r} starts at tick {region_start}" if not hits
                             else f"{len(hits)} MIDI regions on {track!r} start at tick {region_start}")
        return hits[0]
    hits = [r for r in regions if r.start <= tick < r.start + r.length]
    if len(hits) == 1:
        return hits[0]
    bar = meter(data).bar(tick)
    if not hits:
        raise ValueError(f"no MIDI region on {track!r} holds bar {bar:g}; its regions: {_spans(data, regions)}")
    raise ValueError(f"bar {bar:g} is inside {len(hits)} MIDI regions on {track!r}: {_spans(data, hits)}")


def first_event_stamped(qesm: bytes) -> bytes:
    """A region's `qeSM` with the words Logic set when its sequence gained a first event."""
    q = bytearray(qesm)
    end = HEADER + name_end(q[HEADER:])
    for off, value in FIRST_EVENT_STAMPS.items():
        struct.pack_into("<I", q, end + off, value)
    return bytes(q)


def add_note(data: bytes, *, track: str, tick: int, pitch: int, velocity: int, length: int,
             channel: int = 1, region_start: int | None = None, track_count: int | None = None) -> bytes:
    """A note at absolute ``tick`` in the MIDI region on ``track`` whose span holds it, or in
    the one starting at ``region_start``."""
    require_full_walk(data)
    region = _pick_region(data, track, tick, region_start, track_count)
    records, t = project_records(data), region.triple
    if tick < region.start:
        raise ValueError(f"tick {tick} is before the region's start {region.start}")
    rel = tick - region.start + BAR_ONE + region.offset
    head, ext = note_lines(tick=rel, pitch=pitch, velocity=velocity, length=length, channel=channel)
    payload = records[t.end].raw[HEADER:]
    evs = events(payload)
    body = sum(LINE + LINE * len(e.lines) for e in evs)
    lines = [(e.head, e.lines) for e in evs]
    at = next((k for k, (h, _l) in enumerate(lines) if struct.unpack_from("<I", h, 4)[0] > rel), len(lines))
    lines.insert(at, (head, (ext,)))
    new = b"".join(h + b"".join(ls) for h, ls in lines) + payload[body:]
    out = [r.raw for r in records]
    out[t.end] = rec(b"qSvE", records[t.end].raw, new)
    if not evs:
        out[t.start] = first_event_stamped(out[t.start])
    result = reassemble(data, out)
    require_valid(result)
    return result
