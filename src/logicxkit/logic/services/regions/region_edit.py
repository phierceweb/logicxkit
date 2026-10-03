"""Edits of a region's placement — move, trim, split, loop, mute, rename, fades — over its
song-container entry (`regions.py`), its record (`audio_regions.py`) or its sequence
(`midi.py`), as Logic's own edits of one blank-born project wrote them (2026-09-15, the
`regions-a*` goldens). A region is named by its number in the `regions` listing (`listed`).

Audio lengths are frames; ticks convert through samples per tick at one tempo. A split keeps the
parent's record slot: the piece gets a record with the next piece number in its header owner,
its time at its UUID's, and an entry with that number at `+40`, named `<parent>.<piece>` as
Logic names one; the file record's region count goes up by one (Logic loads that many), and the
registry gains a blank pair for the next free sequence slot (Logic's split consumes one) and a
blank kind-0x1e pair keyed by the parent's slot, as Logic's own did; a MIDI
split gives the piece its own sequence triple on the next free slot holding the parent's events
unchanged, playing from the cut through the sequence offset past the `qeSM` name. Loop-on writes the
entry's loop length: a MIDI region's length in ticks, an audio region's length in ticks times
1000 (one measurement).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .audio_regions import (
    AUDIO_ENTRY, ENTRY_PIECE_AT, FILE_TAG, REGION_COUNT_AT, REGION_FRAMES_AT, REGION_MUTE_AT, REGION_MUTE_BIT, REGION_NAME_AT,
    REGION_OFFSET_AT, REGION_TAG, AudioRegion, magic_at, read_audio_regions, region_key,
)
from .audio_write import REGION_TIME_AT, REGION_UUID_FROM_END, _uuid_time
from ..song.events import BAR_ONE, LINE, events
from .fades import Fade, with_fade
from .flexmarkers import FLEX_BIT, samples_per_tick
from ..stream.stream import HEADER, project_records, reassemble
from ..midi.midi import (
    ENTRY_FLAGS_AT, ENTRY_LOOP_LENGTH_AT, ENTRY_MUTE_AT, ENTRY_SLOT_AT, ENTRY_TICK_AT, LOOP_BIT, MIDI_ENTRY, MUTE_BIT, NO_LOOP,
    SEQ_OFFSET_AFTER_NAME, SEQ_OFFSET_FLAG, SEQ_OFFSET_FLAG_AFTER_NAME, MidiRegion, read_midi, sequence_offset,
)
from ..midi.midi_write import LENGTH_AFTER_NAME, _with_name, entry_tick, name_end, region_length
from ..stream.recbuild import fresh_uuid, rec, slot_of, with_owner, with_slot
from .regions import ENTRY, TAIL, entry_blocks, song_container
from ..stream.registry import GNOS_TAG, register_after_run, register_slot
from ..stream.sequence import QESM_ID_AT, free_seq_id, free_table_slot, index_table, sequences, triple_by_slot
from ..song.tempo import project_tempo, read_tempo_events
from ..arrange.tracklist import arrange_run
from ..stream.validate import require_valid

START_AFTER_NAME, LOOP_AFTER_NAME = 224, 76
EDITED_BIT, SELECTED_AT = 0x01, 15
FADES_AT = 72
AUDIO_LOOP_SCALE = 1000
SPLIT_PARENT_AT, SPLIT_PIECE_AT, NO_LINK = 208, 210, 0xFFFFFFFF     # region record words Logic's split sets
SPLIT_KIND = 0x1E                                                    # registry pair keyed by the parent's slot


@dataclass(frozen=True)
class Located:
    number: int
    kind: str                  # "midi" or "audio"
    midi: MidiRegion | None = None
    audio: AudioRegion | None = None
    alias: int = 0             # a MIDI region's place among the entries playing its sequence
    aliases: int = 1           # how many entries play it

    @property
    def region(self):
        return self.midi if self.kind == "midi" else self.audio

    @property
    def key(self) -> tuple[int, int, int]:
        """The entry's `integrity_regions.RegionKey`."""
        return (self.region.object_id, self.region.start, AUDIO_ENTRY if self.kind == "audio" else MIDI_ENTRY)

    @property
    def ident(self) -> tuple:
        """What stays the same across edits: an audio record's (slot, piece); a MIDI sequence's slot
        and the region's place among the entries playing it (aliases), in container order."""
        return ("audio", self.audio.record_key) if self.audio else ("midi", self.midi.slot, self.alias)


def listed(data: bytes, track_count: int | None = None) -> list[Located]:
    """Every region in the `regions` listing's order: by row, start, audio before MIDI."""
    midi = read_midi(data, track_count)
    by_slot: dict[int, list[int]] = {}
    for r in sorted(midi, key=lambda r: r.at):
        by_slot.setdefault(r.slot, []).append(r.at)
    rows = [(r.row, r.start, "audio", i, r) for i, r in enumerate(read_audio_regions(data, track_count))]
    rows += [(r.row, r.start, "midi", i, r) for i, r in enumerate(midi)]
    rows.sort(key=lambda x: x[:4])
    return [Located(n, kind, r if kind == "midi" else None, r if kind == "audio" else None,
                    by_slot[r.slot].index(r.at) if kind == "midi" else 0, len(by_slot[r.slot]) if kind == "midi" else 1)
            for n, (_row, _start, kind, _i, r) in enumerate(rows, 1)]


def located(data: bytes, number: int, track_count: int | None = None) -> Located:
    regions = listed(data, track_count)
    if not 1 <= number <= len(regions):
        raise ValueError(f"region {number}: the listing has {len(regions)} region(s)")
    return regions[number - 1]


def renumbered(data: bytes, ident: tuple, track_count: int | None = None) -> int:
    """The listing number region ``ident`` (`Located.ident`) has now, after earlier edits."""
    for loc in listed(data, track_count):
        if loc.ident == ident:
            return loc.number
    raise ValueError(f"the region {ident} is no longer in the listing")


def samples_per_tick_of(data: bytes, rate: int) -> float:
    """Frames per tick at the song's one tempo; a song whose tempo changes is refused."""
    bpms = {round(e.bpm, 4) for e in read_tempo_events(data)} | {round(project_tempo(data)[1], 4)}
    if len(bpms) > 1:
        raise ValueError("the tempo changes; an audio region's length in ticks needs one tempo")
    return samples_per_tick(rate * 60 / bpms.pop())


def _container(records, track_count):
    song = song_container(records, arrange_run(records, track_count))
    if song is None:
        raise ValueError("no song container")
    return song, records[song.end].raw[HEADER:]


def _chunks(payload: bytes) -> tuple[list[bytes], bytes]:
    """Each entry with its flex marker blocks, and the tail."""
    body = payload[:len(payload) - TAIL]
    offs = [off for off, _b in entry_blocks(payload)]
    return [body[off:(offs[k + 1] if k + 1 < len(offs) else len(body))] for k, off in enumerate(offs)], payload[len(payload) - TAIL:]


def _placed(chunks: list[bytes], chunk: bytes) -> list[bytes]:
    tick = struct.unpack_from("<I", chunk, ENTRY_TICK_AT)[0]
    at = next((k for k, c in enumerate(chunks) if struct.unpack_from("<I", c, ENTRY_TICK_AT)[0] > tick), len(chunks))
    return chunks[:at] + [chunk] + chunks[at:]


def _rewrite(payload: bytes, at: int, entry: bytes, extra: bytes | None = None) -> bytes:
    """The chunk at ``at`` with ``entry`` as its entry — in place, or back in tick order when its
    tick changed; ``extra`` a second entry placed in tick order too."""
    chunks, tail = _chunks(payload)
    k = next(i for i in range(len(chunks)) if _offset(chunks, i) == at)
    chunk = entry + chunks[k][ENTRY:]
    if entry[ENTRY_TICK_AT:ENTRY_TICK_AT + 4] == chunks[k][ENTRY_TICK_AT:ENTRY_TICK_AT + 4]:
        rest = chunks[:k] + [chunk] + chunks[k + 1:]
    else:
        rest = _placed(chunks[:k] + chunks[k + 1:], chunk)
    if extra is not None:
        rest = _placed(rest, extra)
    return b"".join(rest) + tail


def _offset(chunks: list[bytes], k: int) -> int:
    return sum(len(c) for c in chunks[:k])


def _flagged(entry: bytes, *, tick: int | None = None, mute: bool | None = None, loop: bool | None = None,
             loop_length: int | None = None) -> bytes:
    e = bytearray(entry)
    if tick is not None:
        struct.pack_into("<I", e, ENTRY_TICK_AT, entry_tick(tick))
    if mute is not None:
        e[ENTRY_MUTE_AT] = (e[ENTRY_MUTE_AT] & ~MUTE_BIT) | (MUTE_BIT if mute else 0)
    if loop is not None:
        e[ENTRY_FLAGS_AT] = (e[ENTRY_FLAGS_AT] & ~LOOP_BIT) | (LOOP_BIT if loop else 0)
        struct.pack_into("<I", e, ENTRY_LOOP_LENGTH_AT, loop_length if loop else NO_LOOP)
    return bytes(e)


def _with_start(qesm: bytes, tick: int) -> bytes:
    q = bytearray(qesm)
    struct.pack_into("<I", q, HEADER + name_end(q[HEADER:]) + START_AFTER_NAME, tick - BAR_ONE)
    return bytes(q)


def _with_length(qesm: bytes, length: int) -> bytes:
    q = bytearray(qesm)
    struct.pack_into("<I", q, HEADER + name_end(q[HEADER:]) + LENGTH_AFTER_NAME, length)
    return bytes(q)


def _with_loop(qesm: bytes, on: bool) -> bytes:
    q = bytearray(qesm)
    at = HEADER + name_end(q[HEADER:]) + LOOP_AFTER_NAME
    q[at] = (q[at] & ~LOOP_BIT) | (LOOP_BIT if on else 0)
    return bytes(q)


def _shifted(qsve: bytes, delta: int) -> bytes:
    """The sequence's events ``delta`` ticks earlier, the tail as it was."""
    payload = qsve[HEADER:]
    evs = events(payload)
    body = sum(LINE + LINE * len(e.lines) for e in evs)
    lines = []
    for e in evs:
        if e.tick - delta < 0:
            raise ValueError(f"an event at tick {e.tick - BAR_ONE} of the region would land before the sequence's start "
                             f"(a trim of {delta} ticks); trim less, or delete the event first")
        head = bytearray(e.head)
        struct.pack_into("<I", head, 4, e.tick - delta)
        lines.append(bytes(head) + b"".join(e.lines))
    return rec(b"qSvE", qsve, b"".join(lines) + payload[body:])


def _with_offset(qesm: bytes, offset: int) -> bytes:
    q = bytearray(qesm)
    end = HEADER + name_end(q[HEADER:])
    struct.pack_into("<I", q, end + SEQ_OFFSET_AFTER_NAME, offset)
    q[end + SEQ_OFFSET_FLAG_AFTER_NAME] |= SEQ_OFFSET_FLAG
    return bytes(q)


def _finish(data: bytes, out: list[bytes]) -> bytes:
    result = reassemble(data, out)
    require_valid(result)
    return result


def _entry(payload: bytes, loc: Located) -> bytes:
    return payload[loc.region.at:loc.region.at + ENTRY]


def _require_sole(loc: Located, what: str) -> None:
    """A MIDI region's length, name, start field and loop live in the sequence its aliases share."""
    if loc.aliases > 1:
        raise ValueError(f"region {loc.number} {loc.region.name!r} is one of {loc.aliases} regions playing one sequence; "
                         f"{what} it would change them all")


def _require_unflexed(payload: bytes, loc: Located, what: str) -> None:
    """A flexed (quantized) region's marker blocks are placed from its start; how a trim or a
    split re-places them is unmeasured."""
    blocks = dict(entry_blocks(payload)).get(loc.region.at, 0)
    if blocks or payload[loc.region.at + SELECTED_AT] & FLEX_BIT:
        raise ValueError(f"region {loc.number} {loc.region.name!r} is flexed; {what} a flexed region is not supported — "
                         "quantize after the edit instead")


def _record_with_name(raw: bytes, name: str) -> bytes:
    p = raw[HEADER:]
    old_n = struct.unpack_from("<H", p, REGION_NAME_AT)[0]
    text = name.encode("utf-8")
    if len(text) > 0xFFFF:
        raise ValueError("a region's name is at most 65535 bytes of UTF-8")
    body = p[:REGION_NAME_AT] + struct.pack("<H", len(text)) + text + bytes(len(text) % 2) + p[REGION_NAME_AT + 2 + old_n + old_n % 2:]
    return rec(REGION_TAG, raw, body)


def _frames(ticks: float, spt: float | None) -> int:
    if spt is None:
        raise ValueError("an audio region's length in ticks needs the project's sample rate")
    return round(ticks * spt)


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


def trim_region(data: bytes, number: int, *, start: int | None = None, length: int | None = None,
                spt: float | None = None, track_count: int | None = None) -> bytes:
    """Region ``number`` starting at tick ``start`` (its content kept in place) and lasting
    ``length`` ticks."""
    loc = located(data, number, track_count)
    r = loc.region
    if start is not None and start < BAR_ONE:
        raise ValueError("a region starts at or after bar 1")
    _require_sole(loc, "trimming")
    records = project_records(data)
    song, payload = _container(records, track_count)
    _require_unflexed(payload, loc, "trimming")
    out = [r_.raw for r_ in records]
    entry = _entry(payload, loc)
    delta = 0 if start is None else start - r.start
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
    if delta or r.loop:
        entry = _flagged(entry, tick=start if delta else None, loop=True if r.loop else None, loop_length=loop_length)
        out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, r.at, entry))
    return _finish(data, out)


def _piece_entry(entry: bytes, tick: int, *, piece: int | None = None, slot: int | None = None) -> bytes:
    e = bytearray(_flagged(entry, tick=tick, loop=False))
    e[ENTRY_FLAGS_AT] &= ~EDITED_BIT
    e[SELECTED_AT] = 0
    e[FADES_AT:FADES_AT + 8] = bytes(8)
    if piece is not None:
        e[ENTRY_PIECE_AT] = piece
    if slot is not None:
        struct.pack_into("<I", e, ENTRY_SLOT_AT, slot)
    return bytes(e)


def split_region(data: bytes, number: int, tick: int, *, spt: float | None = None,
                 track_count: int | None = None) -> bytes:
    """Region ``number`` cut at absolute ``tick``; the part from the cut becomes a new region."""
    loc = located(data, number, track_count)
    r = loc.region
    if r.loop:
        raise ValueError("a looping region is not split; switch its loop off first")
    _require_sole(loc, "splitting")
    records = project_records(data)
    song, payload = _container(records, track_count)
    _require_unflexed(payload, loc, "splitting")
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
        parent = bytearray(records[a.record].raw)
        struct.pack_into("<I", parent, HEADER + REGION_FRAMES_AT, frames)
        struct.pack_into("<I", parent, HEADER + SPLIT_PARENT_AT, NO_LINK)
        new = bytearray(_record_with_name(with_owner(records[a.record].raw, piece), f"{a.name}.{piece}"))
        struct.pack_into("<I", new, HEADER + REGION_OFFSET_AT, a.offset + frames)
        struct.pack_into("<I", new, HEADER + REGION_FRAMES_AT, a.frames - frames)
        end, uuid = len(new) - REGION_UUID_FROM_END, fresh_uuid()
        new[end:end + 16] = uuid
        struct.pack_into("<Q", new, HEADER + REGION_TIME_AT, _uuid_time(uuid))
        new[HEADER + SPLIT_PIECE_AT] = 1
        out[a.record] = bytes(parent)
        seqs = sequences(records)
        taken = free_table_slot(records[index_table(records)].raw[HEADER:], seqs)
        for i, r_ in enumerate(records):
            if r_.tag == GNOS_TAG:
                g = register_slot(r_.raw[HEADER:], slot=taken, blank=True)
                out[i] = rec(GNOS_TAG, r_.raw, register_after_run(g, kind=SPLIT_KIND, entry_id=slot))
            elif r_.tag == FILE_TAG and slot_of(r_.raw) == slot:
                f = bytearray(r_.raw)
                at = HEADER + magic_at(r_.raw[HEADER:]) + REGION_COUNT_AT
                struct.pack_into("<I", f, at, piece + 1)
                out[i] = bytes(f)
        last = max(i for i, r_ in enumerate(records) if r_.tag == REGION_TAG and region_key(r_.raw)[0] == slot)
        out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, a.at, entry, _piece_entry(entry, tick, piece=piece)))
        out.insert(last + 1, bytes(new))
        return _finish(data, out)
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
    return _finish(data, out)


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


def rename_region(data: bytes, number: int, name: str, track_count: int | None = None) -> bytes:
    loc = located(data, number, track_count)
    _require_sole(loc, "renaming")
    records = project_records(data)
    out = [r.raw for r in records]
    if loc.audio:
        out[loc.audio.record] = _record_with_name(records[loc.audio.record].raw, name)
    else:
        t = triple_by_slot(sequences(records), loc.midi.slot)
        out[t.start] = _with_name(records[t.start].raw, name)
    return _finish(data, out)


def set_fade(data: bytes, number: int, fade: Fade, track_count: int | None = None) -> bytes:
    loc = located(data, number, track_count)
    if loc.audio is None:
        raise ValueError(f"region {number} is a MIDI region; fades are an audio region's")
    records = project_records(data)
    song, payload = _container(records, track_count)
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.audio.at, with_fade(_entry(payload, loc), fade)))
    return _finish(data, out)
