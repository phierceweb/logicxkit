"""The mixer's channel records (`OCuA`): which record is the channel proper, its width byte and
the slot base every channel carries, and the count record (`nCuA`) beside them."""

from __future__ import annotations

import struct

from .slot_width import MONO, STEREO
from .stream import HEADER, NO_KEY, ProjRecord, project_records

# raw tag bytes; note Logic stores them reversed from how they read (OCuA displays as "AuCO")
CHANNEL_TAG = b"OCuA"

CHANNEL_FMT_AT = 123    # the channel's own width: OCuA payload +123, a literal channel count
CHANNEL_BASE_AT = 28          # every channel record's own copy of the project's slot base
MIXER_MIN = 200                     # a channel record proper is longer than its stubs and 14-byte shells


def is_mixer_record(record: ProjRecord) -> bool:
    """The channel record proper, not a slot or a stub."""
    return record.tag == CHANNEL_TAG and record.key == NO_KEY and len(record.raw) - HEADER > MIXER_MIN


def channel_formats(data: bytes) -> dict[int, int]:
    """owner -> 1 (mono) or 2 (stereo), from each channel's own record."""
    out: dict[int, int] = {}
    best: dict[int, int] = {}
    for record in project_records(data):
        if record.tag != CHANNEL_TAG or record.key != NO_KEY:
            continue
        payload = record.raw[HEADER:]
        if len(payload) > CHANNEL_FMT_AT and len(payload) > best.get(record.owner, -1):
            best[record.owner] = len(payload)
            out[record.owner] = payload[CHANNEL_FMT_AT]
    return {o: f for o, f in out.items() if f in (MONO, STEREO)}


COUNT_TAG = b"nCuA"
COUNT_TOTAL_AT = 26
COUNT_HEAD = 132


DEVICE_INPUTS_AT = 36


def is_channel_count(record: ProjRecord) -> bool:
    """The count record proper: its length is the head plus one word per counted channel."""
    p = record.raw[HEADER:]
    if record.tag != COUNT_TAG or len(p) < COUNT_HEAD:
        return False
    total = struct.unpack_from("<H", p, COUNT_TOTAL_AT)[0]
    return total > 0 and len(p) == COUNT_HEAD + 4 * total


def device_inputs(data: bytes) -> int | None:
    """The input count the project was created with, from the channel-count record — what
    the send and routing words count over, even after `Input` records are added (Logic's
    re-save of a 20-input song given 26 records kept the base at 20, 2026-09-06)."""
    for r in project_records(data):
        if is_channel_count(r):
            n = struct.unpack_from("<H", r.raw, HEADER + DEVICE_INPUTS_AT)[0]
            return n or None
    return None
