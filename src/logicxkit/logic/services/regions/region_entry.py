"""The byte edits the region operations compose: a song-container entry re-placed in tick
order, its flags and loop length, a sequence's start, length, loop bit and offset, its events
shifted, an audio record renamed, the guards an edit needs (one region alone, not flexed), and
the finish that reassembles and validates."""

from __future__ import annotations

import struct

from .audio_regions import ENTRY_PIECE_AT, REGION_NAME_AT, REGION_TAG
from ..song.events import BAR_ONE, LINE, events
from .flexmarkers import END, ENTRY_FLAGS_AT as FLEX_FLAGS_AT, FLEX_BIT, FRACTION_AT, SOURCE_AT, START, TARGET_AT, block_fields, marker_block, ticks_of
from ..stream.stream import HEADER, reassemble
from ..midi.midi import (
    ENTRY_FLAGS_AT, ENTRY_LOOP_LENGTH_AT, ENTRY_MUTE_AT, ENTRY_SLOT_AT, ENTRY_TICK_AT, LOOP_BIT, MUTE_BIT, NO_LOOP,
    SEQ_OFFSET_AFTER_NAME, SEQ_OFFSET_FLAG, SEQ_OFFSET_FLAG_AFTER_NAME,
)
from ..midi.midi_write import LENGTH_AFTER_NAME, entry_tick, name_end
from ..stream.recbuild import rec
from .region_locate import Located
from .regions import ENTRY, TAIL, entry_blocks, song_container
from ..arrange.tracklist import arrange_run
from ..stream.validate import require_valid

START_AFTER_NAME, LOOP_AFTER_NAME = 224, 76
EDITED_BIT, SELECTED_AT = 0x01, 15
FADES_AT = 72


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


def _rewrite(payload: bytes, at: int, entry: bytes, extra: bytes | None = None, blocks: bytes | None = None) -> bytes:
    """The chunk at ``at`` with ``entry`` as its entry — in place, or back in tick order when its
    tick changed — and its marker blocks kept, or ``blocks`` instead; ``extra`` a second entry
    (with its own blocks appended) placed in tick order too."""
    chunks, tail = _chunks(payload)
    k = next(i for i in range(len(chunks)) if _offset(chunks, i) == at)
    chunk = entry + (chunks[k][ENTRY:] if blocks is None else blocks)
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


def _finish(data: bytes, out: list[bytes], validate: bool = True) -> bytes:
    """The records reassembled; validated unless a batch of edits validates once at its end."""
    result = reassemble(data, out)
    if validate:
        require_valid(result)
    return result


def _entry(payload: bytes, loc: Located) -> bytes:
    return payload[loc.region.at:loc.region.at + ENTRY]


def _require_sole(loc: Located, what: str) -> None:
    """A MIDI region's length, name, start field and loop live in the sequence its aliases share."""
    if loc.aliases > 1:
        raise ValueError(f"region {loc.number} {loc.region.name!r} is one of {loc.aliases} regions playing one sequence; "
                         f"{what} it would change them all")


def identity_anchors(frames: int, spt: float) -> tuple[bytes, bytes]:
    """The two marker blocks a region carries on a flexed track with nothing moved: source 0 to
    target 0, its last frame to its length in ticks with the fraction — the form every drum region
    of a live set bounced in place carried (2026-10-25)."""
    ticks, fraction = ticks_of(frames, spt)
    return marker_block(0, 0, START), marker_block(frames, ticks, END, fraction)


CARRIED_KINDS = (0, 6)                 # blocks past the anchors that are the file's markers, not quantize hits


def _carried(payload: bytes, loc: Located, spt: float | None) -> list[bytes] | None:
    """The region's marker blocks past its two identity anchors, when the list is cuttable — the
    identity anchors of its length first, then only the file's own markers (`CARRIED_KINDS`),
    which a region carries relative to its start: one file's regions at an offset carry its
    markers at source minus that offset (the owner's saves, 2026-10-25) — else None."""
    if spt is None or loc.audio is None:
        return None
    at, frames = loc.region.at, loc.audio.frames
    count = dict(entry_blocks(payload)).get(at, 0)
    if count < 2:
        return None
    blocks = [payload[at + ENTRY * k:at + ENTRY * (k + 1)] for k in range(1, count + 1)]
    first, second = block_fields(blocks[0]), block_fields(blocks[1])
    # (source, kind, target, fraction); Logic's fraction differs from ours in the last places, so a tick's tolerance
    if first != (0, START, 0, 0) or second[:2] != (frames, END) or abs(second[2] - frames / spt) > 1:
        return None
    if any(block_fields(b)[1] not in CARRIED_KINDS for b in blocks[2:]):
        return None
    return blocks[2:]


def _anchored(payload: bytes, loc: Located, spt: float | None) -> bool:
    return _carried(payload, loc, spt) is not None


def _shifted_block(block: bytes, shift: int, spt: float) -> bytes:
    """``block`` as a piece ``shift`` frames further into the file carries it."""
    b = bytearray(block)
    source = block_fields(block)[0] - shift
    ticks, fraction = ticks_of(source, spt) if source >= 0 else (-ticks_of(-source, spt)[0], 0)
    struct.pack_into("<i", b, SOURCE_AT, source)
    struct.pack_into("<i", b, TARGET_AT, ticks)
    struct.pack_into("<H", b, FRACTION_AT, fraction)
    return bytes(b)


def _anchors_after(payload: bytes, loc: Located, frames: int, spt: float | None, shift: int = 0) -> bytes | None:
    """The blocks a cut leaves a piece lasting ``frames`` whose first frame moved ``shift`` frames
    into the file: fresh identity anchors, then the file's markers shifted; none when the region
    carried no blocks."""
    carried = _carried(payload, loc, spt)
    if carried is None:
        return None
    return b"".join(identity_anchors(frames, spt)) + b"".join(_shifted_block(b, shift, spt) for b in carried)


def _require_unflexed(payload: bytes, loc: Located, what: str, spt: float | None = None) -> None:
    """A quantized region's marker blocks are placed from its start; how a trim or a split
    re-places them is unmeasured. A region carrying only the two identity anchors is cut and
    re-anchored."""
    blocks = dict(entry_blocks(payload)).get(loc.region.at, 0)
    if _anchored(payload, loc, spt):
        return
    if blocks or payload[loc.region.at + FLEX_FLAGS_AT] & FLEX_BIT:
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



def _piece_entry(entry: bytes, tick: int, *, piece: int | None = None, slot: int | None = None) -> bytes:
    e = bytearray(_flagged(entry, tick=tick, loop=False))
    e[ENTRY_FLAGS_AT] &= ~EDITED_BIT
    e[SELECTED_AT] = 0
    e[FADES_AT:FADES_AT + 8] = bytes(8)
    if piece is not None:
        struct.pack_into("<H", e, ENTRY_PIECE_AT, piece)
    if slot is not None:
        struct.pack_into("<I", e, ENTRY_SLOT_AT, slot)
    return bytes(e)

