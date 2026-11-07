"""Channel record `+30`, the number of insert slots the mixer shows: one value on every channel
record of the project, the longest chain plus one empty slot. Logic recomputes it on save."""

from __future__ import annotations

import struct

from .binding import channels
from .mixer import CHANNEL_TAG
from .slots import SHOWN_AT
from ..stream.stream import HEADER, project_records, reassemble


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
    the longest chain plus one empty slot, one value for the project. A higher count is left:
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
    return reassemble(data, out)
