"""Insert plugin-slot records into a project's channels — the edit that actually changes a chain.

Logic renders the slot records embedded in the project. A channel's `.cst` reference only names
the strip on the Setting button (a channel with a reference and no slot records shows an empty
Audio FX column), so giving a channel a chain means adding slot records to it.

Donors must come from a project written by the same Logic build — the satellite class version
differs between builds (`AuCU` v4 in Logic 11.2.2, v5 in 12.x), and the key that means "plugin
slot" moves with the schema.
"""

from __future__ import annotations

import hashlib
import re
import struct

from .._binary import FLOAT_OFFSET as FLOAT_OFFSET_IN_CHUNK
from .._binary import find_blocks, patch_block_floats
from .keyflags import sync_key_flags
from .mixer import CHANNEL_FMT_AT, CHANNEL_TAG, channel_formats
from .slot_width import MONO, STEREO, set_slot_format
from .slots import SLOT_INDEX_AT, SLOT_INDEX_BASE_DEFAULT, set_slot_bypass, slot_index_base
from .stream import BODY_START, HEADER, KEY_OFF, NO_KEY, OWNER_OFF, TOTAL_AT, project_records
from .validate import require_full_walk, require_valid


def instance_offsets(payloads: list[bytes], chunk_end: int) -> list[int]:
    """Payload offsets that differ between real instances of ONE plugin, after its parameters.

    These carry the per-instance id. Their position is plugin-specific, so they are measured
    from actual Logic-written instances rather than assumed; with fewer than two instances the
    answer is "none", and nothing gets rewritten.
    """
    if len(payloads) < 2:
        return []
    base = payloads[0]
    return sorted({i for other in payloads[1:]
                   for i in range(min(len(base), len(other)))
                   if base[i] != other[i] and i >= chunk_end})

_LABEL = re.compile(rb"(?<=\x00)[\x20-\x7e]{1,63}\.pst")


def state_blocks(blocks: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """A record's live block and the same-size copies a Logic re-save writes right after it. A
    value goes into every one, or Logic loads the stale copy (the logic README, gotcha 1)."""
    run = blocks[:1]
    for b in blocks[1:]:
        if (b[1], b[2]) != (run[0][1], run[0][2]):
            break
        run.append(b)
    return run


def apply_float_overrides(raw: bytes, overrides: dict) -> bytes:
    """Set individual parameter floats, leaving every other value in the record untouched.

    Writing a whole array would zero the parameters we cannot map — ChromaVerb has 81 floats of
    which about a dozen are documented — so a dial is expressed as {index: value}.
    """
    if not overrides:
        return raw
    blocks = find_blocks(raw[HEADER:])
    if not blocks:
        return raw
    n = blocks[0][2]
    body = bytearray(raw[HEADER:])
    for i, value in overrides.items():
        i = int(i)
        if not 0 <= i < n:
            raise ValueError(f"float index {i} is outside the plug-in's block of {n}")
        for idx, _tid, _n in state_blocks(blocks):
            struct.pack_into("<f", body, idx + FLOAT_OFFSET_IN_CHUNK + i * 4, float(value))
    return raw[:HEADER] + bytes(body)


def relabel_slot(raw: bytes, name: str) -> bytes:
    """Rewrite a slot record's preset label in place; a clone otherwise keeps the donor's.

    The field is null-padded, so the writable run is the label plus its trailing nulls —
    measured rather than assumed, since the width differs between contexts.
    """
    m = _LABEL.search(raw)
    if not m:
        return raw
    end = m.end()
    while end < len(raw) and raw[end] == 0:
        end += 1
    field = end - m.start()
    encoded = f"{name}.pst".encode("latin-1")
    if len(encoded) > field:
        raise ValueError(f"label '{name}.pst' exceeds the {field}-byte field")
    return raw[:m.start()] + encoded.ljust(field, b"\x00") + raw[end:]


# WIDTH, channel side. Three bytes move together, not just the count at +123. Measured per
# session as the bytes where every stereo aux agrees and the mono one differs; identical in every
# session measured, across both class versions, and matched by the one session Logic itself wrote
# with a stereo Vox Slapback.
CHANNEL_WIDTH = {78: {MONO: 211, STEREO: 215}, 86: {MONO: 0, STEREO: 1},
                 CHANNEL_FMT_AT: {MONO: MONO, STEREO: STEREO}}


def set_channel_format(raw: bytes, fmt: int) -> bytes:
    """Rewrite a channel record's width. Nothing else in the record moves."""
    payload_len = len(raw) - HEADER
    if payload_len <= CHANNEL_FMT_AT or raw[HEADER + CHANNEL_FMT_AT] == fmt:
        return raw
    buf = bytearray(raw)
    for off, byfmt in CHANNEL_WIDTH.items():
        if off < payload_len:
            buf[HEADER + off] = byfmt[fmt]
    return bytes(buf)


def widen_channels(data: bytes, want: dict[int, int]) -> tuple[bytes, list[int]]:
    """Set the width of whole channels -> ``(project, [owners actually changed])``.

    Plugins already on the channel are re-stamped to match: a slot carries its own width, so a
    channel widened on its own leaves them at the old one and ``validate_project`` refuses the
    result. Running before ``insert_slots`` also hands it the width to give the slots it places.
    """

    require_full_walk(data)
    out, changed = [], []
    for record in project_records(data):
        raw = record.raw
        if record.tag == CHANNEL_TAG and record.key == NO_KEY and record.owner in want:
            new = set_channel_format(raw, want[record.owner])
            if new != raw:
                raw = new
                if record.owner not in changed:
                    changed.append(record.owner)
        elif record.owner in want and find_blocks(raw[HEADER:]):
            try:
                raw = set_slot_format(raw, want[record.owner])
            except ValueError as e:
                raise ValueError(f"channel {record.owner} key {record.key}: cannot follow the "
                                 f"channel to width {want[record.owner]} — {e}") from None
        out.append(raw)
    body = b"".join(out)
    head = bytearray(data[:BODY_START])
    struct.pack_into("<I", head, TOTAL_AT, len(body))
    result = bytes(head) + body
    require_valid(result)
    return result, sorted(changed)


def _stamp(raw: bytes, owner: int, key: int, floats, limit: int, seed: str,
           label: str | None = None, fmt: int | None = None,
           id_offsets: tuple[int, ...] = (), type_id: int | None = None,
           bypass: bool = False, index_base: int = SLOT_INDEX_BASE_DEFAULT,
           overrides: dict | None = None) -> bytes:
    """Clone a donor slot: retarget it, give it its own instance id, patch its parameters.

    ``id_offsets`` must be measured from real instances of this plugin — writing at assumed
    positions overwrites live data (it broke every Enveloper record).
    """
    if fmt is not None and (type_id is not None or find_blocks(raw[HEADER:])):
        raw = set_slot_format(raw, fmt, type_id)
    if bypass:
        raw = set_slot_bypass(raw, True)
    buf = bytearray(raw)
    struct.pack_into("<H", buf, OWNER_OFF, owner)
    struct.pack_into("<H", buf, KEY_OFF, key)
    if HEADER + SLOT_INDEX_AT < len(buf):
        buf[HEADER + SLOT_INDEX_AT] = max(0, key - index_base)

    digest = hashlib.sha256(seed.encode()).digest()
    for i, off in enumerate(id_offsets):
        if 0 <= off < len(buf) - HEADER:
            buf[HEADER + off] = digest[i % len(digest)]

    if label:
        buf = bytearray(relabel_slot(bytes(buf), label))
    if floats:
        inner = bytearray(buf[HEADER:])
        for idx, _tid, n in state_blocks(find_blocks(bytes(inner))):
            patch_block_floats(inner, idx, 0, list(floats)[:min(limit or len(floats), n)])
        buf[HEADER:] = inner
    if overrides:                                     # a dialled value wins over the strip's
        buf = bytearray(apply_float_overrides(bytes(buf), overrides))
    return bytes(buf)


def _clones(plan: dict, formats: dict[int, int], owner: int,
            index_base: int = SLOT_INDEX_BASE_DEFAULT) -> list[bytes]:
    """Every slot record to add for one channel. One place, so the two insertion sites
    (channel with satellites / channel without) can never drift apart.

    A plan entry is (donor, key, floats, limit[, label[, id_offsets[, type_id]]]).
    """
    out = []
    for entry in plan[owner]:
        donor, key, floats, limit = entry[:4]
        label = entry[4] if len(entry) > 4 else None
        id_offsets = entry[5] if len(entry) > 5 else ()
        type_id = entry[6] if len(entry) > 6 else None
        bypass = entry[7] if len(entry) > 7 else False
        overrides = entry[8] if len(entry) > 8 else None
        out.append(_stamp(donor, owner, key, floats, limit, f"{owner}:{key}", label,
                          formats.get(owner), id_offsets, type_id, bypass, index_base,
                          overrides))
    return out


def insert_slots(data: bytes, plan: dict[int, list[tuple[bytes, int, object, int]]],
                 drop: dict[int, set[int]] | None = None) -> bytes:
    """Add slot records to channels. ``plan`` maps owner -> [(donor_raw, key, floats, limit)].

    Any existing record whose owner and key the plan writes is dropped, so re-running is
    idempotent rather than stacking duplicates. The match is on ``(owner, key)`` alone, not on
    the record's tag: a plan that reaches the key of a channel's `.cst` reference record takes
    that record too. ``drop`` removes further ``owner -> {key}`` records — the caller's way to
    clear a superseded copy the plan's own keys do not reach.
    """
    records = project_records(data)
    formats = channel_formats(data)
    index_base = slot_index_base(data)
    owners = {r.owner for r in records if r.tag == CHANNEL_TAG}
    missing = sorted(set(plan) - owners)
    if missing:
        raise ValueError(f"no channel record for owner(s) {missing}")

    # Where the slots go: immediately before the owner's first satellite (slot keys are the
    # lowest, so that is their sorted position). A channel can be preceded by a 14-byte OCuA
    # stub, so "after the first channel record" would attach them to the stub instead.
    anchor: dict[int, int] = {}
    for i, record in enumerate(records):
        if record.owner not in plan or record.owner in anchor:
            continue
        if record.tag == b"UCuA":
            anchor[record.owner] = i
    for owner in plan:
        if owner not in anchor:  # no satellites at all — sit after the largest channel record
            best = max((i for i, r in enumerate(records)
                        if r.owner == owner and r.tag == CHANNEL_TAG), key=lambda i: len(records[i].raw))
            anchor[owner] = best + 1

    replacing = {owner: {e[1] for e in slots} for owner, slots in plan.items()}
    inserts = {i: owner for owner, i in anchor.items()}
    out = []
    for i, record in enumerate(records):
        if i in inserts:
            owner = inserts[i]
            out += _clones(plan, formats, owner, index_base)
        if record.owner in replacing and record.key in replacing[record.owner]:
            continue  # drop any slot we are about to write
        if drop and record.key in drop.get(record.owner, ()):
            continue
        out.append(record.raw)
    for i, owner in inserts.items():
        if i >= len(records):
            out += _clones(plan, formats, owner, index_base)

    body = b"".join(out)
    head = bytearray(data[:BODY_START])
    struct.pack_into("<I", head, TOTAL_AT, len(body))
    result = bytes(head) + body

    # Never hand back a project that violates a structural invariant.
    require_valid(result)
    return sync_key_flags(result)
