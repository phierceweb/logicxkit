"""Environment objects — the `ivnE` records that name tracks and stack folders.

    +0     u32   channel-object type in the low half, the build's: 1800 at class v12 from
                 Logic 12, 1760 at class v12 from Logic 11.2, 1728 at v11; mixed projects set
                 flag bits 0x4040 in the high half on some tracks
    +16    u32   object id — what a `karT` row's +8 points at
    +38    u32   parent: the object id of the stack this track was dragged into (0 = never)
    +80    u8    1 on the selected object only (`selection.py`)
    +82    u32   per-object stamp: a fresh object gets its pattern's plus the pattern's +86;
                 on a channel insert every object above the pattern's moves up by 66
    +86    u16   0x42 on a fresh object
    +154   u8    kind; 0 marks a grouping object (stack folders, Logic's Preview/Click/Master)
    +155   u8    track colour, a palette index (drums 96, guitars 81; a recolour moved 96 -> 64)
    +158   u16   name length in bytes, the UTF-8 name follows (padded to an even length)
    name end     u16 = the bound channel's owner + 1, kept live when owners shift; on a
    name end +3  stack object, its Sub number
    last 16      the object's instance UUID; a mixer channel binds to an object by carrying it

Payload length is 463 or 464 plus the name length, so a rename changes the record size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .names import readable, written
from .stream import HEADER, project_records, reassemble
from .validate import require_full_walk
from .recbuild import fresh_uuid, rec

ENV_TAG = b"ivnE"
CHANNEL_OBJECT = {11: 1728, 12: 1800}
CHANNEL_OBJECT_TYPES = {11: {1728}, 12: {1760, 1800}}
OBJECT_ID_AT = 16
PARENT_AT = 38
KIND_AT = 154
COLOUR_AT = 155
NAME_AT = 158
UUID_LEN = 16
GROUPING = 0
ICON_AT = 148
DEFAULT_ICON = 0x1223
DEFAULT_COLOUR = 16
ID_STEP = 4
SELECTED_AT = 80
STAMP_AT, STAMP_STEP_AT = 82, 86
STAMP_SHIFT, FRESH_STEP = 66, 0x42
STATE_AT = 45
NAMED_BIT = 1                     # +45 bit 0: the name is the user's; clear, the arrange shows
                                  # the channel-strip setting's name instead (every named
                                  # track on hand sets it; Logic's own fresh adds do not)
STACK_NUMBER_AFTER_NAME = 3
_NAME_MAX = 127                   # bytes; the longest written name Logic kept (`names-long-*`)


@dataclass(frozen=True)
class EnvObject:
    object_id: int
    name: str | None                  # None: the bytes are not UTF-8 text
    kind: int
    parent: int
    uuid: bytes
    size: int
    colour: int = 0
    icon: int = 0


def _constant(records) -> set[int] | None:
    version = next((r.ver for r in records if r.tag == ENV_TAG), None)
    return CHANNEL_OBJECT_TYPES.get(version)


TYPE_MASK = 0xFFFF                 # +0: the type in the low half; mixes set flags above it


def _is_channel_object(payload: bytes, constant: set[int] | None) -> bool:
    return (constant is not None and len(payload) > NAME_AT + 2 + UUID_LEN
            and struct.unpack_from("<I", payload, 0)[0] & TYPE_MASK in constant)


def _name_bytes(payload: bytes) -> bytes | None:
    """The name's bytes, or None when the length field is not one. Any length that fits the
    record is read: `_NAME_MAX` is the longest Logic was shown to keep, a limit for the writer."""
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    if not n or NAME_AT + 2 + n > len(payload):
        return None
    return payload[NAME_AT + 2:NAME_AT + 2 + n]


def channel_objects(data: bytes) -> dict[int, EnvObject]:
    """object id -> every channel-type Environment object with a name field; ``name`` is None
    where its bytes are not UTF-8 text, so binding and the write gate still see the object."""
    records = project_records(data)
    constant = _constant(records)
    out: dict[int, EnvObject] = {}
    if constant is None:
        return out
    for record in records:
        if record.tag != ENV_TAG:
            continue
        payload = record.raw[HEADER:]
        if not _is_channel_object(payload, constant):
            continue
        raw_name = _name_bytes(payload)
        if raw_name is None:
            continue
        object_id = struct.unpack_from("<I", payload, OBJECT_ID_AT)[0]
        out[object_id] = EnvObject(
            object_id=object_id, name=readable(raw_name), kind=payload[KIND_AT],
            parent=struct.unpack_from("<I", payload, PARENT_AT)[0],
            uuid=payload[-UUID_LEN:], size=len(payload), colour=payload[COLOUR_AT],
            icon=struct.unpack_from("<H", payload, ICON_AT)[0])
    return out


def set_parent(raw: bytes, parent: int) -> bytes:
    """Stamp the stack object id a track was dragged into; the record length is unchanged."""
    buf = bytearray(raw)
    struct.pack_into("<I", buf, HEADER + PARENT_AT, parent)
    return bytes(buf)


def set_icon(data: bytes, object_id: int, icon: int) -> bytes:
    """Set one track's icon — the u16 at +148 a fresh add gets `DEFAULT_ICON` in. Decoded
    from reads: the template's icons differ per track and land on the tracks cut from it."""
    if not 0 <= icon <= 0xFFFF:
        raise ValueError("an icon is a u16")
    require_full_walk(data)
    records = project_records(data)
    out, hit = [], False
    for record in records:
        raw = record.raw
        if object_id_of(record) == object_id:
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + ICON_AT, icon)
            raw = bytes(buf)
            hit = True
        out.append(raw)
    if not hit:
        raise ValueError(f"no channel object {object_id}")
    return reassemble(data, out)


def set_colour(data: bytes, object_id: int, colour: int) -> bytes:
    """Recolour one track's object; measured as the only persistent change of a recolour."""
    if not 0 <= colour <= 255:
        raise ValueError("colour is a palette index 0-255")
    require_full_walk(data)
    records = project_records(data)
    constant = _constant(records)
    out, hit = [], False
    for record in records:
        raw = record.raw
        if record.tag == ENV_TAG and constant is not None:
            payload = raw[HEADER:]
            if (_is_channel_object(payload, constant)
                    and struct.unpack_from("<I", payload, OBJECT_ID_AT)[0] == object_id):
                buf = bytearray(raw)
                buf[HEADER + COLOUR_AT] = colour
                raw = bytes(buf)
                hit = True
        out.append(raw)
    if not hit:
        raise ValueError(f"no channel object {object_id}")
    return reassemble(data, out)


def object_record(records, object_id: int) -> bytes:
    """The raw `ivnE` record carrying ``object_id``."""
    for r in records:
        if (r.tag == ENV_TAG and len(r.raw) - HEADER > NAME_AT
                and struct.unpack_from("<I", r.raw, HEADER + OBJECT_ID_AT)[0] == object_id):
            return r.raw
    raise ValueError(f"no environment object {object_id}")


def next_object_id(records) -> int:
    """The id Logic gives the next object: the next multiple of four past the highest.

    Track rows count too. Most sessions on hand have `karT` rows naming ids above
    every `ivnE`, so scanning the objects alone returns an id a row already claims and the new
    object shares it — a duplicate row in the flat mixer list.
    """
    from .tracklist import TRACK_OBJECT_AT, TRACK_TAG

    ids = [struct.unpack_from("<I", r.raw, HEADER + OBJECT_ID_AT)[0]
           for r in records if r.tag == ENV_TAG and len(r.raw) - HEADER > NAME_AT]
    ids += [struct.unpack_from("<I", r.raw, HEADER + TRACK_OBJECT_AT)[0]
            for r in records if r.tag == TRACK_TAG
            and len(r.raw) - HEADER >= TRACK_OBJECT_AT + 4]
    return (max(ids) // ID_STEP + 1) * ID_STEP


def object_id_of(record) -> int | None:
    """The object id of a channel-object `ivnE` record, else None."""
    payload = record.raw[HEADER:]
    types = CHANNEL_OBJECT_TYPES.get(record.ver)
    if record.tag != ENV_TAG or not _is_channel_object(payload, types):
        return None
    return struct.unpack_from("<I", payload, OBJECT_ID_AT)[0]


def name_end(payload: bytes) -> int:
    """Offset just past the even-padded name: the bound-channel index lives there."""
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    return NAME_AT + 2 + n + (n & 1)


def object_stamp(raw: bytes) -> int:
    return struct.unpack_from("<I", raw, HEADER + STAMP_AT)[0]


def _with_name(payload: bytes, name: str) -> bytearray:
    """The payload with the name field rewritten as Logic writes one — UTF-8, the length in
    bytes, padded to even; everything after it keeps its place."""
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    encoded = written(name, "a track name", limit=_NAME_MAX)
    old_field = n + (n % 2)
    new_field = encoded + (b"\x00" if len(encoded) % 2 else b"")
    return (bytearray(payload[:NAME_AT]) + struct.pack("<H", len(encoded)) + new_field
            + payload[NAME_AT + 2 + old_field:])


def rename_object(raw: bytes, name: str) -> bytes:
    """``raw`` renamed and marked user-named — the record changes size, nothing else moves."""
    body = _with_name(raw[HEADER:], name)
    body[STATE_AT] |= NAMED_BIT
    return rec(ENV_TAG, raw, bytes(body))


def rename_track(data: bytes, object_id: int, name: str) -> bytes:
    """Rename one track's object: the name field and the user-named bit, which is all Logic's
    own rename changed in the object (`names-non-ascii-logic`)."""
    require_full_walk(data)
    records = project_records(data)
    out, hit = [], False
    for record in records:
        raw = record.raw
        if object_id_of(record) == object_id:
            raw = rename_object(raw, name)
            hit = True
        out.append(raw)
    if not hit:
        raise ValueError(f"no channel object {object_id}")
    return reassemble(data, out)


def clone_object(raw: bytes, *, object_id: int, name: str, owner: int, colour: int | None,
                 icon: int | None = DEFAULT_ICON, stack_number: int | None = None,
                 fresh_step: int | None = FRESH_STEP, named: bool = True) -> bytes:
    """``raw`` as a fresh top-level object bound to channel ``owner``: new id (the header
    +10 repeats it), name (user-given unless ``named`` is off), colour and icon (None keeps
    the pattern's), a fresh UUID, the stamp minted from the pattern's, the parent cleared,
    selected."""
    p = raw[HEADER:]
    body = _with_name(p, name)
    struct.pack_into("<I", body, OBJECT_ID_AT, object_id)
    struct.pack_into("<I", body, PARENT_AT, 0)
    body[STATE_AT] = NAMED_BIT if named else 0
    body[SELECTED_AT] = 1
    struct.pack_into("<I", body, STAMP_AT,
                     object_stamp(raw) + struct.unpack_from("<H", p, STAMP_STEP_AT)[0])
    if fresh_step is not None:
        struct.pack_into("<H", body, STAMP_STEP_AT, fresh_step)
    if colour is not None:
        body[COLOUR_AT] = colour
    if icon is not None:
        struct.pack_into("<H", body, ICON_AT, icon)
    end = name_end(body)
    struct.pack_into("<H", body, end, owner + 1)
    if stack_number is not None:
        body[end + STACK_NUMBER_AFTER_NAME] = stack_number
    body[-UUID_LEN:] = fresh_uuid()
    out = bytearray(rec(ENV_TAG, raw, bytes(body)))
    struct.pack_into("<H", out, 10, object_id)
    return bytes(out)


def set_selected_object(raw: bytes, selected: bool) -> bytes:
    buf = bytearray(raw)
    buf[HEADER + SELECTED_AT] = 1 if selected else 0
    return bytes(buf)


def shifted_object(raw: bytes, *, channel: bool, stamp: bool) -> bytes:
    """An object after a channel insert below it: its channel index up one when its own
    channel's owner moved (``channel``), its stamp up by 66 when it sat above the pattern's
    (``stamp``)."""
    buf = bytearray(raw)
    if channel:
        at = HEADER + name_end(raw[HEADER:])
        struct.pack_into("<H", buf, at, struct.unpack_from("<H", buf, at)[0] + 1)
    if stamp:
        struct.pack_into("<I", buf, HEADER + STAMP_AT, object_stamp(raw) + STAMP_SHIFT)
    return bytes(buf)
