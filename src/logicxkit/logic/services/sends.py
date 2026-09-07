"""Send records — `UCuA` keys 0-2 under a channel's owner, 76-byte payload.

    +0    u32   class word: 72 at `UCuA` v5, the only version on hand
    +4    u32   send slot: 0, 0x10000, 0x20000
    +8    u16   0 or 4 — not decoded
    +16   ..    the level, not decoded: `+17` and `+27` move together and differ per send
    +20   u16   destination: bus number + the project's device input count - 1 (32 inputs:
                46 -> Bus 15, 41 -> Bus 10; a 20-input project writes Bus 10 as 29 — Logic
                rewrote 41 to 29 on re-save, 2026-09-05, and had dropped the channel's plugin
                while the send pointed past its buses). The device count is the channel-count
                record's +36 word; adding `Input` records leaves it, and the words, alone
    +44   16    the send's own instance UUID (v1), distinct on every send
    +60   16    the destination `Bus N` channel's own UUID (`binding.py`)

The channel's own `OCuA` mirrors them: u32 flags at +132, +136, +140 read 1 when send
slot 0, 1, 2 exists (every Logic-written channel on hand, 17,430 of them).

Measured on 78 sends across three Logic 12.3.1 saves: every bus resolves to a `Bus N`
channel record whose UUID the send repeats at +60. Two Logic re-saves left every send
byte-identical, so nothing here is a per-save nonce. They sit right after the channel's
`OCuA` in key order, before the plugin slots. `sends_write.py` writes them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .binding import channels
from .insert import HEADER, ProjRecord, project_records

SEND_TAG = b"UCuA"
SEND_KEYS = range(0, 3)
CLASS_AT = 0
SLOT_AT = 4
BUS_AT = 20
BUS_OFFSET = 31                 # for a 32-input project, and for fixtures without inputs
INSTANCE_UUID_AT = 44
DEST_UUID_AT = 60
SEND_FLAG_AT = 132              # in the channel's OCuA, one u32 per send slot
_PAYLOAD = 76


@dataclass(frozen=True)
class Send:
    owner: int
    key: int
    slot: int
    bus: int
    raw: bytes


_SEND_MAX = 128                 # every send is 76 bytes (1,197 on 39 files); a project whose
                                # plugin slots start at key 2 carries kilobyte slots under those keys


def is_send(record: ProjRecord) -> bool:
    return (record.tag == SEND_TAG and record.key in SEND_KEYS
            and _PAYLOAD <= len(record.raw) - HEADER < _SEND_MAX)


DEVICE_INPUTS_AT = 36


def device_inputs(data: bytes) -> int | None:
    """The input count the project was created with, from the channel-count record — what
    the send word's base follows, even after `Input` records are added (Logic's re-save of a
    20-input song given 26 records kept the base at 20, 2026-09-06)."""
    from .channel_alloc import is_channel_count          # channel_alloc imports this module
    for r in project_records(data):
        if is_channel_count(r):
            n = struct.unpack_from("<H", r.raw, HEADER + DEVICE_INPUTS_AT)[0]
            return n or None
    return None


def send_base(data: bytes) -> int:
    """What `+20` holds for Bus 0: the project's device input count less one (a project
    without `Input` channels, a fixture, counts as the 32-input case)."""
    inputs = device_inputs(data)
    if inputs is None:
        inputs = sum(1 for c in channels(data).values() if c.label.startswith("Input ") and "-" not in c.label)
    return inputs - 1 if inputs else BUS_OFFSET


def read_sends(data: bytes) -> dict[int, list[Send]]:
    """owner -> its sends in key order."""
    base = send_base(data)
    out: dict[int, list[Send]] = {}
    for record in project_records(data):
        if not is_send(record):
            continue
        payload = record.raw[HEADER:]
        out.setdefault(record.owner, []).append(Send(
            owner=record.owner, key=record.key,
            slot=struct.unpack_from("<I", payload, SLOT_AT)[0] >> 16,
            bus=struct.unpack_from("<H", payload, BUS_AT)[0] - base,
            raw=record.raw))
    return out


def bus_owner(data: bytes, bus: int) -> int | None:
    """Owner of the ``Bus N`` channel record, or ``None`` when the project has no such bus."""
    return next((o for o, c in channels(data).items() if c.label == f"Bus {bus}"), None)
