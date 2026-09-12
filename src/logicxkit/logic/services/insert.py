"""Insert plugin-slot records into a project's channels — the edit that actually changes a chain.

Logic renders the slot records embedded in the project. A channel's `.cst` reference only names
the strip on the Setting button (a channel with a reference and no slot records shows an empty
Audio FX column), so giving a channel a chain means adding slot records to it.

Length-changing, so the file-header total at 0x10 (== filesize - 24) is rewritten. Nothing else
needs fixing: the stream carries no offset table, record count or checksum.

Donors must come from a project written by the same Logic build — the satellite class version
differs between builds (`AuCU` v4 in Logic 11.2.2, v5 in 12.x), and the key that means "plugin
slot" moves with the schema.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass

from .._binary import FLOAT_OFFSET as FLOAT_OFFSET_IN_CHUNK
from .._binary import find_blocks, patch_block_floats


HEADER = 36
VER_OFF, OWNER_OFF, KEY_OFF, SIZE_OFF = 4, 14, 18, 28
TOTAL_AT = 0x10        # file header: uint32 == filesize - 24
BODY_START = 24
# raw tag bytes; note Logic stores them reversed from how they read (OCuA displays as "AuCO")
CHANNEL_TAG = b"OCuA"
NO_KEY = 0xFFFF
# WIDTH. A plugin instance carries its own width and Logic does NOT derive it from the channel
# (its own files contain channel/slot disagreements), so a cloned mono donor stays mono on a
# stereo bus. The channel's width is at OCuA payload+123 (a literal channel count).
#
# A slot's width is SEVEN fields, not six:
#   +81            per-plugin config INDEX (not a channel count — Gain's stereo index is 3)
#   +84, +118/+119 channel counts
#   +116..117      plugin-VARIANT id, selecting the mono or stereo build of the plugin
#   +156 (+157)    one byte per input bus: main, then side chain
# Setting the counts without the variant id tells Logic "stereo" while still pointing it at the
# mono build. +82/+83 (bus counts) must be left alone.
CHANNEL_FMT_AT = 123
SLOT_COUNT_AT = (84, 118, 119)
SLOT_CFG_AT = 81
SLOT_VARIANT_AT = 116
SLOT_BUS_AT = (156, 157)
MONO, STEREO = 1, 2

# BYPASS — payload +112: 0 = active, 1 = bypassed. Confirmed in Logic: a build written with 1 on
# nine Enveloper slots opened with them bypassed, and after they were enabled by hand the flag read
# 0 on exactly those channels while untouched ones still read 1.
SLOT_BYPASS_AT = 112

# Slot INDEX within the channel, written by Logic as key - 3 and unique per channel. A clone
# inherits the donor's, so without rewriting it two slots claim the same index and Logic renders
# only one of them.
SLOT_INDEX_AT = 6
SLOT_INDEX_BASE_DEFAULT = 4   # Logic 11.2 / 12; older builds start their slot keys at 3


_PLUGIN_MARKS = (b"GAMETSPP", b"<plist")      # native chunks and XML AU states; the binary-plist
                                              # property records (the strip reference) are not slots


CHANNEL_BASE_AT = 28          # every channel record's own copy of the project's slot base


def slot_index_base(data: bytes) -> int:
    """The key that slot index 0 corresponds to: 2 with up to one send in the project, 3 with
    two, 4 with three (Logic moves it with the sends, 2026-09-12). Every channel record
    carries it at +28; when they all agree that is the answer, else the project's own plugin
    slots (native chunks and AU states alike) vote."""
    words = {struct.unpack_from("<H", r.raw, HEADER + CHANNEL_BASE_AT)[0]
             for r in project_records(data) if r.tag == CHANNEL_TAG and len(r.raw) - HEADER > CHANNEL_BASE_AT + 2}
    if len(words) == 1 and next(iter(words)) in (2, 3, 4):
        return words.pop()
    votes: dict[int, int] = {}
    for record in project_records(data):
        if record.tag != b"UCuA" or not any(m in record.raw for m in _PLUGIN_MARKS):
            continue
        payload = record.raw[HEADER:]
        if len(payload) > SLOT_INDEX_AT and (find_blocks(payload) or b"GAMETSPP" not in payload):
            base = record.key - payload[SLOT_INDEX_AT]
            votes[base] = votes.get(base, 0) + 1
    return max(votes, key=votes.get) if votes else SLOT_INDEX_BASE_DEFAULT


def slot_bypassed(raw: bytes) -> bool:
    payload = raw[HEADER:]
    return len(payload) > SLOT_BYPASS_AT and payload[SLOT_BYPASS_AT] == 1


def set_slot_bypass(raw: bytes, bypassed: bool) -> bytes:
    buf = bytearray(raw)
    at = HEADER + SLOT_BYPASS_AT
    if at < len(buf):
        buf[at] = 1 if bypassed else 0
    return bytes(buf)

# config index per width, per plugin. `variant_id - config_index` is constant per plugin, so the
# variant id is rebased rather than incremented — a blanket +1 is wrong for Gain.
PLUGIN_CFG = {
    236: {MONO: 1, STEREO: 2},   # Channel EQ
    154: {MONO: 1, STEREO: 2},   # Compressor
    157: {MONO: 1, STEREO: 2},   # Enveloper
    199: {MONO: 1, STEREO: 2},   # Limiter
    183: {MONO: 1, STEREO: 3},   # Gain
    147: {MONO: 1, STEREO: 2},   # Echo
}


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
    idx, _tid, n = blocks[0]
    body = bytearray(raw[HEADER:])
    for i, value in overrides.items():
        i = int(i)
        if 0 <= i < n:
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


def channel_formats(data: bytes) -> dict[int, int]:
    """owner -> 1 (mono) or 2 (stereo), from each channel's own record."""
    out: dict[int, int] = {}
    best: dict[int, int] = {}
    for record in project_records(data):
        if record.tag != CHANNEL_TAG or record.key != NO_KEY:
            continue
        payload = record.raw[HEADER:]
        if len(payload) > CHANNEL_FMT_AT and len(payload) > best.get(record.owner, -1):
            best[record.owner] = len(payload)
            out[record.owner] = payload[CHANNEL_FMT_AT]
    return {o: f for o, f in out.items() if f in (MONO, STEREO)}


# WIDTH, channel side. Three bytes move together, not just the count at +123. Measured per
# session as the bytes where every stereo aux agrees and the mono one differs; identical in all
# ten sessions across both class versions, and matched by the one session Logic itself wrote
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
    from .validate import require_full_walk, require_valid

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


def slot_format(raw: bytes) -> int | None:
    """The channel count a slot record declares, or None if it declares none."""
    payload = raw[HEADER:]
    seen = {payload[o] for o in SLOT_COUNT_AT if o < len(payload)} - {0}
    return seen.pop() if len(seen) == 1 else None


def set_slot_format(raw: bytes, fmt: int, type_id: int | None = None) -> bytes:
    """Rewrite a slot's width — channel counts, config index and plugin-variant id together.

    ``type_id`` is read from the record's own parameter chunk when not supplied.
    """
    if slot_format(raw) == fmt:
        return raw          # already the right width — no mapping needed to change nothing
    if type_id is None:
        blocks = find_blocks(raw[HEADER:])
        type_id = blocks[0][1] if blocks else None
    cfg_map = PLUGIN_CFG.get(type_id)
    if cfg_map is None:
        raise ValueError(f"unknown plugin type {type_id}: refusing to guess its stereo config "
                         "index (a blanket 2 is wrong for e.g. Gain, whose stereo index is 3)")
    buf = bytearray(raw)
    old_cfg = buf[HEADER + SLOT_CFG_AT]
    new_cfg = cfg_map[fmt]

    for off in SLOT_COUNT_AT:
        at = HEADER + off
        if at < len(buf) and buf[at] in (MONO, STEREO):
            buf[at] = fmt
    buf[HEADER + SLOT_CFG_AT] = new_cfg

    at = HEADER + SLOT_VARIANT_AT
    if at + 1 < len(buf):
        variant = struct.unpack_from("<H", buf, at)[0]
        if variant:  # 0 in class versions that do not carry it
            struct.pack_into("<H", buf, at, variant - old_cfg + new_cfg)

    main, side = (HEADER + o for o in SLOT_BUS_AT)
    old_main = buf[main] if main < len(buf) else 0
    if main < len(buf) and buf[main] in (MONO, STEREO):
        buf[main] = fmt
    # a stereo instance may legitimately keep a mono side chain — only follow when they agreed
    if side < len(buf) and buf[side] in (MONO, STEREO) and buf[side] == old_main:
        buf[side] = fmt
    return bytes(buf)


@dataclass(frozen=True)
class ProjRecord:
    tag: bytes
    ver: int
    owner: int
    key: int
    raw: bytes


def project_records(data: bytes, start: int = BODY_START) -> list[ProjRecord]:
    """Walk a record stream. Accepts any 4-byte tag — a project uses many.

    ``start`` is the 24-byte ProjectData file header by default; a .cst begins at 0.
    """
    out, pos = [], start
    while pos + HEADER <= len(data):
        size = struct.unpack_from("<I", data, pos + SIZE_OFF)[0]
        end = pos + HEADER + size
        if end > len(data):
            break
        out.append(ProjRecord(
            data[pos:pos + 4],
            struct.unpack_from("<H", data, pos + VER_OFF)[0],
            struct.unpack_from("<H", data, pos + OWNER_OFF)[0],
            struct.unpack_from("<H", data, pos + KEY_OFF)[0],
            data[pos:end]))
        pos = end
    return out


def reassemble(data: bytes, records: list[bytes]) -> bytes:
    """``data``'s file header over a new record stream, the total at 0x10 rewritten."""
    body = b"".join(records)
    head = bytearray(data[:BODY_START])
    struct.pack_into("<I", head, TOTAL_AT, len(body))
    return bytes(head) + body


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

    if overrides:
        buf = bytearray(apply_float_overrides(bytes(buf), overrides))
    if label:
        buf = bytearray(relabel_slot(bytes(buf), label))
    if floats:
        body = bytes(buf[HEADER:])
        blocks = find_blocks(body)
        if blocks:
            idx, _tid, n = blocks[0]
            inner = bytearray(body)
            patch_block_floats(inner, idx, 0, list(floats)[:min(limit or len(floats), n)])
            buf[HEADER:] = inner
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
    from .validate import require_valid
    require_valid(result)
    from .keyflags import sync_key_flags
    return sync_key_flags(result)
