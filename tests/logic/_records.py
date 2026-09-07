"""Synthetic ProjectData builders shared by the record-level tests.

Every byte a test reads is written here, so these prove structure, not decoding — the goldens
on the Recording template are what pin the format.
"""

import struct

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 5) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


def uuid(n: int) -> bytes:
    """A distinct 16-byte id per n; never all-zero."""
    return struct.pack("<IIII", 0x94C011EF, n, n * 7 + 1, 0xE1E1)


def env_obj(object_id: int, name: str, *, grouping: bool = False, uuid: bytes | None = None,
            parent: int = 0, ver: int = 12, group: int = 0) -> bytes:
    from logicxkit.logic.services.environment import (
        CHANNEL_OBJECT, GROUPING, KIND_AT, NAME_AT, PARENT_AT)
    encoded = name.encode()
    p = bytearray(463 + len(encoded) + len(encoded) % 2)   # names are padded to even length
    struct.pack_into("<I", p, 0, CHANNEL_OBJECT[ver])
    struct.pack_into("<I", p, 16, object_id)
    struct.pack_into("<I", p, 24, group)
    struct.pack_into("<I", p, PARENT_AT, parent)
    p[KIND_AT] = GROUPING if grouping else 128
    struct.pack_into("<H", p, NAME_AT, len(encoded))
    p[NAME_AT + 2:NAME_AT + 2 + len(encoded)] = encoded
    p[-16:] = uuid if uuid is not None else globals()["uuid"](object_id)
    return rec(b"ivnE", 0xFFFF, 0xFFFF, bytes(p), ver)


def chan(owner: int, label: str, *, uuid: bytes = b"", dest: bytes = b"", source: bytes = b"",
         stack_index: int = 0, fader: int = 90, pan: int = 64, size: int = 257,
         in_use: bool = True) -> bytes:
    p = bytearray(size)
    struct.pack_into("<H", p, 26, max(0, (size - 201) // 4))  # flag words size a v7 record
    p[24] = p[25] = 1 if in_use else 0
    p[60:60 + len(label) + 1] = b" " + label.encode()
    p[85] = p[119] = fader
    p[89] = pan
    p[110] = stack_index
    p[123] = 2
    if uuid:
        p[size - 48:size - 32] = uuid
    if dest:
        p[size - 32:size - 16] = dest
    if source:
        p[size - 16:] = source
    return rec(b"OCuA", owner, 0xFFFF, bytes(p), 7)


def track(key: int, object_id: int, *, flag: int = 1, member: bool = False) -> bytes:
    p = bytearray(58)
    struct.pack_into("<I", p, 0, flag)
    struct.pack_into("<I", p, 8, object_id)
    p[14] = 1 if member else 0
    return rec(b"karT", 0xFFFF, key, bytes(p), 6)


def marker() -> bytes:
    """A zero-size karT as Logic writes it: key 0xFFFF, +20 = 0x7FFF."""
    raw = bytearray(rec(b"karT", 0xFFFF, 0xFFFF, b"", 6))
    struct.pack_into("<H", raw, 20, 0x7FFF)
    return bytes(raw)


def send(owner: int, key: int, bus: int, *, slot: int | None = None) -> bytes:
    p = bytearray(76)
    struct.pack_into("<I", p, 0, 72)                                  # the send class word
    struct.pack_into("<I", p, 4, key * 0x10000 if slot is None else slot)
    struct.pack_into("<I", p, 20, bus + 31)
    return rec(b"UCuA", owner, key, bytes(p), 5)


def _slotted(raw: bytes, slot: int) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<H", buf, 10, slot)
    return bytes(buf)


def seq_triple(seq_id: int, *, slot: int = 0, object_id: int = 0, index: int = 0,
               big: bytes = b"", size: int = 345) -> bytes:
    """qeSM (+8 = seq_id, +234 = object_id, +242 = -index, +300 = 382) / zero-size karT /
    qSvE, all three carrying ``slot``; ``big`` makes the qSvE the index table."""
    p = bytearray(size)
    struct.pack_into("<I", p, 8, seq_id)
    struct.pack_into("<H", p, 234, object_id)
    struct.pack_into("<h", p, 242, -index)
    struct.pack_into("<I", p, 300, 382)
    return (_slotted(rec(b"qeSM", 0xFFFF, 0xFFFF, bytes(p), 5), slot)
            + _slotted(marker(), slot)
            + _slotted(rec(b"qSvE", seq_id, 0xFFFF, big or bytes(16), 5), slot))


def index_entry(object_id: int, index: int, slot: int) -> bytes:
    """One 80-byte index-table entry: object id at +16, sequence index at +20, slot at +32."""
    e = bytearray(80)
    struct.pack_into("<I", e, 16, object_id)
    e[20] = index
    struct.pack_into("<H", e, 32, slot)
    return bytes(e)


def gnos(*ids: int, slots: tuple[int, ...] = (), groups: tuple[int, ...] = ()) -> bytes:
    """The registries a gnoS carries: ``<0x14><id><uuid>`` / ``<0x14><id><8>`` per object,
    ``<0x17><slot><...>`` per index-table slot (plus the list ids 4 and 8), zero-filled, and
    ``<0x11><slot>`` per group slot directly before the object entries."""
    grp24 = b"".join(struct.pack("<II", 0x11, i) + uuid(900 + i) for i in groups)
    grp16 = b"".join(struct.pack("<II", 0x11, i) + bytes(8) for i in groups)
    run24 = b"".join(struct.pack("<II", 0x14, i) + uuid(i) for i in ids)
    run16 = b"".join(struct.pack("<II", 0x14, i) + bytes(8) for i in ids)
    slot_ids = (4, 8) + tuple(slots)
    slot24 = b"".join(struct.pack("<II", 0x17, i) + bytes(16) for i in slot_ids)
    slot16 = b"".join(struct.pack("<II", 0x17, i) + bytes(8) for i in slot_ids)
    return rec(b"gnoS", 0xFFFF, 0xFFFF,
               bytes(240) + grp24 + run24 + bytes(16) + slot24 + bytes(16) + grp16 + run16 + bytes(16)
               + slot16 + bytes(16), 5)


def count_record(total: int, classes: list[int], entries: int) -> bytes:
    """nCuA: total at +26, one u16 per channel class from +28, a 4-byte entry per channel."""
    p = bytearray(132)
    struct.pack_into("<H", p, 26, total)
    for k, n in enumerate(classes):
        struct.pack_into("<H", p, 28 + 2 * k, n)
    return rec(b"nCuA", 0xFFFF, 0xFFFF, bytes(p) + b"\x01\x00\x00\x00" * entries, 5)


def group_triple(slot: int, group_id: int, *, name: str = "", flags: int = 0x81400005,
                 events: bytes = b"") -> bytes:
    """A group's qeSM (+6 = 0x11, id at +8, name at +16, flags after it) / marker / qSvE
    (owner = the id, the events then a 16-byte tail), all carrying ``slot``."""
    encoded = name.encode()
    padded = encoded + (b"\x00" if len(encoded) % 2 else b"")
    p = bytearray(297 + len(padded))
    struct.pack_into("<I", p, 8, group_id)
    struct.pack_into("<H", p, 16, len(encoded))
    p[18:18 + len(padded)] = padded
    struct.pack_into("<I", p, 70 + len(padded), flags)
    qesm = bytearray(_slotted(rec(b"qeSM", 0xFFFF, 0xFFFF, bytes(p), 5), slot))
    qesm[6] = 0x11
    qsve = bytearray(_slotted(rec(b"qSvE", group_id, 0xFFFF, events + bytes(16), 1), slot))
    qsve[6] = 0x11
    return bytes(qesm) + _slotted(marker(), slot) + bytes(qsve)
