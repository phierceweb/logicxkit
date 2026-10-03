"""Write sends — add one, copy a channel's set from another project, or drop them.

A send sits right after its channel's `OCuA` in key order, before the plugin slots (key 4+);
`sends.py` has the layout. Nothing is synthesised: a new send is a clone of one the project
already carries, else of the one Logic made on a blank project (packaged `send-12.3.1.json`),
so the undecoded `+8` word comes from the template, and only the fields the file proves are
set — owner, key, `+4`, `+20`, a fresh instance UUID at `+44` and the target bus channel's UUID
at `+60` — plus the slot's flag on the channel's own record. An added send takes the level, mode
and bypass asked for (`with_settings`), else those of the send Logic adds; a copied send keeps its
source's.
"""

from __future__ import annotations

import json
import struct

from ....utils.data import data_file
from .binding import Channel, channels
from .levels import level_word
from ..stream.keyflags import sync_key_flags
from .mixer import CHANNEL_TAG
from ..stream.stream import HEADER, KEY_OFF, ProjRecord, project_records, reassemble
from ..stream.recbuild import fresh_uuid, rec
from .sends import (
    BUS_AT,
    BYPASS_AT,
    CLASS_AT,
    DEST_UUID_AT,
    INDEPENDENT_PAN,
    INSTANCE_UUID_AT,
    LEVEL_AT,
    LEVEL_FIXED_AT,
    MODES,
    OPTIONS_AT,
    POST_PAN_AT,
    PRE_FADER_AT,
    SEND_KEYS,
    SEND_TAG,
    SLOT_AT,
    is_send,
    read_sends,
    send_base,
)
from ..stream.validate import require_full_walk, require_valid

UUID_LEN = 16
_DATA = "send-12.3.1.json"


def _bus_uuid(chans: dict[int, Channel], bus: int) -> bytes:
    chan = next((c for c in chans.values() if c.label == f"Bus {bus}"), None)
    if chan is None or chan.uuid == bytes(UUID_LEN):
        raise ValueError(f"no Bus {bus} channel with a UUID to target")
    return chan.uuid


def _packaged() -> bytes:
    """The send Logic made on a blank project (packaged `send-12.3.1.json`)."""
    t = json.loads(data_file("logic", _DATA).read_text())
    return bytes.fromhex(t["header"]) + bytes.fromhex(t["payload"])


def _template(records: list[ProjRecord], owner: int) -> bytes:
    """A send to clone: the channel's own, else the project's first, else the packaged one."""
    sends = [r for r in records if is_send(r)]
    if sends:
        return next((r.raw for r in sends if r.owner == owner), sends[0].raw)
    return _packaged()


def _as_logic_adds(raw: bytes) -> bytes:
    """``raw`` with the level, mode, bypass and independent pan of the send Logic adds: its
    second send beside one at -16.8 dB came in at -inf, post pan (`send-two-base-3-logic`)."""
    logic, buf = _packaged()[HEADER:], bytearray(raw)
    for at in (POST_PAN_AT, LEVEL_AT, PRE_FADER_AT, BYPASS_AT):
        buf[HEADER + at] = logic[at]
    buf[HEADER + OPTIONS_AT] = buf[HEADER + OPTIONS_AT] & ~INDEPENDENT_PAN | logic[OPTIONS_AT] & INDEPENDENT_PAN
    buf[HEADER + LEVEL_FIXED_AT:HEADER + LEVEL_FIXED_AT + 4] = logic[LEVEL_FIXED_AT:LEVEL_FIXED_AT + 4]
    return bytes(buf)


def _clone(template: bytes, *, owner: int, key: int, bus: int, bus_uuid: bytes, base: int,
           container: bytes | None = None) -> bytes:
    """``template`` re-targeted. ``container``, a send of the destination project, lends its
    header and class word when the source comes from another project; ``base`` is the
    destination project's `send_base`."""
    p = bytearray(template[HEADER:])
    if container is not None:
        p[CLASS_AT:CLASS_AT + 4] = container[HEADER + CLASS_AT:HEADER + CLASS_AT + 4]
    struct.pack_into("<I", p, SLOT_AT, key << 16)
    struct.pack_into("<H", p, BUS_AT, bus + base)
    p[INSTANCE_UUID_AT:INSTANCE_UUID_AT + UUID_LEN] = fresh_uuid()
    p[DEST_UUID_AT:DEST_UUID_AT + UUID_LEN] = bus_uuid
    return rec(SEND_TAG, container or template, bytes(p), owner=owner, key=key)


def with_settings(raw: bytes, *, level_db: float | None = None, mode: str | None = None,
                  bypass: bool | None = None) -> bytes:
    """The send record with its level (``float("-inf")`` silences it), mode and bypass set;
    ``None`` leaves one as it is."""
    buf = bytearray(raw)
    if level_db is not None:
        struct.pack_into("<I", buf, HEADER + LEVEL_FIXED_AT, level_word(level_db))
        buf[HEADER + LEVEL_AT] = buf[HEADER + LEVEL_FIXED_AT + 3]
    if mode is not None:
        if mode not in MODES:
            raise ValueError("a send's mode is post pan, post fader or pre fader")
        buf[HEADER + POST_PAN_AT], buf[HEADER + PRE_FADER_AT] = MODES[mode]
    if bypass is not None:
        buf[HEADER + BYPASS_AT] = 1 if bypass else 0
    return bytes(buf)


def _place(records: list[ProjRecord], owner: int, new: bytes) -> list[ProjRecord]:
    """``new`` into the owner's satellite run in key order: before the first satellite with a
    higher key or a slot at its own, else after the last one, else right after the owner's
    longest channel record."""
    key = struct.unpack_from("<H", new, KEY_OFF)[0]
    sats = [i for i, r in enumerate(records) if r.owner == owner and r.tag == SEND_TAG]
    later = [i for i in sats if records[i].key > key or (records[i].key == key and not is_send(records[i]))]
    if later:
        at = later[0]
    elif sats:
        at = sats[-1] + 1
    else:
        chan = [i for i, r in enumerate(records) if r.owner == owner and r.tag == CHANNEL_TAG]
        if not chan:
            raise ValueError(f"no channel record for owner {owner}")
        at = max(chan, key=lambda i: len(records[i].raw)) + 1
    return records[:at] + project_records(new, start=0) + records[at:]


def _finish(data: bytes, records: list[ProjRecord], owner: int) -> bytes:
    """The records written back; a third send in a base-2 project takes slot 1's key, and Logic
    drops the plug-in there, so the project moves to Logic 12's layout (`slotkeys`)."""
    from .slotkeys import needs_rebase, rebase                # slotkeys reads sends
    out = sync_key_flags(reassemble(data, [r.raw for r in records]))
    require_valid(out)
    return rebase(out)[0] if needs_rebase(out) else out


def add_send(data: bytes, *, owner: int, bus: int, key: int | None = None,
             level_db: float | None = None, mode: str | None = None,
             bypass: bool | None = None) -> tuple[bytes, dict]:
    """A send from channel ``owner`` to ``Bus bus`` -> ``(project, {owner, key, bus, replaced})``.

    ``key`` defaults to the lowest free of 0-2; an explicit key that is taken is replaced. A
    second send to a bus the channel already sends to is refused. The level, mode and bypass
    are the ones given, else those of the send Logic adds (`with_settings`, `_as_logic_adds`).
    """
    require_full_walk(data)
    records = project_records(data)
    chans = channels(data)
    if owner not in chans:
        raise ValueError(f"no channel record for owner {owner}")
    used = {r.key for r in records if is_send(r) and r.owner == owner}
    if key is None:
        key = next((k for k in SEND_KEYS if k not in used), None)
        if key is None:
            raise ValueError(f"channel {owner} already carries three sends")
    elif key not in SEND_KEYS:
        raise ValueError("a send key is 0, 1 or 2")
    twin = next((s for s in read_sends(data).get(owner, []) if s.bus == bus and s.key != key), None)
    if twin is not None:
        raise ValueError(f"channel {owner} already sends to Bus {bus} (send {twin.key}); set that one instead")
    new = with_settings(_as_logic_adds(_clone(_template(records, owner), owner=owner, key=key, bus=bus,
                                              bus_uuid=_bus_uuid(chans, bus), base=send_base(data))),
                        level_db=level_db, mode=mode, bypass=bypass)
    kept = [r for r in records if not (is_send(r) and r.owner == owner and r.key == key)]
    out = _finish(data, _place(kept, owner, new), owner)
    return out, {"owner": owner, "key": key, "bus": bus, "replaced": key in used}


def set_send(data: bytes, *, owner: int, bus: int, level_db: float | None = None,
             mode: str | None = None, bypass: bool | None = None) -> tuple[bytes, dict]:
    """The level, mode or bypass of ``owner``'s send to ``Bus bus`` -> ``(project, {owner, key,
    bus})``. The record keeps its size and place; nothing else moves."""
    require_full_walk(data)
    mine = [s for s in read_sends(data).get(owner, []) if s.bus == bus]
    if not mine:
        raise ValueError(f"channel {owner} has no send to Bus {bus}")
    new = with_settings(mine[0].raw, level_db=level_db, mode=mode, bypass=bypass)
    key = mine[0].key
    out = reassemble(data, [new if is_send(r) and r.owner == owner and r.key == key else r.raw
                            for r in project_records(data)])
    require_valid(out)
    return out, {"owner": owner, "key": key, "bus": bus}


def copy_sends(src: bytes, dst: bytes, *, src_owner: int, dst_owner: int) -> tuple[bytes, dict]:
    """Replace ``dst_owner``'s sends with clones of ``src_owner``'s, same keys and bus numbers
    -> ``(project, {keys, buses, replaced})``.

    Buses are not remapped: each clone targets ``dst``'s own ``Bus N`` channel. When ``dst``
    already carries sends, theirs is the header and class word the clones take.
    """
    require_full_walk(dst)
    sources = sorted(read_sends(src).get(src_owner, []), key=lambda s: s.key)
    if not sources:
        raise ValueError(f"source channel {src_owner} carries no sends")
    records = project_records(dst)
    chans = channels(dst)
    if dst_owner not in chans:
        raise ValueError(f"no channel record for owner {dst_owner}")
    dst_sends = [r for r in records if is_send(r)]
    container = next((r.raw for r in dst_sends if r.owner == dst_owner),
                     dst_sends[0].raw if dst_sends else None)
    replaced = sorted(r.key for r in dst_sends if r.owner == dst_owner)
    kept = [r for r in records if not (is_send(r) and r.owner == dst_owner)]
    base = send_base(dst)
    for s in sources:
        new = _clone(s.raw, owner=dst_owner, key=s.key, bus=s.bus,
                     bus_uuid=_bus_uuid(chans, s.bus), base=base, container=container)
        kept = _place(kept, dst_owner, new)
    out = _finish(dst, kept, dst_owner)
    return out, {"keys": [s.key for s in sources], "buses": [s.bus for s in sources],
                 "replaced": replaced}


def remove_sends(data: bytes, *, owner: int) -> bytes:
    """Drop every send (keys 0-2) channel ``owner`` carries."""
    require_full_walk(data)
    kept = [r for r in project_records(data) if not (is_send(r) and r.owner == owner)]
    return _finish(data, kept, owner)
