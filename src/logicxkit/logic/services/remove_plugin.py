"""One slot out of a channel, the slots after it moved up a key, and what named it by slot — its
Smart Control mappings and automation lanes — dropped, the later ones moved with their plug-ins.
An instrument channel's slot 1 stays its instrument's: removing the instrument moves nothing up.
The key range is left as it is (Logic re-lays it out on save) and so is the shown-slot count.
"""

from __future__ import annotations

from .add_plugin import _rekey
from .insert import project_records, reassemble, slot_index_base
from .insert_lanes import move_lanes
from .keyflags import sync_key_flags
from .slots import archive_index, is_plugin_slot, property_key_base
from .smart_controls import drop_mapping_slot, shift_mapping_slots
from .transplant import channel_slots, is_instrument_channel
from .validate import require_full_walk, require_valid


def remove_plugin(data: bytes, owner: int, at: int) -> tuple[bytes, dict]:
    """The channel without the plug-in in slot ``at`` (from 1, empty slots counted) ->
    ``(project, report)``; the report counts the automation points dropped with it."""
    require_full_walk(data)
    first, base = slot_index_base(data), property_key_base(data)
    existing = channel_slots(data, owner)
    gone = next((r for r in existing if r.key == first + at - 1), None) if at >= 1 else None
    if gone is None:
        held = ", ".join(str(r.key - first + 1) for r in existing) or "none"
        raise ValueError(f"slot {at} holds no plug-in; the channel's plug-ins are in slot(s) {held}")
    close_up = not (at == 1 and is_instrument_channel(data, owner))
    moved = [(r.key, r.key - 1) for r in existing if r.key > gone.key] if close_up else []
    shifted = dict(moved)
    run = [_rekey(r.raw, shifted[r.key], first) if r.key in shifted else r.raw for r in existing if r is not gone]
    records = project_records(data)
    old = {i for i, r in enumerate(records) if r.owner == owner and is_plugin_slot(r, base, first)}
    kept = []
    for i, r in enumerate(records):
        if i in old:
            continue
        raw = r.raw
        if r.owner == owner and archive_index(raw) == 1:
            raw = drop_mapping_slot(raw, gone.key - first)
            if close_up:
                raw = shift_mapping_slots(raw, from_index=gone.key - first + 1, by=-1)
        kept.append(raw)
    start = min(old)
    out = sync_key_flags(reassemble(data, kept[:start] + run + kept[start:]))
    moves = {at: None} | {k - first + 1: new - first + 1 for k, new in moved}
    out, counts = move_lanes(out, owner, moves)
    require_valid(out)
    return out, {"key": gone.key, "position": at, "moved": moved, "slots": len(existing) - 1,
                 "lanes_dropped": counts["dropped"], "lanes_moved": counts["moved"]}
