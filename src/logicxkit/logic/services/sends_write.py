"""Write sends — add one, copy a channel's set from another project, or drop them.

A send sits right after its channel's `OCuA` in key order, before the plugin slots (key 4+);
`sends.py` has the layout. Nothing is synthesised: a new send is a clone of one the project
already carries, so the level bytes and the undecoded `+8` word come from the template, and
only the fields the file proves are set — owner, key, `+4`, `+20`, a fresh instance UUID at
`+44` and the target bus channel's UUID at `+60` — plus the slot's flag on the channel's own
record. Not yet confirmed by opening in Logic.
"""

from __future__ import annotations

import struct

from .binding import Channel, channels
from .keyflags import sync_key_flags
from .insert import CHANNEL_TAG, HEADER, KEY_OFF, ProjRecord, project_records, reassemble
from .recbuild import fresh_uuid, rec
from .sends import (
    BUS_AT,
    CLASS_AT,
    DEST_UUID_AT,
    INSTANCE_UUID_AT,
    SEND_KEYS,
    SEND_TAG,
    SLOT_AT,
    is_send,
    read_sends,
    send_base,
)
from .validate import require_full_walk, require_valid

UUID_LEN = 16


def _bus_uuid(chans: dict[int, Channel], bus: int) -> bytes:
    chan = next((c for c in chans.values() if c.label == f"Bus {bus}"), None)
    if chan is None or chan.uuid == bytes(UUID_LEN):
        raise ValueError(f"no Bus {bus} channel with a UUID to target")
    return chan.uuid


def _template(records: list[ProjRecord], owner: int) -> bytes:
    """A send to clone: one of the channel's own if it has any, else the project's first."""
    sends = [r for r in records if is_send(r)]
    if not sends:
        raise ValueError("this project carries no send to clone; a donor project is needed")
    return next((r.raw for r in sends if r.owner == owner), sends[0].raw)


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


def _place(records: list[ProjRecord], owner: int, new: bytes) -> list[ProjRecord]:
    """``new`` into the owner's satellite run in key order: before the first satellite with a
    higher key, else after the last one, else right after the owner's longest channel record."""
    key = struct.unpack_from("<H", new, KEY_OFF)[0]
    sats = [i for i, r in enumerate(records) if r.owner == owner and r.tag == SEND_TAG]
    later = [i for i in sats if records[i].key > key]
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
    out = sync_key_flags(reassemble(data, [r.raw for r in records]))
    require_valid(out)
    return out


def add_send(data: bytes, *, owner: int, bus: int, key: int | None = None) -> tuple[bytes, dict]:
    """A send from channel ``owner`` to ``Bus bus`` -> ``(project, {owner, key, bus, replaced})``.

    ``key`` defaults to the lowest free of 0-2; an explicit key that is taken is replaced.
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
    new = _clone(_template(records, owner), owner=owner, key=key, bus=bus,
                 bus_uuid=_bus_uuid(chans, bus), base=send_base(data))
    kept = [r for r in records if not (is_send(r) and r.owner == owner and r.key == key)]
    out = _finish(data, _place(kept, owner, new), owner)
    return out, {"owner": owner, "key": key, "bus": bus, "replaced": key in used}


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
