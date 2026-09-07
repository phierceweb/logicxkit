"""`Input N` channels past a session's count. Written from the audio-channel insert Logic
made (`channel_alloc`) and the input records every project carries; six made on a 20-input
song came back from Logic's re-save byte for byte, routing and all (2026-09-06).

Each new mono input goes right after the last one as a copy of it with its own UUID, every
later channel owner and bound object moves up one, and the count record gains one input.
Send words stay: their base is the device input count the project was made with
(`sends.device_inputs`), which Logic keeps as it was.
"""

from __future__ import annotations

from .binding import bound_channels, channels
from .channel_alloc import (
    COUNT_INPUT_AT,
    bump_channel_count,
    is_channel_count,
    is_channel_record,
    mixer_record,
    new_input_channel,
)
from .environment import object_id_of, shifted_object
from .insert import project_records, reassemble
from .recbuild import with_owner

MAX_INPUTS = 64


def mono_inputs(data: bytes) -> list[tuple[int, int]]:
    """``(number, owner)`` of every mono `Input N`, in number order."""
    return sorted((int(c.label[6:]), o) for o, c in channels(data).items()
                  if c.label.startswith("Input ") and "-" not in c.label)


def ensure_inputs(data: bytes, wanted: int) -> bytes:
    """The session with mono inputs up to `Input wanted`."""
    if not 1 <= wanted <= MAX_INPUTS:
        raise ValueError(f"Input {wanted} is outside 1-{MAX_INPUTS}")
    while True:
        have = mono_inputs(data)
        if not have:
            raise ValueError("the session has no Input channels to copy")
        if have[-1][0] >= wanted:
            return data
        data = _add_input(data, have[-1][0] + 1, have[-1][1])


def _add_input(data: bytes, number: int, last_owner: int) -> bytes:
    records = project_records(data)
    owner = last_owner + 1
    new = new_input_channel(mixer_record(records, last_owner), number=number, owner=owner)
    owners_of = bound_channels(data)
    last_idx = max(i for i, r in enumerate(records) if is_channel_record(r) and r.owner == last_owner)
    out = []
    for i, r in enumerate(records):
        raw = r.raw
        if is_channel_record(r) and r.owner >= owner:
            raw = with_owner(raw, r.owner + 1)
        if is_channel_count(r):
            raw = bump_channel_count(raw, class_at=COUNT_INPUT_AT)
        else:
            oid = object_id_of(r)
            if oid is not None and owners_of.get(oid, -1) >= owner:
                raw = shifted_object(raw, channel=True, stamp=False)
        out.append(raw)
        if i == last_idx:
            out.append(new)
    return reassemble(data, out)

