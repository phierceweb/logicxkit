"""Move a channel's plugin slots from one project onto a channel of another.

The slot records are cloned verbatim — third-party AU state is opaque bytes and needs no
decode — then re-stamped for the target (owner, key, slot index, width for native plugins).

Which keys are slots is per project: they run from 4 up to the key of the channel's `.cst`
reference record, which sits at 9, 10, 12 or 13 depending on the session. That range is the
capacity, and overrunning it deletes the reference record — `validate_project` cannot see the
loss, so the guard here is the only thing standing in front of it.
"""

from __future__ import annotations

from .binding import channels
from .chains import channel_references
from .keyflags import sync_key_flags
from .recbuild import rec
from .insert import (
    CHANNEL_TAG,
    HEADER,
    SLOT_INDEX_AT,
    ProjRecord,
    channel_formats,
    insert_slots,
    project_records,
    reassemble,
    set_slot_bypass,
    slot_index_base,
)
from .validate import require_full_walk, require_valid

_DEFAULT_PROPERTY_KEY = 10


def property_key_base(data: bytes) -> int:
    """The key of the `.cst` reference record — the first key that is a property, not a slot."""
    keys = [r.key for r in project_records(data)
            if r.tag == b"UCuA" and len(r.raw) - HEADER < 400 and b".cst" in r.raw]
    return min(keys) if keys else _DEFAULT_PROPERTY_KEY


def is_plugin_slot(record: ProjRecord, base: int, index_base: int) -> bool:
    """A plugin slot: in the slot key range AND carrying its slot index at +6. Every session's
    Audio 1 also holds a 200-byte 'Audio Recording' record in that range, and Aux strips a
    68-byte one, both with +6 = 0 — not slots, never to be bypassed or cloned."""
    payload = record.raw[HEADER:]
    return (record.tag == b"UCuA" and index_base <= record.key < base
            and len(payload) > SLOT_INDEX_AT and payload[SLOT_INDEX_AT] == record.key - index_base)


def slot_class_version(data: bytes) -> int | None:
    """The class version this project writes plugin slots at, or None if it is not uniform."""
    base, index_base = property_key_base(data), slot_index_base(data)
    versions = {r.ver for r in project_records(data) if is_plugin_slot(r, base, index_base)}
    return versions.pop() if len(versions) == 1 else None


def channel_slots(data: bytes, owner: int) -> list[ProjRecord]:
    """The plugin-slot records one channel carries, in key order."""
    base, index_base = property_key_base(data), slot_index_base(data)
    return sorted((r for r in project_records(data)
                   if r.owner == owner and is_plugin_slot(r, base, index_base)),
                  key=lambda r: r.key)


def owner_of(data: bytes, label: str) -> int | None:
    return next((o for o, c in channels(data).items() if c.label == label), None)


def transplant(src: bytes, dst: bytes, *, src_owner: int, dst_owner: int,
               bypass: bool = False, force: bool = False) -> tuple[bytes, dict]:
    """Replace ``dst_owner``'s slots with clones of ``src_owner``'s -> ``(project, report)``.

    The clones take ``dst``'s own slot keys (from 2 in projects made before Logic 11.2, from 4
    since), whatever keys ``src`` used. Refuses a move that would overrun the key range or
    cross a class version; ``force`` writes anyway.
    """
    require_full_walk(dst)
    slots = channel_slots(src, src_owner)
    if not slots:
        raise ValueError(f"source channel {src_owner} carries no plugin slots")
    existing = {r.key for r in channel_slots(dst, dst_owner)}
    first = slot_index_base(dst)
    base = property_key_base(dst)
    if not force:
        _refuse_unsafe(slots, first=first, base=base, dst_version=slot_class_version(dst))
    keys = list(range(first, first + len(slots)))
    plan = {dst_owner: [(r.raw, key, None, None, None, (), None, bypass, None)
                        for r, key in zip(slots, keys, strict=True)]}
    out = insert_slots(dst, plan, drop={dst_owner: existing - set(keys)})
    require_valid(out)
    src_width, dst_width = channel_formats(src).get(src_owner), channel_formats(dst).get(dst_owner)
    return out, {"slots": len(slots), "replaced": sorted(existing),
                 "width": (src_width, dst_width),
                 "width_mismatch": bool(src_width and dst_width and src_width != dst_width),
                 "ref": channel_references(src).get(src_owner)}


def _refuse_unsafe(slots: list[ProjRecord], *, first: int, base: int,
                   dst_version: int | None) -> None:
    capacity = base - first
    if len(slots) > capacity:
        raise ValueError(
            f"{len(slots)} source slots into a channel that holds {capacity}: keys "
            f"{first}..{first + len(slots) - 1} would run into the `.cst` reference record at "
            f"key {base} and delete it. Move fewer slots, or pass --force.")
    versions = sorted({r.ver for r in slots})
    if dst_version is not None and versions != [dst_version]:
        got = "/".join(f"v{v}" for v in versions)
        raise ValueError(
            f"source slots are {got} and this project writes v{dst_version}: a record cannot be "
            f"legalised across class versions. Re-save the source in Logic, or pass --force.")


def reference_record(data: bytes, owner: int) -> bytes | None:
    """The channel's `.cst` reference record (the `UCuA` at the project's reference key)."""
    base = property_key_base(data)
    return next((r.raw for r in project_records(data)
                 if r.tag == b"UCuA" and r.owner == owner and r.key == base), None)


def copy_reference(src: bytes, dst: bytes, *, src_owner: int, dst_owner: int) -> bytes:
    """Give ``dst_owner`` the strip reference ``src_owner`` carries, at ``dst``'s own
    reference key, replacing one it already has. The record is a label, not a loader
    (README: references are labels), so cloning it verbatim is the whole job."""
    require_full_walk(dst)
    template = reference_record(src, src_owner)
    if template is None:
        raise ValueError(f"source channel {src_owner} carries no strip reference")
    key = property_key_base(dst)
    new = rec(b"UCuA", template, template[HEADER:], owner=dst_owner, key=key)
    records = project_records(dst)
    kept = [r for r in records if not (r.tag == b"UCuA" and r.owner == dst_owner and r.key == key)]
    # right after the owner's last slot-range record, else after its channel record
    owned = [i for i, r in enumerate(kept) if r.owner == dst_owner and (r.tag == b"UCuA" and r.key < key or r.tag == CHANNEL_TAG)]
    at = (owned[-1] + 1) if owned else len(kept)
    out = [r.raw for r in kept[:at]] + [new] + [r.raw for r in kept[at:]]
    result = sync_key_flags(reassemble(dst, out))
    require_valid(result)
    return result


def remove_slots(data: bytes, owner: int) -> tuple[bytes, list[int]]:
    """Drop every plugin slot one channel carries -> ``(project, [keys removed])``. The
    non-slot records in the key range and the `.cst` reference stay; the channel's key flags
    follow (a flag left set for a missing record is a file Logic refuses to open)."""
    require_full_walk(data)
    base, index_base = property_key_base(data), slot_index_base(data)
    out, removed = [], []
    for record in project_records(data):
        if record.owner == owner and is_plugin_slot(record, base, index_base):
            removed.append(record.key)
            continue
        out.append(record.raw)
    result = sync_key_flags(reassemble(data, out))
    require_valid(result)
    return result, sorted(removed)


def set_bypass(data: bytes, owner: int, bypassed: bool = True) -> tuple[bytes, list[int]]:
    """Bypass (or enable) every plugin slot on one channel -> ``(project, [keys changed])``."""
    require_full_walk(data)
    base, index_base = property_key_base(data), slot_index_base(data)
    out, changed = [], []
    for record in project_records(data):
        raw = record.raw
        if record.owner == owner and is_plugin_slot(record, base, index_base):
            new = set_slot_bypass(raw, bypassed)
            if new != raw:
                changed.append(record.key)
                raw = new
        out.append(raw)
    result = data[:24] + b"".join(out)
    require_valid(result)
    return result, changed
