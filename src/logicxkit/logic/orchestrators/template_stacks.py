"""Which session stack a template stack means, for `apply_template`: the one whose header row
pairs with the template's header, else the one unclaimed session stack of its name. A header
paired with a row that is no stack, or two stacks of the name, means none."""

from __future__ import annotations

from ..services.arrange.stacks import Stack
from ..services.arrange.trackname import stacks_named


def stack_of(stacks: list[Stack]) -> dict[int, Stack]:
    """row key -> the stack holding that row directly."""
    return {key: s for s in stacks for key, _name in s.members}


def stack_targets(pairs, t_stacks: list[Stack], s_stacks: list[Stack]) -> dict[int, Stack | str]:
    """template stack object id -> its session stack, or why there is none."""
    by_object = {s.object_id: s for s in s_stacks}
    headers = {t.object_id for t in t_stacks}
    paired = {p.template["object_id"]: p.session for p in pairs
              if p.session is not None and p.template["object_id"] in headers}
    claimed = {r["object_id"] for r in paired.values()}
    out: dict[int, Stack | str] = {}
    for t in t_stacks:
        row = paired.get(t.object_id)
        if row is not None:
            out[t.object_id] = by_object.get(row["object_id"]) or \
                f"its header pairs with {row['name']} ({row['label']}), which is not a stack"
            continue
        named = [s for s in stacks_named(s_stacks, t.name) if s.object_id not in claimed]
        if len(named) == 1:
            out[t.object_id] = named[0]
        elif named:
            out[t.object_id] = (f"{len(named)} session stacks are named {t.name!r} ("
                                f"{', '.join(s.strip for s in named)}) and none pairs with the template's")
        else:
            out[t.object_id] = "the stack does not exist yet"
    return out


def same_stack(a: Stack | None, b: Stack | str | None) -> bool:
    return isinstance(b, Stack) and a is not None and a.object_id == b.object_id
