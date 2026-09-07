"""Environment objects — the `ivnE` records that name tracks and stack folders.

    +0     u32   channel-object type in the low half: 1800 at class v12 (Logic 12), 1728 at
                 v11; mixed projects set flag bits 0x4040 in the high half on some tracks
    +16    u32   object id — what a `karT` row's +8 points at
    +38    u32   parent: the object id of the stack this track was dragged into (0 = never)
    +80    u8    1 on the selected object only (`selection.py`)
    +82    u32   per-object stamp: a fresh object gets its pattern's plus the pattern's +86;
                 on a channel insert every object above the pattern's moves up by 66
    +86    u16   0x42 on a fresh object
    +154   u8    kind; 0 marks a grouping object (stack folders, Logic's Preview/Click/Master)
    +155   u8    track colour, a palette index (drums 96, guitars 81; a recolour moved 96 -> 64)
    +158   u16   name length, the name follows (padded to an even length)
    name end     u16 = the bound channel's owner + 1, kept live when owners shift; on a
    name end +3  stack object, its Sub number
    last 16      the object's instance UUID; a mixer channel binds to an object by carrying it

Payload length is 463 or 464 plus the name length, so a rename changes the record size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .insert import HEADER, project_records, reassemble
from .validate import require_full_walk
from .recbuild import fresh_uuid, rec

ENV_TAG = b"ivnE"
CHANNEL_OBJECT = {11: 1728, 12: 1800}
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
                                  # the channel-strip setting's name instead (1,327 named
                                  # tracks on 39 files set it; Logic's own fresh adds do not)
STACK_NUMBER_AFTER_NAME = 3
_NAME_MAX = 63


@dataclass(frozen=True)
class EnvObject:
    object_id: int
    name: str
    kind: int
    parent: int
    uuid: bytes
    size: int
    colour: int = 0
    icon: int = 0


def _constant(records) -> int | None:
    version = next((r.ver for r in records if r.tag == ENV_TAG), None)
    return CHANNEL_OBJECT.get(version)


TYPE_MASK = 0xFFFF                 # +0: the type in the low half; mixes set flags above it


def _is_channel_object(payload: bytes, constant: int | None) -> bool:
    return (constant is not None and len(payload) > NAME_AT + 2 + UUID_LEN
            and struct.unpack_from("<I", payload, 0)[0] & TYPE_MASK == constant)


def _name(payload: bytes) -> str | None:
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    if not (0 < n <= _NAME_MAX) or NAME_AT + 2 + n > len(payload):
        return None
    raw = payload[NAME_AT + 2:NAME_AT + 2 + n]
    return raw.decode("latin-1") if all(32 <= c < 127 for c in raw) else None


def channel_objects(data: bytes) -> dict[int, EnvObject]:
    """object id -> the channel-type Environment objects whose name decodes."""
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
        name = _name(payload)
        if name is None:
            continue
        object_id = struct.unpack_from("<I", payload, OBJECT_ID_AT)[0]
        out[object_id] = EnvObject(
            object_id=object_id, name=name, kind=payload[KIND_AT],
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

    Track rows count too. Nine of the ten sessions on hand have `karT` rows naming ids above
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
    if record.tag != ENV_TAG or not _is_channel_object(payload, CHANNEL_OBJECT.get(record.ver)):
        return None
    return struct.unpack_from("<I", payload, OBJECT_ID_AT)[0]


def name_end(payload: bytes) -> int:
    """Offset just past the even-padded name: the bound-channel index lives there."""
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    return NAME_AT + 2 + n + (n & 1)


def object_stamp(raw: bytes) -> int:
    return struct.unpack_from("<I", raw, HEADER + STAMP_AT)[0]


def _with_name(payload: bytes, name: str) -> bytearray:
    """The payload with the name field rewritten; everything after it keeps its place."""
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    if not name.isascii() or not name.isprintable():
        raise ValueError("a track name is printable ASCII here — no file on hand shows how Logic "
                         "stores anything else")
    encoded = name.encode("ascii")
    if not 0 < len(encoded) <= _NAME_MAX:
        raise ValueError(f"a track name is 1-{_NAME_MAX} characters")
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
    """Rename one track's object; the only field a rename touches (unmeasured: no Logic
    rename save on hand, but the object is the sole holder of the name)."""
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
