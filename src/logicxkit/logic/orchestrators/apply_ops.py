"""Run planned ops as the chain of atomic writers, one at a time, each validated."""

from __future__ import annotations

from ..services.groups import read_groups
from .ops import Op, _reason


def apply(template: bytes, session: bytes, ops: list[Op], *, session_count: int | None) -> tuple[bytes, int]:
    """Run the planned ops in order -> ``(project, rows added)``. Structural ops change the
    session's rows, so the plan is re-derived after each of them. A writer answers for what
    it changes, not for flaws the session arrived with (`validate.tolerating`)."""
    from ..services.addtrack import add_track
    from ..services.environment import rename_track, set_colour, set_icon
    from ..services.groups import assign, create_group
    from ..services.insert import widen_channels
    from ..services.instout import bind_instrument_output, unbind_instrument_output
    from ..services.levels import set_levels
    from ..services.reorder import move_track
    from ..services.retrack import retrack
    from ..services.sends_write import copy_sends
    from ..services.stack_create import create_stack
    from ..services.stacks import move_out_of_stack, move_to_stack, set_hidden, set_power
    from ..services.transplant import copy_reference, remove_slots, transplant
    from ..services.routing import set_input, set_output
    from ..services.validate import tolerating

    data, added = session, 0
    count = session_count
    made_groups: dict[str, int] = {}          # template group label -> the session group made for it
    with tolerating(session):
        for op in ops:
            if op.status != "planned":
                continue
            a = op.args
            try:
                if op.kind == "add":
                    data, _r = add_track(data, name=a["name"], after=a["after"], kind=a["kind"],
                                         track_count=count, colour=a["colour"], member=a.get("member"))
                    op.made = _r["object_id"]
                    added += 1
                    count = None if count is None else count + 1
                elif op.kind == "stack":
                    data, _r = create_stack(data, name=a["name"], members=a["members"], track_count=count,
                                            colour=a["colour"] if a["colour"] is not None else 16)
                    op.made = _r["object_id"]
                    added += 1
                    count = None if count is None else count + 1
                elif op.kind == "member" and a.get("leave"):
                    data = move_out_of_stack(data, a["track"], track_count=count)
                elif op.kind == "member":
                    data = move_to_stack(data, a["track"], a["stack"], track_count=count)
                elif op.kind == "order":
                    data = move_track(data, a["track"], after=a["after"], track_count=count)
                elif op.kind == "rename":
                    data = rename_track(data, a["track"], a["name"])
                elif op.kind == "colour":
                    data = set_colour(data, a["track"], a["colour"])
                elif op.kind == "icon":
                    data = set_icon(data, a["track"], a["icon"])
                elif op.kind == "hidden":
                    data = set_hidden(data, a["track"], a["hidden"], track_count=count)
                elif op.kind == "power":
                    data = set_power(data, a["track"], a["on"], track_count=count)
                elif op.kind == "return":
                    if a["slots"]:
                        data, _k = remove_slots(data, a["owner"])
                    data = unbind_instrument_output(data, a["owner"])          # clears +94/+95 either way
                    if not a.get("unbind"):
                        data = set_input(data, a["owner"], None)
                elif op.kind == "group" and a.get("leave"):
                    data = assign(data, a["track"], 0)
                elif op.kind == "group":
                    number = made_groups.get(a["label"]) or next(
                        (g.number for g in read_groups(data) if g.label == a["label"]), None)
                    if number is None:
                        data, made = create_group(data, name=a["name"], flags=a["flags"])
                        number = made_groups[a["label"]] = made.number
                    data = assign(data, a["track"], number)
                elif op.kind == "width":
                    data, _c = widen_channels(data, {a["owner"]: a["fmt"]})
                elif op.kind == "chains" and a.get("remove"):
                    data, _k = remove_slots(data, a["dst_owner"])
                elif op.kind == "chains":
                    data, _r = transplant(template, data, src_owner=a["src_owner"], dst_owner=a["dst_owner"])
                elif op.kind == "refs" and a.get("copy"):
                    data = copy_reference(template, data, src_owner=a["src_owner"], dst_owner=a["dst_owner"])
                elif op.kind == "refs":
                    target = a["new"] if a["category"] is None else {"name": a["new"], "category": a["category"]}
                    data, _r = retrack(data, {a["old"]: target}, a["category"] or "")
                elif op.kind == "output":
                    data = set_output(data, a["owner"], a["dest"])
                elif op.kind == "input":
                    data = set_input(data, a["owner"], a["dest"])
                elif op.kind == "instout":
                    data = bind_instrument_output(data, a["owner"], pattern=a["pattern"], instrument=a["instrument"])
                elif op.kind == "sends":
                    data, _r = copy_sends(template, data, src_owner=a["src_owner"], dst_owner=a["dst_owner"])
                elif op.kind == "levels":
                    data, _c = set_levels(data, {a["owner"]: {"fader_fixed": a["fader_fixed"], "pan": a["pan"]}})
                op.status = "done"
            except ValueError as e:
                op.status, op.note = "failed", _reason(e)
    return data, added
