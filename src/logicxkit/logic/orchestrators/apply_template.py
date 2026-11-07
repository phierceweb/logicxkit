"""Apply a template's layout to a session: plan the difference, then run it as a chain of the
atomic writers, one op at a time, each validated.

Order: structure (tracks to add, stacks to make, rows to move into stacks, arrange order),
then the track fields (name, colour, hidden), then the channel fields (width, plugin chain,
strip reference, output, input, sends, fader and pan), then the groups — last, so a member's
group events carry the fader the template set — and the session's own bus returns: a
mixer-only aux the legacy song returns a bus through is silenced once a template return
listens to the same bus, or every bus plays twice. A plan lists every op with the rule
that paired the rows; ``apply`` runs them and reports what ran, was skipped or refused.
"""

from __future__ import annotations

import re

from ..services.mixer.binding import channels, input_labels
from ..services.mixer.pairing import extra_rows, forced_by_object, match_quality, pair_rows, pair_tracks
from ..services.arrange.stacks import read_stacks, read_tracks
from .apply_ops import apply
from .ops import KINDS, STRUCTURE, Op  # noqa: F401  (the names callers import from here)
from .template_plan_channels import channel_ops, group_ops, return_ops
from .template_plan_rows import field_ops, order_ops, structure_ops
from .template_stacks import stack_of, stack_targets

# Below this share of rows paired by Environment object id, the two files are not the same
# lineage and the label rule will pair anything with a matching `Audio N`. A session cut from
# the same template scores near 1.0 and an unrelated one near 0, with tracks remade by hand
# costing a few points each, so the floor sits well clear of both.
LINEAGE_FLOOR = 0.5


def plan(template: bytes, session: bytes, *, template_count: int | None, session_count: int | None,
         skip: tuple[str, ...] = (), only: set[int] | None = None,
         forced: dict | None = None, known: dict[int, int] | None = None,
         excluded: set[str] | None = None) -> list[Op]:
    """The ops that take ``session`` to ``template``'s layout, in the order they must run.

    ``only`` restricts the plan to the session rows with those object ids — a stack's
    members, say — and drops the structural ops, which are never about one row. ``known``
    pairs rows an earlier round made (object id -> the template row's key) before any rule
    runs, so a new track that shares its name with an old one is not added twice.
    ``excluded`` names template rows the map leaves out: never paired, never added."""
    ops = _plan(template, session, template_count=template_count, session_count=session_count,
                forced=forced, known=known, excluded=excluded)
    if only is not None:
        ops = [op for op in ops if op.row in only]
    for op in ops:
        if op.kind in skip and op.status == "planned":
            op.status, op.note = "skipped", "skipped by request"
    return ops



def _plan(template: bytes, session: bytes, *, template_count: int | None,
          session_count: int | None, forced: dict | None = None,
          known: dict[int, int] | None = None, excluded: set[str] | None = None) -> list[Op]:
    t_rows, s_rows = read_tracks(template, template_count), read_tracks(session, session_count)
    pairs = pair_rows(t_rows, s_rows, forced=forced, known=known, excluded=excluded)
    t_stacks, s_stacks = read_stacks(template, template_count), read_stacks(session, session_count)
    t_in, s_in = stack_of(t_stacks), stack_of(s_stacks)
    target_of = stack_targets(pairs, t_stacks, s_stacks)
    ops = structure_ops(pairs, t_in, s_in, target_of)
    ops += order_ops(pairs, t_stacks, t_in, s_in, target_of)
    ops += field_ops(pairs)
    channel, reads = channel_ops(template, session, pairs)
    ops += channel
    ops += group_ops(template, session, pairs)
    ops += return_ops(reads, pairs, s_rows, session)
    return ops


def with_template_inputs(template: bytes, session: bytes) -> tuple[bytes, list[Op]]:
    """The session with every mono `Input N` the template routes from, made before anything
    is planned — an insert moves every later channel owner, so it cannot run among ops that
    already name owners."""
    from ..services.arrange.inputs_create import ensure_inputs, mono_inputs
    t_ch = channels(template)
    wanted = [int(m.group(1)) for c in t_ch.values() if (m := re.fullmatch(r"Input (\d+)", c.label))]
    fed = [int(m.group(1)) for label in input_labels(template).values()
           if label and (m := re.fullmatch(r"Input (\d+)", label))]
    need = max(fed, default=0)
    have = mono_inputs(session)
    top = have[-1][0] if have else 0
    if need <= top or not have or need > max(wanted, default=0):
        return session, []
    out = ensure_inputs(session, need)
    return out, [Op("input", "session", f"Input {top + 1}-{need} made", "template routes from them",
                    status="done")]


def apply_template(template: bytes, session: bytes, *, template_count: int | None,
                   session_count: int | None, skip: tuple[str, ...] = (),
                   only: set[int] | None = None,
                   forced: dict[str, str] | None = None,
                   excluded: set[str] | None = None) -> tuple[bytes, list[Op], int]:
    """Plan and apply in one go -> ``(project, ops, rows added)``. Structural ops are run
    first and the field ops planned again on the result, so they see the rows that were
    just made."""
    if forced:
        forced = forced_by_object(forced, read_tracks(session, session_count))
    data, made_inputs = with_template_inputs(template, session)
    count, added, done_structural = session_count, 0, list(made_inputs)
    known: dict[int, int] = {}                  # rows made so far -> the template row they stand for
    for _round in range(4):                     # adds first, then the stacks they belong to, then moves
        ops = plan(template, data, template_count=template_count, session_count=count, skip=skip,
                   only=only, forced=forced, known=known, excluded=excluded)
        structural = [op for op in ops if op.kind in STRUCTURE and op.status == "planned"
                      and not op.args.get("pending")]            # a stack waits for its adds
        if not structural:
            break
        data, new_rows = apply(template, data, structural, session_count=count)
        known.update({op.made: op.args["template_row"] for op in structural if op.made is not None})
        added += new_rows
        count = None if count is None else count + new_rows
        done_structural += structural
        if not any(op.status == "done" for op in structural):
            break
    ops = plan(template, data, template_count=template_count, session_count=count, skip=skip,
               only=only, forced=forced, known=known, excluded=excluded)
    if "return" in skip:                                   # the step that brings a bus up is a return
        returns = []
        for op in ops:
            if op.kind == "output" and op.status == "planned" and op.args.get("use_bus"):
                op.status, op.note = "skipped", f"{op.args['use_bus']} is brought up by a return, and returns are skipped"
    else:
        data, returns = with_bus_returns(data, ops, count)
    if returns:
        ops = plan(template, data, template_count=template_count, session_count=count, skip=skip,
                   only=only, forced=forced, known=known, excluded=excluded)
    leftover = [op for op in ops if op.kind in STRUCTURE]          # what still cannot be done
    rest = [op for op in ops if op.kind not in STRUCTURE]
    data, _ = apply(template, data, rest, session_count=count)
    return data, done_structural + leftover + returns + rest, added


def with_bus_returns(session: bytes, ops: list[Op], count: int | None) -> tuple[bytes, list[Op]]:
    """The session with every bus a planned output op sends to and nothing in it will hear put
    in use, as Logic's own output change leaves one (`bus_return.use_bus`: the lowest free aux
    fed from it, output Output 1-2). It runs before the channel ops are planned for good — a
    fresh aux strip moves the owners above it, so no op may name one yet. With "return" skipped it
    does not run, and the output ops that needed it are skipped, saying so."""
    from ..services.arrange.bus_return import use_bus
    buses = dict.fromkeys(op.args["use_bus"] for op in ops
                          if op.kind == "output" and op.status == "planned" and op.args.get("use_bus"))
    done: list[Op] = []
    for bus in buses:
        owner = next(o for o, c in channels(session).items() if c.label == bus)
        session, made = use_bus(session, owner, count)
        what = f"{made['aux']} fed from it, output Output 1-2" if made["aux"] else "a UUID of its own"
        done.append(Op("return", bus, f"put in use: {what}, as Logic's own does", "template returns it",
                       status="done"))
    return session, done


def session_only(template: bytes, session: bytes, *, template_count: int | None,
                 session_count: int | None, forced: dict[str, str] | None = None,
                 excluded: set[str] | None = None) -> list[dict]:
    """Session rows no template row claims. The plan leaves them as they are; naming them is
    what keeps a stray track from being invisible in it."""
    from ..services.arrange.stacks import read_tracks
    pairs = pair_tracks(template, session, template_count=template_count,
                        session_count=session_count, forced=forced, excluded=excluded)
    return extra_rows(pairs, read_tracks(session, session_count))


def lineage_problem(template: bytes, session: bytes, *, template_count: int | None,
                    session_count: int | None) -> str | None:
    """Why these two files must not be template-applied to each other, or None."""
    pairs = pair_tracks(template, session, template_count=template_count,
                        session_count=session_count)
    quality = match_quality(pairs)
    if quality >= LINEAGE_FLOOR:
        return None
    by_label = [p for p in pairs if p.rule == "label"]
    example = next((f"{p.session['name']!r} would become {p.template['name']!r}"
                    for p in by_label if p.session["name"] != p.template["name"]), None)
    return (f"only {quality:.0%} of rows pair by object id (floor {LINEAGE_FLOOR:.0%}) — these "
            f"two projects are not the same lineage, so pairing falls through to the mixer "
            f"label and would rewrite unrelated tracks"
            + (f"; for example {example}" if example else ""))
