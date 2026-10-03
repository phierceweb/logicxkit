"""A folder stack made a summing stack, as Logic 12.4's Track > Convert Folder Stack to Summing
Stack leaves the file."""

from __future__ import annotations

import struct

from ..mixer.binding import IN_USE_AT, bound_channels, set_stack_index
from ..mixer.mixer import is_mixer_record
from ..stream.recbuild import rec
from ..stream.sequence import EVENT_LEN, QESM_OBJECT_AT, SEQ_END_TAG, sequences
from ..stream.stream import HEADER, NO_KEY, project_records, reassemble
from ..stream.validate import require_valid
from .environment import NAMED_BIT, STATE_AT, object_id_of, object_record, rename_object
from .stack_moves import flatten_stack
from .stacks import SUMMING, read_stacks, span_end
from .tracklist import MEMBER_AT, arrange_run, row_object

CARRIED_LANE = "Volume"


def _master_state(data: bytes, stack, track_count: int | None) -> list[str]:
    """What a folder's main strip carries that no measured convert shows the fate of: a lane
    other than Volume on its track, an insert."""
    from ..mixer.plugins import slot_payloads
    from ..regions.automation import read_automation
    out = [f"a {ln.parameter} lane" for a in read_automation(data, track_count) if a.track_object == stack.object_id
           for ln in a.lanes if not ln.region and ln.parameter != CARRIED_LANE]
    out += [f"a {ref.name} insert" for ref, _p in slot_payloads(data) if ref.channel == stack.strip]
    return out


def _level_left(data: bytes, stack) -> float | None:
    """The folder's fader in dB when off unity: Logic's convert leaves it on the `Sub` strip it
    takes out of use and puts the aux at unity (`stack-convert-level-after-logic`)."""
    from ..mixer.levels import read_levels
    level = read_levels(data)[stack.owner]["fader_db"]
    if level is None:
        return float("-inf")
    return level if abs(level) >= 0.05 else None


def _carry_lanes(data: bytes, source: int, target: int) -> bytes:
    """``source``'s automation points moved onto ``target``'s folder, ``source``'s left with its
    closing event: Logic's convert moved the folder's Volume lane byte for byte
    (`stack-convert-lane-after-logic`)."""
    from ..regions.automation import FOLDER_NAME, named
    records = project_records(data)
    ends = {}
    for t in sequences(records):
        q = records[t.start].raw[HEADER:]
        if named(q, FOLDER_NAME) and len(q) >= QESM_OBJECT_AT + 2:
            ends[struct.unpack_from("<H", q, QESM_OBJECT_AT)[0]] = t.end
    if source not in ends or target not in ends:
        raise ValueError(f"no automation folder for object {source if source not in ends else target}")
    out = [r.raw for r in records]
    points = out[ends[source]][HEADER:]
    out[ends[target]] = rec(SEQ_END_TAG, out[ends[target]], points)
    out[ends[source]] = rec(SEQ_END_TAG, out[ends[source]], points[-EVENT_LEN:])
    return reassemble(data, out)


def convert_to_summing(data: bytes, stack_object: int, track_count: int | None = None) -> tuple[bytes, dict]:
    """The folder flattened, a summing stack made over its direct members (`stack_summing`: the
    lowest free `Aux` fed from the lowest free bus), the folder's header object removed while its
    flat row and table entry stay as Logic left them, its `Sub` strip taken out of use, the
    members' channels at stack index 0 inside another folder too, its Volume lane moved onto the
    new header, its level left on the `Sub` strip (`stack-converted-to-summing-logic`,
    `nest-convert-*-after-logic`, `stack-convert-lane-after-logic`,
    `stack-convert-level-after-logic`). The header keeps
    the folder's name when it was the user's; an unnamed folder's is `Sum N`, N the aux's number,
    unnamed as Logic's own `Sum 1` on `Aux 1` is. A folder whose main strip carries what no save
    shows the fate of (`_master_state`) is refused."""
    from .stack_summing import create_summing_stack
    records = project_records(data)
    stacks = {s.object_id: s for s in read_stacks(data, track_count)}
    if stack_object not in stacks:
        raise ValueError(f"object {stack_object} is not a stack")
    stack = stacks[stack_object]
    if stack.kind == SUMMING:
        raise ValueError(f"{stack.name!r} is already a summing stack")
    if not stack.members:
        raise ValueError("no track sits in it, so there is nothing to convert")
    carried = _master_state(data, stack, track_count)
    if carried:
        raise ValueError(f"its main strip carries {', '.join(carried)}; Logic's convert of such a folder "
                         "is not measured, so nothing is written")
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    depths = [records[i].raw[HEADER + MEMBER_AT] for i in run]
    start = order.index(stack_object)
    members = [order[k] for k in range(start + 1, span_end(depths, start)) if depths[k] == stack.depth + 1]
    named = bool(object_record(records, stack_object)[HEADER + STATE_AT] & NAMED_BIT)
    sub_owner = stack.owner

    flat = flatten_stack(data, stack_object, track_count)
    count = None if track_count is None else track_count - 1
    out, report = create_summing_stack(flat, name=stack.name if named else "Sum", members=members, track_count=count)
    out = _carry_lanes(out, stack_object, report["object_id"])
    name = stack.name if named else f"Sum {report['label'].split()[-1]}"
    header_owner = bound_channels(out)[report["object_id"]]
    member_owners = {bound_channels(out)[m] for m in members}
    rows = []
    for r in project_records(out):
        raw = r.raw
        oid = object_id_of(r)
        if oid == stack_object:
            continue                                      # the folder's header object
        if oid == report["object_id"] and not named:
            body = bytearray(rename_object(raw, name))
            body[HEADER + STATE_AT] &= ~NAMED_BIT
            raw = bytes(body)
        elif is_mixer_record(r) and r.owner in member_owners:
            raw = set_stack_index(raw, 0)
        elif is_mixer_record(r) and r.owner == sub_owner and r.key == NO_KEY:
            body = bytearray(raw)
            body[HEADER + IN_USE_AT] = body[HEADER + IN_USE_AT + 1] = 0
            raw = bytes(body)
        rows.append(raw)
    result = reassemble(out, rows)
    require_valid(result)
    return result, {**report, "name": name, "sub": stack.strip, "header_owner": header_owner,
                    "level_left": _level_left(data, stack)}
