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

from ..services.mixer.binding import channels, input_labels, output_labels
from ..services.mixer.chains import channel_references
from ..services.arrange.groups import read_groups
from ..services.mixer.instout import read_instrument_outputs
from ..services.mixer.mixer import channel_formats
from ..services.stream.stream import HEADER
from ..services.mixer.levels import FIXED_ONE, read_levels
from ..services.mixer.pairing import extra_rows, forced_by_object, match_quality, pair_rows, pair_tracks
from ..services.arrange.retrack import cst_references
from ..services.mixer.sends import read_sends
from ..services.arrange.stacks import Stack, read_stacks, read_tracks
from ..services.mixer.transplant import channel_slots, slot_class_version
from .apply_ops import apply
from .ops import KINDS, STRUCTURE, Op  # noqa: F401  (the names callers import from here)
from .template_stacks import same_stack, stack_of, stack_targets

# Below this share of rows paired by Environment object id, the two files are not the same
# lineage and the label rule will pair anything with a matching `Audio N`. A session cut from
# the same template scores near 1.0 and an unrelated one near 0, with tracks remade by hand
# costing a few points each, so the floor sits well clear of both.
LINEAGE_FLOOR = 0.5

def _row_name(r: dict) -> str:
    return f"{r['name']} ({r['label']})" if r["label"] else str(r["name"])


def _kind_of(row: dict) -> str | None:
    label = row["label"] or ""
    if label.startswith("Audio "):
        return "audio"
    if label.startswith("Inst "):
        return "instrument"
    if label.startswith("Aux "):                          # incl. the kind-0 input-less auxes
        return "aux"
    return None


def _id(stack: Stack | None) -> int | None:
    return None if stack is None else stack.object_id


def _name(stack: Stack | None, other: Stack | str | None = None) -> str:
    """A stack's name, with its strip when ``other`` shares the name."""
    if stack is None:
        return "?"
    return f"{stack.name} ({stack.strip})" if isinstance(other, Stack) and other.name == stack.name else stack.name


def _by_label(chans) -> dict[str, int]:
    """Routing targets by mixer label — buses and inputs are never marked in use, so all
    channels count."""
    return {c.label: o for o, c in chans.items()}


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
    ops: list[Op] = []

    # --- structure
    previous = None                      # the session row the last paired template row landed on
    last_add = None                      # the add op planned directly above, if any
    for p in pairs:
        t = p.template
        if p.session is None:
            kind = _kind_of(t)
            if t["grouping"] and (t["label"] or "").startswith("Sub "):
                wanted = [q.session for q in pairs if q.session is not None
                          and _id(t_in.get(q.template["key"])) == t["object_id"]]
                for m in wanted:
                    for _level in range(m["depth"]):      # inside another stack: out first, one move per level
                        ops.append(Op("member", _row_name(m), f"leave stack {_name(s_in.get(m['key']))}",
                                      p.rule, args={"track": m["object_id"], "leave": True}, row=m["object_id"]))
                op = Op("stack", _row_name(t), f"make a stack of {len(wanted)} track(s)", p.rule,
                        args={"members": [m["object_id"] for m in wanted], "name": t["name"],
                              "colour": t["colour"], "template_row": t["key"], "stack_id": t["object_id"]})
            elif kind is None:
                op = Op("add", _row_name(t), "add", p.rule, status="refused",
                        note="only audio, instrument and aux tracks can be added")
            elif previous is None:
                op = Op("add", _row_name(t), f"add {kind} track", p.rule, status="refused",
                        note="no paired row above it to place it after")
            else:
                inside = t_in.get(t["key"])
                anchor = last_add.args["name"] if last_add else previous["name"]
                op = Op("add", _row_name(t), f"add {kind} track after {anchor}", p.rule,
                        args={"kind": kind, "name": t["name"], "after": previous["object_id"],
                              "after_op": last_add, "colour": t["colour"], "template_row": t["key"],
                              "member": inside is not None and isinstance(target_of[inside.object_id], Stack)})
                last_add = op
            ops.append(op)
            continue
        s = p.session
        want, have = t_in.get(t["key"]), s_in.get(s["key"])
        target = target_of[want.object_id] if want is not None else None
        if want is None and have is not None:
            ops.append(Op("member", _row_name(s), f"leave stack {have.name}", p.rule,
                          args={"track": s["object_id"], "leave": True}, row=s["object_id"]))
        elif want is not None and not same_stack(have, target):
            found = isinstance(target, Stack)
            to = _name(target, have) if found else want.name
            desc = f"move into stack {to}" if have is None else f"move from {_name(have, target)} to {to}"
            op = Op("member", _row_name(s), desc, p.rule,
                    args={"track": s["object_id"], "stack": target.object_id if found else None,
                          "stack_name": want.name, "stack_id": want.object_id}, row=s["object_id"])
            if not found:
                op.status, op.note = "refused", target
            ops.append(op)
        previous, last_add = s, None

    for op in ops:                       # a stack of tracks added above it is made once they exist
        if op.kind == "stack":
            pending = [a for a in ops if a.kind == "add" and a.status == "planned"
                       and _id(t_in.get(a.args["template_row"])) == op.args["stack_id"]]
            op.detail = f"make a stack of {len(op.args['members']) + len(pending)} track(s)"
            if pending:
                op.args["pending"], op.note = pending, f"{len(pending)} of them added above"
            elif not op.args["members"]:
                op.status, op.note = "refused", "none of its members is in the session"
    made = {(op.args["stack_id"], m) for op in ops if op.kind == "stack" and op.status == "planned"
            for m in op.args["members"]}
    ops = [op for op in ops if not (op.kind == "member" and op.args.get("stack") is None
                                    and (op.args.get("stack_id"), op.args["track"]) in made)]

    # --- arrange order, per parent, among paired rows that already sit under that parent
    for parent in [None, *t_stacks]:
        s_parent = None if parent is None else target_of[parent.object_id]
        if parent is not None and not isinstance(s_parent, Stack):
            continue
        wanted = [p for p in pairs if p.session is not None
                  and _id(t_in.get(p.template["key"])) == _id(parent)
                  and _id(s_in.get(p.session["key"])) == _id(s_parent)
                  and not p.template["grouping"]]
        session_order = sorted(wanted, key=lambda p: p.session["key"])
        if [p.session["key"] for p in wanted] != [p.session["key"] for p in session_order]:
            for prev, cur in zip(wanted, wanted[1:], strict=False):
                ops.append(Op("order", _row_name(cur.session), f"after {prev.session['name']}", cur.rule,
                              args={"track": cur.session["object_id"], "after": prev.session["object_id"]},
                              row=cur.session["object_id"]))

    # --- track fields
    for p in pairs:
        if p.session is None:
            continue
        t, s = p.template, p.session
        if t["name"] != s["name"]:
            ops.append(Op("rename", _row_name(s), f"-> {t['name']!r}", p.rule,
                          args={"track": s["object_id"], "name": t["name"]}, row=s["object_id"]))
        if t["colour"] != s["colour"]:
            ops.append(Op("colour", _row_name(s), f"{s['colour']} -> {t['colour']}", p.rule,
                          args={"track": s["object_id"], "colour": t["colour"]}, row=s["object_id"]))
        if t["icon"] is not None and s["icon"] is not None and t["icon"] != s["icon"]:
            ops.append(Op("icon", _row_name(s), f"{s['icon']} -> {t['icon']}", p.rule,
                          args={"track": s["object_id"], "icon": t["icon"]}, row=s["object_id"]))
        if t["hidden"] != s["hidden"]:
            ops.append(Op("hidden", _row_name(s), "hide" if t["hidden"] else "show", p.rule,
                          args={"track": s["object_id"], "hidden": t["hidden"]}, row=s["object_id"]))
        if t["on"] != s["on"]:
            ops.append(Op("power", _row_name(s), "switch on" if t["on"] else "switch off", p.rule,
                          args={"track": s["object_id"], "on": t["on"]}, row=s["object_id"]))

    # --- channel fields, on the bound channels of paired rows
    t_ch, s_ch = channels(template), channels(session)
    s_labels = _by_label(s_ch)
    t_fmt, s_fmt = channel_formats(template), channel_formats(session)
    t_ref, s_ref = channel_references(template), channel_references(session)
    t_cat = {r.name: r.category for r in cst_references(template)}
    t_out, s_out = output_labels(template), output_labels(session)
    t_inp, s_inp = input_labels(template), input_labels(session)
    slot_class = slot_class_version(session)
    t_sends, s_sends = read_sends(template), read_sends(session)
    t_lv, s_lv = read_levels(template), read_levels(session)
    t_inst, s_inst = read_instrument_outputs(template), read_instrument_outputs(session)
    inst_rows = {p.template["owner"]: p.session["owner"] for p in pairs          # template Inst owner -> session owner
                 if p.session is not None and p.template["owner"] is not None and p.session["owner"] is not None}
    # buses something takes as input: the template's, and the session's once this pass's input ops run
    t_heard = {label for label in t_inp.values() if label}
    s_heard = {label for label in s_inp.values() if label} | {t_inp[to] for to in inst_rows if t_inp.get(to)}
    for p in pairs:
        if p.session is None or p.template["owner"] is None or p.session["owner"] is None:
            continue
        to, so = p.template["owner"], p.session["owner"]
        name = _row_name(p.session)
        first = len(ops)
        if to in t_fmt and so in s_fmt and t_fmt[to] != s_fmt[so]:
            ops.append(Op("width", name, f"{'mono' if s_fmt[so] == 1 else 'stereo'} -> "
                          f"{'mono' if t_fmt[to] == 1 else 'stereo'}", p.rule,
                          args={"owner": so, "fmt": t_fmt[to]}))
        t_records = channel_slots(template, to)
        t_slots = [r.raw[HEADER:] for r in t_records]
        s_slots = [r.raw[HEADER:] for r in channel_slots(session, so)]
        if t_slots != s_slots:
            if t_slots:
                op = Op("chains", name,
                        f"{len(s_slots)} slot(s) -> {len(t_slots)} from the template",
                        p.rule, args={"src_owner": to, "dst_owner": so})
                classes = sorted({r.ver for r in t_records})
                if slot_class is not None and classes != [slot_class]:
                    op.status = "refused"
                    op.note = (f"the template's slots are class {'/'.join(map(str, classes))} "
                               f"and this project writes class {slot_class}: save the template "
                               "in the current Logic")
                ops.append(op)
            else:
                ops.append(Op("chains", name, f"remove {len(s_slots)} slot(s); the template has none",
                              p.rule, args={"dst_owner": so, "remove": True}))
        if not t_ref.get(to) and s_ref.get(so):
            ops.append(Op("refs", name, f"carries {s_ref[so]}; the template has none", p.rule, status="refused",
                          note="clearing a strip reference is not written"))
        elif t_ref.get(to) and t_ref.get(to) != s_ref.get(so):
            if s_ref.get(so) is None:
                ops.append(Op("refs", name, f"set reference {t_ref[to]}", p.rule,
                              args={"copy": True, "src_owner": to, "dst_owner": so}))
            else:
                # per channel: two session channels sharing a name may part ways here
                ops.append(Op("refs", name, f"{s_ref[so]} -> {t_ref[to]}", p.rule,
                              args={"owner": so, "old": s_ref[so], "new": t_ref[to], "category": t_cat.get(t_ref[to])}))
        for kind, t_map, s_map in (("output", t_out, s_out), ("input", t_inp, s_inp)):
            if to not in t_map:                                     # not read is not unrouted
                continue
            dest_label, s_label = t_map[to], s_map.get(so)
            if dest_label is None:
                if kind == "input" and s_label is not None:     # fed by nothing, as the template's
                    ops.append(Op(kind, name, "-> no input", p.rule, args={"owner": so, "dest": None}))
                continue
            if s_label == dest_label:
                continue
            op = Op(kind, name, f"-> {dest_label}", p.rule, args={"owner": so, "dest": s_labels.get(dest_label)})
            if dest_label not in s_labels:
                op.status, op.note = "refused", f"the session has no {dest_label}"
            elif kind == "output" and dest_label in t_heard and dest_label not in s_heard:
                op.status, op.note = "refused", f"nothing in the session takes {dest_label} as input"
            ops.append(op)
        tb = t_inst.get(to)
        if tb is not None:
            sb = s_inst.get(so)
            t_inst_owner = next((o for o, c in t_ch.items() if c.label == f"Inst {tb.instrument}"), None)
            s_inst_owner = inst_rows.get(t_inst_owner)
            number = int(s_ch[s_inst_owner].label.split()[1]) if s_inst_owner in s_ch and s_ch[s_inst_owner].label.startswith("Inst ") else None
            if number is None:
                ops.append(Op("instout", name, f"<- {tb.name} of Inst {tb.instrument}", p.rule, status="refused",
                              note="the instrument that feeds it is not paired in the session"))
            elif sb is None or (sb.name, sb.instrument, sb.plugin) != (tb.name, number, tb.plugin):
                ops.append(Op("instout", name, f"<- {tb.name} of Inst {number}", p.rule,
                              args={"owner": so, "pattern": tb.raw, "instrument": number}))
        t_set = [(x.key, x.bus) for x in t_sends.get(to, [])]
        s_set = [(x.key, x.bus) for x in s_sends.get(so, [])]
        if t_set != s_set:
            op = Op("sends", name, f"{s_set} -> {t_set}", p.rule, args={"src_owner": to, "dst_owner": so})
            if not t_set:
                op.status, op.note = "refused", "removing sends is not part of a template apply"
            ops.append(op)
        if to in t_lv and so in s_lv:
            tl, sl = t_lv[to], s_lv[so]
            fixed = tl["fader_fixed"] if tl["fader_fixed"] >> 24 == tl["fader"] else tl["fader"] * FIXED_ONE
            if fixed != sl["fader_fixed"] or tl["pan"] != sl["pan"]:
                ops.append(Op("levels", name, f"fader {sl['fader_fixed'] / FIXED_ONE:.2f} -> {fixed / FIXED_ONE:.2f}, "
                              f"pan {sl['pan']} -> {tl['pan']}",
                              p.rule, args={"owner": so, "fader_fixed": fixed, "pan": tl["pan"]}))
        for op in ops[first:]:
            op.row = p.session["object_id"]

    # --- groups: a paired row follows its template row's group, matched by name (or number)
    t_grp = {m: g for g in read_groups(template) for m in g.members}
    s_grp = {m: g for g in read_groups(session) for m in g.members}
    for p in pairs:
        if p.session is None:
            continue
        tg, sg = t_grp.get(p.template["object_id"]), s_grp.get(p.session["object_id"])
        if (tg.label if tg else None) == (sg.label if sg else None):
            continue
        s = p.session
        if tg is None:
            ops.append(Op("group", _row_name(s), f"leave group {sg.label}", p.rule,
                          args={"track": s["object_id"], "leave": True}, row=s["object_id"]))
        else:
            ops.append(Op("group", _row_name(s), f"-> group {tg.label} ({', '.join(tg.settings)})", p.rule,
                          args={"track": s["object_id"], "label": tg.label, "name": tg.name,
                                "flags": tg.flags}, row=s["object_id"]))

    # --- the session's mixer-only bus returns, once a paired row's aux returns the same bus
    # (read from the template side: the input ops that feed the added returns run in this pass)
    returned: dict[str, str] = {}                   # session bus label -> the row returning it
    for p in pairs:
        if p.session is None or p.template["owner"] is None or p.session["owner"] is None:
            continue
        to = p.template["owner"]
        if to in t_ch and t_ch[to].label.startswith("Aux ") and t_inp.get(to) is not None:
            returned.setdefault(t_inp[to], _row_name(p.session))
    taken: dict[tuple[int, str], str] = {}          # (session Inst number, output name) -> the row taking it
    for p in pairs:
        if p.session is None or p.template["owner"] is None or p.session["owner"] is None:
            continue
        tb = t_inst.get(p.template["owner"])
        if tb is None:
            continue
        t_inst_owner = next((o for o, c in t_ch.items() if c.label == f"Inst {tb.instrument}"), None)
        s_inst_owner = inst_rows.get(t_inst_owner)
        if s_inst_owner in s_ch and s_ch[s_inst_owner].label.startswith("Inst "):
            taken.setdefault((int(s_ch[s_inst_owner].label.split()[1]), tb.name), _row_name(p.session))
    row_owners = {r["owner"] for r in s_rows if r["owner"] is not None}
    for so, c in sorted(s_ch.items()):
        if so in row_owners or not c.label.startswith("Aux ") or not c.in_use:
            continue
        slots = len(channel_slots(session, so))
        gone = f", {slots} slot(s) removed" if slots else ""
        sb = s_inst.get(so)
        if sb is not None and (sb.instrument, sb.name) in taken:
            ops.append(Op("return", c.label, f"takes {sb.name} of Inst {sb.instrument} like "
                          f"{taken[(sb.instrument, sb.name)]}: unbound{gone}",
                          "mixer-only", args={"owner": so, "slots": slots > 0, "unbind": True}))
            continue
        if s_inp.get(so) is None:
            continue
        bus = s_inp[so]
        if bus not in returned:
            continue
        ops.append(Op("return", c.label, f"returns {bus} like {returned[bus]}: no input{gone}",
                      "mixer-only", args={"owner": so, "slots": slots > 0}))
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
    leftover = [op for op in ops if op.kind in STRUCTURE]          # what still cannot be done
    rest = [op for op in ops if op.kind not in STRUCTURE]
    data, _ = apply(template, data, rest, session_count=count)
    return data, done_structural + leftover + rest, added


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
