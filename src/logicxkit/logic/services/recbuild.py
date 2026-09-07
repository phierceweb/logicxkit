"""Record bytes — restamp a 36-byte header over a new payload, mint what Logic mints.

    +0    tag (reversed mnemonic)   +10   u16 slot: object id on `ivnE`, sequence slot on
    +4    u16 class version               the `qeSM`/`qSvE` triples
    +14   u16 owner                 +18   u16 key
    +28   u32 payload size
"""

from __future__ import annotations

import random
import struct
import uuid as _uuid

from .insert import HEADER, KEY_OFF, OWNER_OFF, SIZE_OFF

SLOT_OFF = 10


def rec(tag: bytes, template: bytes, payload: bytes, *, owner: int | None = None,
        key: int | None = None) -> bytes:
    """``template``'s header with ``tag`` and the size of ``payload``, over ``payload``."""
    head = bytearray(template[:HEADER])
    head[0:4] = tag
    struct.pack_into("<I", head, SIZE_OFF, len(payload))
    if owner is not None:
        struct.pack_into("<H", head, OWNER_OFF, owner)
    if key is not None:
        struct.pack_into("<H", head, KEY_OFF, key)
    return bytes(head) + payload


def _stamp(raw: bytes, off: int, value: int) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<H", buf, off, value)
    return bytes(buf)


def with_owner(raw: bytes, owner: int) -> bytes:
    return _stamp(raw, OWNER_OFF, owner)


def with_key(raw: bytes, key: int) -> bytes:
    return _stamp(raw, KEY_OFF, key)


def with_slot(raw: bytes, slot: int) -> bytes:
    return _stamp(raw, SLOT_OFF, slot)


def slot_of(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, SLOT_OFF)[0]


def fresh_uuid() -> bytes:
    """A real v1 UUID (time-based, like Logic's), random clock sequence and node."""
    node = random.getrandbits(48) | (1 << 40)          # multicast bit: never a real MAC
    return _uuid.uuid1(node=node, clock_seq=random.getrandbits(14)).bytes


def time_fields(uuid: bytes) -> bytes:
    """The 60-bit v1 timestamp of ``uuid`` as Logic stores it in the 16-byte `gnoS` entry."""
    low = struct.unpack_from(">I", uuid, 0)[0]
    mid = struct.unpack_from(">H", uuid, 4)[0]
    hi = struct.unpack_from(">H", uuid, 6)[0] & 0x0FFF
    return struct.pack("<IHH", low, mid, hi)
