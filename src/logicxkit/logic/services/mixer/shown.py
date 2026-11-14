"""Channel record `+30`, the number of insert slots the mixer shows: one value on every channel
record of the project, the longest chain plus one empty slot, and its copy at `+61` of the
channel-count record (a u8 beside the slot base at `+60`: equal to the channel word on every public
Logic save, 2026-11-13). Logic recomputes both on save."""

from __future__ import annotations

import struct

from .binding import channels
from .mixer import CHANNEL_TAG, is_channel_count
from .slots import SHOWN_AT
from ..stream.stream import HEADER, project_records, reassemble

SHOWN_MIRROR_AT = 61


def shown_slots(data: bytes) -> int:
    """The highest shown-slot count any channel record carries (0 in a project without one)."""
    owners = set(channels(data))
    return max((struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in project_records(data)
                if r.tag == CHANNEL_TAG and r.owner in owners and len(r.raw) - HEADER >= SHOWN_AT + 2), default=0)


def needed_shown(data: bytes, highest_key: dict[int, int], index_base: int) -> int:
    """The shown-slot count a project needs for the chains ending at ``highest_key`` per owner: the
    longest chain plus one empty slot. An instrument channel's slot 1 is its instrument and does not
    count: Logic kept 2 with one audio effect after it and wrote 3 with two
    (`instrument-fx-two-midi-one-audio-logic`, `instrument-fx-two-midi-two-audio-resave-logic`).
    An instrument channel is one labelled `Inst N`, the mixer's own label."""
    labels = {o: c.label for o, c in channels(data).items()}
    return max((key - index_base + (1 if labels.get(owner, "").startswith("Inst ") else 2)
                for owner, key in highest_key.items()), default=0)


def show_slots(data: bytes, shown: int) -> bytes:
    """Every channel record's `+30` raised to ``shown``, the insert slots the mixer shows —
    the longest chain plus one empty slot, one value for the project — and the channel-count
    record's `+61` set to the value the channel records then carry. A higher count is left:
    Logic recomputes it on save."""
    owners = set(channels(data))
    out = []
    for r in project_records(data):
        raw = r.raw
        if r.tag == CHANNEL_TAG and r.owner in owners and len(raw) - HEADER >= SHOWN_AT + 2 \
                and struct.unpack_from("<H", raw, HEADER + SHOWN_AT)[0] < shown:
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + SHOWN_AT, shown)
            raw = bytes(buf)
        out.append(raw)
    result = reassemble(data, out)
    project = shown_slots(result)
    if project > 0xFF:
        return result
    return reassemble(result, [_mirrored(r.raw, project) if is_channel_count(r) else r.raw for r in project_records(result)])


def _mirrored(raw: bytes, shown: int) -> bytes:
    buf = bytearray(raw)
    buf[HEADER + SHOWN_MIRROR_AT] = shown
    return bytes(buf)
