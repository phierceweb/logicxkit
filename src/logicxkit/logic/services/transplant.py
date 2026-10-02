"""Move a channel's plugin slots from one project onto a channel of another.

The slot records are cloned verbatim — third-party AU state is opaque bytes and needs no
decode — then re-stamped for the target (owner, key, slot index, width for native plugins).

Which keys are slots is per project: they run from 4 up to the key of the channel's `.cst`
reference record, which sits at 9, 10, 12 or 13 depending on the session. That range is the
capacity, and overrunning it deletes the reference record — `validate_project` cannot see the
loss, so the guard here is the only thing standing in front of it.
"""

from __future__ import annotations

from .._binary import find_blocks
from .binding import channels
from .chains import channel_references
from .keyflags import sync_key_flags
from .recbuild import rec
from .insert import insert_slots, instance_offsets
from .mixer import channel_formats, is_mixer_record
from .slot_width import MONO, STEREO, slot_format
from .slots import set_slot_bypass, slot_index_base
from .stream import HEADER, ProjRecord, project_records, reassemble
from .plugins import plugin_identity
from .sidechain import carry
from .slots import is_plugin_slot, property_key_base
from .validate import require_full_walk, require_valid

# A slot's instance id sits in the last 20 bytes but the final four: same-settings instance
# pairs in Logic's saves differ nowhere else.
ID_WINDOW, ID_TAIL = 20, 4
_WIDTH_NAMES = {MONO: "mono", STEREO: "stereo"}


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


def slot_at(data: bytes, owner: int, position: int) -> ProjRecord | None:
    """The plug-in in mixer slot ``position`` (from 1, empty slots counted — the insert number
    automation names it by), or None when that slot is empty."""
    key = slot_index_base(data) + position - 1
    return next((r for r in channel_slots(data, owner) if r.key == key), None)


def slot_position(data: bytes, record: ProjRecord) -> int:
    return record.key - slot_index_base(data) + 1


def owner_of(data: bytes, label: str) -> int | None:
    return next((o for o, c in channels(data).items() if c.label == label), None)


def transplant(src: bytes, dst: bytes, *, src_owner: int, dst_owner: int,
               bypass: bool = False, force: bool = False, fan_out: bool = False) -> tuple[bytes, dict]:
    """Replace ``dst_owner``'s slots with clones of ``src_owner``'s -> ``(project, report)``.

    The clones take ``dst``'s own slot keys (from 2 in projects made before Logic 11.2, from 4
    since), whatever keys ``src`` used. A one-to-one move copies each slot byte for byte, id
    included. ``fan_out`` says the same source goes onto more than one channel: then each copy
    gets its own instance id, measured from a second instance of that plug-in in ``src``, and a
    plug-in with no second instance is refused. Refuses a move that would overrun the key range,
    cross a class version or change a third-party slot's width on an audio channel; ``force``
    writes anyway.
    """
    require_full_walk(dst)
    slots = channel_slots(src, src_owner)
    if not slots:
        raise ValueError(f"source channel {src_owner} carries no plugin slots")
    existing = {r.key for r in channel_slots(dst, dst_owner)}
    first = slot_index_base(dst)
    base = property_key_base(dst)
    src_width, dst_width = channel_formats(src).get(src_owner), channel_formats(dst).get(dst_owner)
    offsets = [id_offsets(src, r.raw) if fan_out else () for r in slots]
    if not force:
        _refuse_unsafe(slots, first=first, base=base, dst_version=slot_class_version(dst))
        if is_audio(dst, dst_owner):
            refuse_width([r.raw for r in slots], dst_width)
        if fan_out and not all(offsets):
            name = _describe(slots[[bool(o) for o in offsets].index(False)].raw)
            raise ValueError(
                f"{name} goes onto more than one channel, and the source holds no second instance "
                "of it to measure its instance id from, so every copy would share one id. Add a "
                "second instance to the source, or pass --force to copy it as it is.")
    keys = list(range(first, first + len(slots)))
    carried = [carry(src, r.raw, dst) for r in slots]      # a side chain follows its source's name
    plan = {dst_owner: [(raw, key, None, None, None, ids or (), None, bypass, None)
                        for (raw, _note), key, ids in zip(carried, keys, offsets, strict=True)]}
    out = insert_slots(dst, plan, drop={dst_owner: existing - set(keys)})
    require_valid(out)
    ids = "verbatim" if not fan_out else "unmeasured" if not all(offsets) else "stamped"
    return out, {"slots": len(slots), "replaced": sorted(existing),
                 "width": (src_width, dst_width),
                 "width_mismatch": bool(src_width and dst_width and src_width != dst_width),
                 "ids": ids, "ref": channel_references(src).get(src_owner),
                 "side_chains": [note for _raw, note in carried if note]}


def id_offsets(data: bytes, raw: bytes) -> tuple[int, ...] | None:
    """Payload offsets of ``raw``'s instance id, from the other instances of the same plug-in
    in ``data``; None when there is no other to measure against. Only the id window counts, so
    two instances saved with different settings are not mistaken for it."""
    payload = raw[HEADER:]
    identity = plugin_identity(payload)
    if identity is None:
        return None
    base, index_base = property_key_base(data), slot_index_base(data)
    others = [r.raw[HEADER:] for r in project_records(data)
              if is_plugin_slot(r, base, index_base) and r.raw != raw and len(r.raw) == len(raw)
              and plugin_identity(r.raw[HEADER:]) == identity]
    if not others:
        return None
    return window_offsets(payload, others)


def window_offsets(payload: bytes, others: list[bytes]) -> tuple[int, ...]:
    """Where ``payload`` differs from other instances of its plug-in inside the id window; empty
    when they carry one id (a copied instance), so nothing tells the id's bytes apart."""
    lower, end = len(payload) - ID_WINDOW, len(payload) - ID_TAIL
    blocks = find_blocks(payload)
    if blocks:                       # never past a native chunk's floats: settings are not an id
        lower = max(lower, blocks[0][0] + 12 + blocks[0][2] * 4)
    return tuple(o for o in instance_offsets([payload, *others], lower) if o < end)


def is_audio(data: bytes, owner: int) -> bool:
    channel = channels(data).get(owner)
    return channel is not None and channel.label.startswith("Audio ")


def is_instrument_channel(data: bytes, owner: int) -> bool:
    """An instrument channel's slot 1 is its instrument (automation's insert 1 there)."""
    channel = channels(data).get(owner)
    return channel is not None and channel.label.startswith("Inst ")


def refuse_width(raws: list[bytes], dst_width: int | None) -> None:
    """A native slot is re-stamped to the channel's width; a third-party one cannot be. Audio
    channels only: on all but a few third-party slots in Logic's saves the two agree there,
    while an instrument channel's width byte says nothing about its plug-in (many differ)."""
    for raw in raws:
        width = slot_format(raw)
        if dst_width and width and width != dst_width and not find_blocks(raw[HEADER:]):
            want, have = (_WIDTH_NAMES.get(w, str(w)) for w in (dst_width, width))
            raise ValueError(
                f"{_describe(raw)} was saved {have} and this channel is {want}; a third-party "
                f"plug-in keeps the width it was saved at. Take it from a {want} track, or pass "
                "--force.")


def _describe(raw: bytes) -> str:
    identity = plugin_identity(raw[HEADER:])
    if identity is None:
        return "a slot"
    return f"plug-in type {identity[1]}" if identity[0] == "native" else f"{identity[3]}/{identity[2]}"


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
    # right after the owner's last slot-range record, else after its channel record proper:
    # owner 0 also owns the 14-byte stubs that sit past every channel
    owned = [i for i, r in enumerate(kept) if r.owner == dst_owner and (r.tag == b"UCuA" and r.key < key or is_mixer_record(r))]
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
