"""Describe what a chain plan does to a project, before it does it.

`insert_slots` replaces any existing slot at a key it writes, so on an already-dialled song a
run discards that work. Naming it is a separate concern from building the plan, and lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chains import channel_references
from .insert import HEADER

# Native plugin type ids, for naming a slot whose record carries no readable name string.
# The verbs are the config's own donor types (the spec's `donors` map).
PLUGIN_NAMES = {236: "Channel EQ", 154: "Compressor", 157: "Enveloper", 199: "Limiter",
                183: "Gain", 147: "Echo", 287: "ChromaVerb", 150: "SilverVerb",
                166: "EnVerb", 231: "Space Designer"}


def _slot_name(payload: bytes, type_id: int | None = None) -> str:
    """What to call a plugin slot when reporting what a chain replaces.

    The name string first — it is the only thing a third-party slot carries — then the native
    type id, then the bare id, so a report never says "?" about work someone is about to lose.
    """
    from .._binary import find_blocks
    from .project import _plugin_name

    name = _plugin_name(payload)
    if name:
        return name
    if type_id is None:
        blocks = find_blocks(payload)
        type_id = blocks[0][1] if blocks else None
    return PLUGIN_NAMES.get(type_id) or (f"type {type_id}" if type_id else "unnamed plugin")


@dataclass(frozen=True)
class ChainChange:
    """What applying a chain plan does to one channel."""
    owner: int
    ref: str
    before: list[str]        # plugin names already on the channel, in slot-key order
    after: list[str]         # plugin names the plan places, in slot-key order
    replaced: list[str]      # names at keys the plan overwrites — this is the work being lost

    @property
    def reordered(self) -> bool:
        """The same plugins, in a different order — a silent rearrangement of a dialled chain."""
        return bool(self.before) and sorted(self.before) == sorted(self.after) \
            and self.before != self.after

    def line(self) -> str:
        if not self.before:
            return f"{self.ref:26s} + {' -> '.join(self.after)}"
        verb = "REORDER" if self.reordered else "REPLACE"
        return (f"{self.ref:26s} {verb}  {' -> '.join(self.before)}"
                f"  ==>  {' -> '.join(self.after)}")


def chain_changes(data: bytes, plan: dict) -> list[ChainChange]:
    """Per channel, the chain that is there and the chain the plan would leave.

    `insert_slots` replaces any existing slot at a key it writes, so on an already-dialled song
    a run discards that work. Nothing said so before it happened.
    """
    from .transplant import channel_slots

    refs = channel_references(data)
    out = []
    for owner, slots in sorted(plan.items()):
        existing = {r.key: _slot_name(r.raw[HEADER:]) for r in channel_slots(data, owner)}
        placed = {e[1]: _slot_name(e[0][HEADER:], e[6]) for e in slots}
        survives = {k: v for k, v in existing.items() if k not in placed}
        out.append(ChainChange(
            owner=owner,
            ref=refs.get(owner, f"owner {owner}"),
            before=[existing[k] for k in sorted(existing)],
            after=[v for _k, v in sorted({**survives, **placed}.items())],
            replaced=[existing[k] for k in sorted(existing) if k in placed],
        ))
    return out
