"""Edits of a region's placement — move, a move onto another track, trim, split, loop, mute, rename,
fades — over its
song-container entry (`regions.py`), its record (`audio_regions.py`) or its sequence
(`midi.py`), as Logic's own edits of one blank-born project wrote them (2026-09-15, the
`regions-a*` goldens). A region is named by its number in the `regions` listing (`listed`).

Audio lengths are frames; ticks convert through samples per tick at one tempo. A split keeps the
parent's record slot: the piece gets a record with the next piece number in its header owner,
its time at its UUID's, and an entry with that number at `+40`, named `<stem>.N` past the file's
highest piece or `.N` (`audio_regions.name_numbers`), as the cutters name theirs; the fade-out and the selection move to the piece (`fades.split_fades`); the file
record's region count goes up by one (Logic loads that many), and the
registry gains a blank pair for the next free sequence slot (Logic's split consumes one) and,
where the registry holds a run of them, a blank kind-0x1e pair keyed by the parent's slot, as
Logic's own split of a blank-born project did — a recorded project's registry held no such run
and Logic's own splits of it added none (2026-10-25), so none is written there; a MIDI
split gives the piece its own sequence triple on the next free slot holding the parent's events
unchanged, playing from the cut through the sequence offset past the `qeSM` name. Loop-on writes the
entry's loop length: a MIDI region's length in ticks, an audio region's length in ticks times
1000 (one measurement).
"""
from __future__ import annotations

import struct

from .audio_regions import (
    FILE_TAG, REGION_COUNT_AT, REGION_FRAMES_AT, REGION_MUTE_AT, REGION_MUTE_BIT, REGION_OFFSET_AT, REGION_TAG, magic_at,
    PIECE_LIMIT, name_numbers, region_key,
)
from .audio_write import ENTRY_SELECTED_AT, REGION_TIME_AT, REGION_UUID_FROM_END, SELECTED, _uuid_time
from ..song.events import BAR_ONE
from .fades import Fade, split_fades, with_fade
from ..stream.stream import HEADER, project_records
from ..midi.midi import sequence_offset
from ..midi.midi_write import _with_name, region_length
from ..stream.recbuild import fresh_uuid, rec, slot_of, with_owner, with_slot
from .region_entry import (
    _anchors_after, _container, _entry, _finish, _flagged, _frames, _piece_entry, _record_with_name, _require_sole,
    _require_unflexed, _rewrite, _shifted, _with_length, _with_loop, _with_offset, _with_start,
)
from .region_locate import located
from .regions import TRACK_OBJECT_AT, TRACK_ROW_AT, _rows
from ..arrange.stacks import read_tracks
from ..arrange.tracklist import arrange_run
from ..arrange.trackname import one_object
from ..stream.registry import GNOS_TAG, has_run, register_after_run, register_slot
from ..stream.sequence import QESM_ID_AT, free_seq_id, free_table_slot, index_table, sequences, triple_by_slot

AUDIO_LOOP_SCALE = 1000
SPLIT_LINK_FROM_END, NO_LINK = 11, 0xFFFFFFFF      # the record's split-link word, after the name, so from its end: Logic's split sets the parent's to NO_LINK and the piece's to 1
SPLIT_KIND = 0x1E                                                    # registry pair keyed by the parent's slot


def move_region(data: bytes, number: int, tick: int, track_count: int | None = None) -> bytes:
    loc = located(data, number, track_count)
    if tick < BAR_ONE:
        raise ValueError("a region starts at or after bar 1")
    _require_sole(loc, "moving")
    records = project_records(data)
    song, payload = _container(records, track_count)
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.region.at, _flagged(_entry(payload, loc), tick=tick)))
    if loc.midi:
        t = triple_by_slot(sequences(records), loc.midi.slot)
        out[t.start] = _with_start(records[t.start].raw, tick)
    return _finish(data, out)


def audio_track(tracks: list[dict], track: str) -> int:
    """The object of the audio track ``track`` names (`trackname.one_object`); a track on another
    kind of channel is refused, since Logic places audio regions on audio tracks alone."""
    object_id = one_object(tracks, track)
    label = next(t["label"] for t in tracks if t["object_id"] == object_id)
    if not label.startswith("Audio "):
        raise ValueError(f"{track!r} is not an audio track (its channel is {label or 'none'}); an audio region goes on one")
    return object_id


def move_to_track(data: bytes, number: int, track: str, track_count: int | None = None, validate: bool = True) -> bytes:
    """Region ``number`` on the track ``track`` names, where it is in time: the entry's track object
    and row, the two fields Logic's own drag of a piece onto another track changed, its record
    untouched (`vocal-pieces-moved-logic`, Logic 12.4, 2026-10-25). An audio region onto an audio
    track; a MIDI region's sequence names its track too, and no move of one is measured."""
    loc = located(data, number, track_count)
    if loc.audio is None:
        raise ValueError(f"region {number} is a MIDI region; moving one onto another track is unmeasured")
    object_id = audio_track(read_tracks(data, track_count), track)
    if object_id == loc.audio.object_id:
        raise ValueError(f"region {number} {loc.audio.name!r} is already on {track!r}")
    records = project_records(data)
    song, payload = _container(records, track_count)
    entry = bytearray(_entry(payload, loc))
    struct.pack_into("<H", entry, TRACK_OBJECT_AT, object_id)
    struct.pack_into("<H", entry, TRACK_ROW_AT, _rows(records, arrange_run(records, track_count))[object_id])
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.audio.at, bytes(entry)))
    return _finish(data, out, validate)


def trim_region(data: bytes, number: int, *, start: int | None = None, length: int | None = None,
                spt: float | None = None, track_count: int | None = None, validate: bool = True) -> bytes:
    """Region ``number`` starting at tick ``start`` (its content kept in place) and lasting
    ``length`` ticks."""
    loc = located(data, number, track_count)
    r = loc.region
    if start is not None and start < BAR_ONE:
        raise ValueError("a region starts at or after bar 1")
    _require_sole(loc, "trimming")
    records = project_records(data)
    song, payload = _container(records, track_count)
    _require_unflexed(payload, loc, "trimming", spt)
    out = [r_.raw for r_ in records]
    entry = _entry(payload, loc)
    delta = 0 if start is None else start - r.start
    blocks = None
    if loc.audio:
        a = loc.audio
        offset, frames = a.offset + _frames(delta, spt), a.frames - _frames(delta, spt)
        if length is not None:
            frames = _frames(length, spt)
        if offset < 0 or frames <= 0 or (a.file and offset + frames > a.file.frames):
            raise ValueError(f"the trim runs outside the file ({a.file.frames if a.file else '?'} frames)")
        body = bytearray(records[a.record].raw)
        struct.pack_into("<I", body, HEADER + REGION_OFFSET_AT, offset)
        struct.pack_into("<I", body, HEADER + REGION_FRAMES_AT, frames)
        out[a.record] = bytes(body)
        loop_length = round(frames / spt * AUDIO_LOOP_SCALE) if r.loop else None
        blocks = _anchors_after(payload, loc, frames, spt, shift=offset - a.offset)
    else:
        t = triple_by_slot(sequences(records), loc.midi.slot)
        have = region_length(records[t.start].raw)
        new_length = (have - delta) if length is None else length
        if new_length <= 0:
            raise ValueError("the trim leaves the region no length")
        q = _with_length(records[t.start].raw, new_length)
        if delta:
            q = _with_start(q, start)
            out[t.end] = _shifted(records[t.end].raw, delta)
        out[t.start] = q
        loop_length = new_length if r.loop else None
    if delta or r.loop or blocks is not None:
        entry = _flagged(entry, tick=start if delta else None, loop=True if r.loop else None, loop_length=loop_length)
        out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, r.at, entry, blocks=blocks))
    return _finish(data, out, validate)



def split_region(data: bytes, number: int, tick: int, *, spt: float | None = None,
                 track_count: int | None = None, validate: bool = True) -> bytes:
    """Region ``number`` cut at absolute ``tick``; the part from the cut becomes a new region."""
    loc = located(data, number, track_count)
    r = loc.region
    if r.loop:
        raise ValueError("a looping region is not split; switch its loop off first")
    _require_sole(loc, "splitting")
    records = project_records(data)
    song, payload = _container(records, track_count)
    _require_unflexed(payload, loc, "splitting", spt)
    out = [r_.raw for r_ in records]
    entry = _entry(payload, loc)
    delta = tick - r.start
    if loc.audio:
        a = loc.audio
        frames = _frames(delta, spt)
        if not 0 < frames < a.frames:
            raise ValueError(f"the cut at tick {tick} is not inside the region")
        slot = region_key(records[a.record].raw)[0]
        piece = 1 + max(region_key(r_.raw)[1] for r_ in records if r_.tag == REGION_TAG and region_key(r_.raw)[0] == slot)
        if piece > PIECE_LIMIT:
            raise ValueError(f"region {number}'s file already holds piece {piece - 1}, the most an entry's two bytes hold")
        parent_entry, piece_entry = (bytearray(e) for e in split_fades(entry, _piece_entry(entry, tick, piece=piece)))
        piece_entry[ENTRY_SELECTED_AT] |= entry[ENTRY_SELECTED_AT] & SELECTED
        parent_entry[ENTRY_SELECTED_AT] &= ~SELECTED
        parent = bytearray(records[a.record].raw)
        struct.pack_into("<I", parent, HEADER + REGION_FRAMES_AT, frames)
        struct.pack_into("<I", parent, len(parent) - SPLIT_LINK_FROM_END, NO_LINK)
        new = bytearray(_record_with_name(with_owner(records[a.record].raw, piece), f"{a.stem}.{name_numbers(records)[slot] + 1}"))
        struct.pack_into("<I", new, HEADER + REGION_OFFSET_AT, a.offset + frames)
        struct.pack_into("<I", new, HEADER + REGION_FRAMES_AT, a.frames - frames)
        end, uuid = len(new) - REGION_UUID_FROM_END, fresh_uuid()
        new[end:end + 16] = uuid
        struct.pack_into("<Q", new, HEADER + REGION_TIME_AT, _uuid_time(uuid))
        struct.pack_into("<I", new, len(new) - SPLIT_LINK_FROM_END, 1)
        out[a.record] = bytes(parent)
        seqs = sequences(records)
        taken = free_table_slot(records[index_table(records)].raw[HEADER:], seqs)
        for i, r_ in enumerate(records):
            if r_.tag == GNOS_TAG:
                g = register_slot(r_.raw[HEADER:], slot=taken, blank=True)
                if has_run(g, SPLIT_KIND):
                    g = register_after_run(g, kind=SPLIT_KIND, entry_id=slot)
                out[i] = rec(GNOS_TAG, r_.raw, g)
            elif r_.tag == FILE_TAG and slot_of(r_.raw) == slot:
                f = bytearray(r_.raw)
                at = HEADER + magic_at(r_.raw[HEADER:]) + REGION_COUNT_AT
                struct.pack_into("<I", f, at, piece + 1)
                out[i] = bytes(f)
        last = max(i for i, r_ in enumerate(records) if r_.tag == REGION_TAG and region_key(r_.raw)[0] == slot)
        parent_blocks = _anchors_after(payload, loc, frames, spt)
        piece_blocks = _anchors_after(payload, loc, a.frames - frames, spt, shift=frames)
        out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, a.at, bytes(parent_entry),
                                                               bytes(piece_entry) + (piece_blocks or b""), blocks=parent_blocks))
        out.insert(last + 1, bytes(new))
        return _finish(data, out, validate)
    m = loc.midi
    seqs = sequences(records)
    t = triple_by_slot(seqs, m.slot)
    have = region_length(records[t.start].raw)
    if not 0 < delta < have:
        raise ValueError(f"the cut at tick {tick} is not inside the region")
    if t.marker is None:
        raise ValueError("the region's sequence has no marker record to clone")
    slot, seq_id = free_table_slot(records[index_table(records)].raw[HEADER:], seqs), free_seq_id(seqs)
    qesm = bytearray(with_slot(_with_start(_with_length(records[t.start].raw, have - delta), tick), slot))
    struct.pack_into("<I", qesm, HEADER + QESM_ID_AT, seq_id)
    qesm = _with_offset(bytes(qesm), sequence_offset(records[t.start].raw) + delta)
    piece_qsve = with_slot(with_owner(records[t.end].raw, seq_id), slot)
    out[t.start] = _with_length(records[t.start].raw, delta)
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, m.at, entry, _piece_entry(entry, tick, slot=slot)))
    for i, r_ in enumerate(records):
        if r_.tag == GNOS_TAG:
            out[i] = rec(GNOS_TAG, r_.raw, register_slot(r_.raw[HEADER:], slot=slot))
    out[t.end + 1:t.end + 1] = [qesm, with_slot(records[t.marker].raw, slot), piece_qsve]
    return _finish(data, out, validate)


def set_loop(data: bytes, number: int, on: bool, *, spt: float | None = None, track_count: int | None = None) -> bytes:
    loc = located(data, number, track_count)
    _require_sole(loc, "looping")
    records = project_records(data)
    song, payload = _container(records, track_count)
    out = [r.raw for r in records]
    if loc.audio:
        length = round(loc.audio.frames / spt * AUDIO_LOOP_SCALE) if on and spt is not None else None
        if on and length is None:
            raise ValueError("an audio region's loop length needs the project's sample rate")
    else:
        t = triple_by_slot(sequences(records), loc.midi.slot)
        length = region_length(records[t.start].raw)
        out[t.start] = _with_loop(records[t.start].raw, on)
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.region.at, _flagged(_entry(payload, loc), loop=on, loop_length=length)))
    return _finish(data, out)


def set_mute(data: bytes, number: int, on: bool, track_count: int | None = None) -> bytes:
    loc = located(data, number, track_count)
    records = project_records(data)
    song, payload = _container(records, track_count)
    out = [r.raw for r in records]
    if loc.audio:
        body = bytearray(records[loc.audio.record].raw)
        at = HEADER + REGION_MUTE_AT
        body[at] = (body[at] & ~REGION_MUTE_BIT) | (REGION_MUTE_BIT if on else 0)
        out[loc.audio.record] = bytes(body)
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.region.at, _flagged(_entry(payload, loc), mute=on)))
    return _finish(data, out)


def rename_region(data: bytes, number: int, name: str, track_count: int | None = None, validate: bool = True) -> bytes:
    loc = located(data, number, track_count)
    _require_sole(loc, "renaming")
    records = project_records(data)
    out = [r.raw for r in records]
    if loc.audio:
        out[loc.audio.record] = _record_with_name(records[loc.audio.record].raw, name)
    else:
        t = triple_by_slot(sequences(records), loc.midi.slot)
        out[t.start] = _with_name(records[t.start].raw, name)
    return _finish(data, out, validate)


def set_fade(data: bytes, number: int, fade: Fade, track_count: int | None = None, validate: bool = True) -> bytes:
    loc = located(data, number, track_count)
    if loc.audio is None:
        raise ValueError(f"region {number} is a MIDI region; fades are an audio region's")
    records = project_records(data)
    song, payload = _container(records, track_count)
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.audio.at, with_fade(_entry(payload, loc), fade)))
    return _finish(data, out, validate)
