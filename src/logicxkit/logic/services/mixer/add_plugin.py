"""One donor slot into a channel at a chosen slot, the slots from there moved down a key.

A slot is its mixer position, from 1 with empty slots counted: key minus the slot base, plus
one — payload +6 holds the index, and automation names the insert by the same number. Keys run
up to the channel's `.cst` reference key (`transplant`'s capacity rule). A moved slot keeps
every other byte, and its Smart Control mappings and automation lanes move with it. An
instrument channel's slot 1 is its instrument, which keeps the width it was saved at: the channel's
input byte follows it, and its width too when no effect comes after. The donor goes through
`insert._stamp`: owner, key, index, width for Logic's own effects, an instance id at measured
offsets, bypass.
"""

from __future__ import annotations

import struct

from .binding import channels
from .channel_width import with_channel_io
from .insert import _stamp, insert_slots
from .mixer import CHANNEL_TAG, channel_formats
from .slot_identity import slot_header
from .slot_width import MONO, STEREO, slot_format
from .slots import SLOT_INDEX_AT, slot_index_base
from ..stream.stream import HEADER, VER_OFF, project_records, reassemble
from ..stream.keyflags import sync_key_flags
from ..stream.recbuild import with_key
from .sidechain import SideChain, with_side_chain
from .slots import SHOWN_AT, archive_index, is_plugin_slot, property_key_base
from .smart_controls import shift_mapping_slots
from .insert_lanes import move_lanes
from .plugins import is_instrument_plugin
from .transplant import channel_slots, is_audio, is_instrument_channel, refuse_width, slot_class_version
from ..stream.validate import require_full_walk, require_valid


def add_plugin(data: bytes, owner: int, donor: bytes, *, at: int | None = None,
               id_offsets: tuple[int, ...] = (), type_id: int | None = None,
               bypass: bool = False, force: bool = False,
               settings: dict[str, float | str] | None = None, table=None,
               side_chain: SideChain | None = None) -> tuple[bytes, dict]:
    """``donor`` onto ``owner`` at 1-based slot ``at`` (the end without) -> ``(project, report)``.

    ``settings`` names parameters to dial on the way in, by ``table`` (`plugin_params.Table`);
    ``side_chain`` is the source the slot listens to (`sidechain.resolve`), none without — a
    donor's own names a channel of the project it came from. Refuses a donor of another class
    version and, on an audio channel, a third-party donor of the other width; ``force`` writes
    anyway.
    """
    require_full_walk(data)
    if settings:
        from .plugin_params import set_by_name
        if table is None:
            raise ValueError("settings need the plug-in's parameter table")
        donor = donor[:HEADER] + set_by_name(table, donor[HEADER:], settings)
    first, base = slot_index_base(data), property_key_base(data)
    existing = channel_slots(data, owner)
    key = _key_for(data, owner, donor, existing, at, first)
    position = key - first + 1
    width = channel_formats(data).get(owner)
    own = slot_format(donor)
    if is_instrument_plugin(donor[HEADER:]) and own in (MONO, STEREO):
        # as Logic's own load from the slot menu: the channel's input is the instrument's, and
        # with no effect after it so is its width; a chain keeps its own
        alone = not any(r.key != key for r in existing)
        data = with_channel_io(data, owner, stereo_input=own == STEREO, output=own if alone else None)
        existing, width = channel_slots(data, owner), own if alone else None
    # an empty slot takes the plug-in as it is; an occupied one moves down with everything after it
    moved = [(r.key, r.key + 1) for r in existing if r.key >= key] if any(r.key == key for r in existing) else []
    if not force:
        _refuse(data, owner, donor, width=width)
    # Logic keeps two keys between the longest chain and the reference: a chain growing into
    # them pushes the reference, the records under it and the archives above it up, project-wide
    last = max([key] + [new for _old, new in moved])
    grown = max(0, last + headroom(data, first, base) - base)
    if grown:
        data = grow_range(data, base, grown, first)
        base += grown
    data = show_slots(data, last - first + 2)
    report = {"key": key, "position": position, "moved": moved, "width": width, "grown": grown,
              "ids": "stamped" if id_offsets else "verbatim", "slots": len(existing) + 1,
              "side_chain": side_chain.label if side_chain else None, "lanes_moved": 0}
    donor = with_side_chain(donor, side_chain)
    if not existing:
        entry = (donor, key, None, None, None, id_offsets, type_id, bypass, None)
        return insert_slots(data, {owner: [entry]}), report

    stamped = _stamp(donor, owner, key, None, None, f"{owner}:{key}", fmt=width,
                     id_offsets=id_offsets, type_id=type_id, bypass=bypass, index_base=first)
    shifted = dict(moved)
    run = [raw for _k, raw in sorted([(shifted.get(r.key, r.key), _rekey(r.raw, shifted[r.key], first)
                                        if r.key in shifted else r.raw) for r in existing] + [(key, stamped)])]
    records = project_records(data)
    old = {i for i, r in enumerate(records) if r.owner == owner and is_plugin_slot(r, base, first)}
    kept = []
    for i, r in enumerate(records):
        if i in old:
            continue
        if moved and r.owner == owner and archive_index(r.raw) == 1:
            kept.append(shift_mapping_slots(r.raw, from_index=key - first, by=1))
            continue
        kept.append(r.raw)
    start = min(old)
    out = sync_key_flags(reassemble(data, kept[:start] + run + kept[start:]))
    if moved:
        out, counts = move_lanes(out, owner, {k - first + 1: new - first + 1 for k, new in moved})
        report["lanes_moved"] = counts["moved"]
    require_valid(out)
    return out, report


def _key_for(data: bytes, owner: int, donor: bytes, existing, at: int | None, first: int) -> int:
    """The key the donor goes to: slot ``at``, else after the last slot. An instrument channel's
    slot 1 is its instrument's, and an instrument goes nowhere else."""
    inst_channel = is_instrument_channel(data, owner)
    instrument = is_instrument_plugin(donor[HEADER:])
    head = slot_header(donor[HEADER:])
    if head is not None and head.midi:
        raise ValueError("a MIDI effect goes into a channel's MIDI FX slots, which are not audio effect slots; "
                         "this command writes instruments and audio effects")
    if instrument and not inst_channel:
        raise ValueError("an instrument goes into an instrument channel's slot 1, not into an audio effect slot")
    if instrument:
        if at not in (None, 1):
            raise ValueError(f"an instrument goes into slot 1 of an instrument channel, not slot {at}")
        if any(r.key == first for r in existing):
            raise ValueError("slot 1 already holds this channel's instrument; replace-plugin --at 1 swaps it")
        return first
    if at is not None:
        if at < 1:
            raise ValueError(f"slot {at} does not exist; slots count from 1")
        if at == 1 and inst_channel:
            raise ValueError("slot 1 of an instrument channel is its instrument; its first audio effect slot is 2")
        return first + at - 1
    key = existing[-1].key + 1 if existing else first
    return max(key, first + 1) if inst_channel else key


def headroom(data: bytes, first: int, base: int) -> int:
    """Keys Logic keeps between the project's highest slot key and the reference: measured
    from the input, since Logic re-lays a project out to its own figure on load (3 on a
    blank-born project, 6 on the owner's sessions) and drops what lands past the channel
    records' flag words. Never under 3."""
    keys = [r.key for r in project_records(data) if is_plugin_slot(r, base, first)]
    return max(3, base - max(keys)) if keys else 3


def grow_range(data: bytes, base: int, by: int, index_base: int) -> bytes:
    """Every channel satellite from two keys under the reference at ``base`` moved up ``by``
    keys, on every channel: the records under the reference, the reference, the archives. A
    plug-in slot there stays: Logic's own save of an instrument with one effect puts the effect
    two keys under the reference (`instrument-es2-over-chromaglow-logic`)."""
    owners = set(channels(data))
    out = [with_key(r.raw, r.key + by) if r.tag == b"UCuA" and r.owner in owners and r.key >= base - 2
           and not is_plugin_slot(r, base, index_base) else r.raw for r in project_records(data)]
    return reassemble(data, out)


def shown_slots(data: bytes) -> int:
    """The highest shown-slot count any channel record carries (0 in a project without one)."""
    owners = set(channels(data))
    return max((struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in project_records(data)
                if r.tag == CHANNEL_TAG and r.owner in owners and len(r.raw) - HEADER >= SHOWN_AT + 2), default=0)


def show_slots(data: bytes, shown: int) -> bytes:
    """Every channel record's `+30` raised to ``shown``, the insert slots the mixer shows —
    the longest chain plus one empty slot, one value for the project. A higher count is left:
    Logic recomputes it on save."""
    owners = set(channels(data))
    out = []
    for r in project_records(data):
        raw = r.raw
        if r.tag == CHANNEL_TAG and r.owner in owners and len(raw) - HEADER >= SHOWN_AT + 2 \
                and struct.unpack_from("<H", raw, HEADER + SHOWN_AT)[0] < shown:
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + SHOWN_AT, shown)
            raw = bytes(buf)
        out.append(raw)
    return reassemble(data, out)


def _refuse(data: bytes, owner: int, donor: bytes, *, width: int | None) -> None:
    version, donor_version = slot_class_version(data), struct.unpack_from("<H", donor, VER_OFF)[0]
    if version is not None and donor_version != version:
        raise ValueError(
            f"the donor is v{donor_version} and this project writes v{version}: a record cannot be "
            "legalised across class versions. Pass --force to write anyway.")
    if is_audio(data, owner):
        refuse_width([donor], width)


def _rekey(raw: bytes, key: int, first: int) -> bytes:
    buf = bytearray(with_key(raw, key))
    buf[HEADER + SLOT_INDEX_AT] = key - first
    return bytes(buf)
