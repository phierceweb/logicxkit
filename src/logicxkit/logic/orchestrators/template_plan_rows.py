"""The structural and track-field steps of a template plan: the rows to add and the stacks to
make, leave or move into, the arrange order under each parent, and a paired row's name, colour,
icon, hidden and power flags. Each step returns its ops; `apply_template._plan` keeps the order."""

from __future__ import annotations

from ..services.arrange.stacks import Stack
from .ops import Op
from .template_stacks import same_stack


def row_name(r: dict) -> str:
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



def structure_ops(pairs, t_in, s_in, target_of) -> list[Op]:
    """Tracks to add, stacks to make, rows to leave or move into stacks; a stack of rows added
    above it is made once they exist, and a move a planned stack already covers is dropped."""
    ops: list[Op] = []
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
                        ops.append(Op("member", row_name(m), f"leave stack {_name(s_in.get(m['key']))}",
                                      p.rule, args={"track": m["object_id"], "leave": True}, row=m["object_id"]))
                op = Op("stack", row_name(t), f"make a stack of {len(wanted)} track(s)", p.rule,
                        args={"members": [m["object_id"] for m in wanted], "name": t["name"],
                              "colour": t["colour"], "template_row": t["key"], "stack_id": t["object_id"]})
            elif kind is None:
                op = Op("add", row_name(t), "add", p.rule, status="refused",
                        note="only audio, instrument and aux tracks can be added")
            elif previous is None:
                op = Op("add", row_name(t), f"add {kind} track", p.rule, status="refused",
                        note="no paired row above it to place it after")
            else:
                inside = t_in.get(t["key"])
                anchor = last_add.args["name"] if last_add else previous["name"]
                op = Op("add", row_name(t), f"add {kind} track after {anchor}", p.rule,
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
            ops.append(Op("member", row_name(s), f"leave stack {have.name}", p.rule,
                          args={"track": s["object_id"], "leave": True}, row=s["object_id"]))
        elif want is not None and not same_stack(have, target):
            found = isinstance(target, Stack)
            to = _name(target, have) if found else want.name
            desc = f"move into stack {to}" if have is None else f"move from {_name(have, target)} to {to}"
            op = Op("member", row_name(s), desc, p.rule,
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
    return ops


def order_ops(pairs, t_stacks, t_in, s_in, target_of) -> list[Op]:
    """Arrange order per parent, among paired rows that already sit under that parent."""
    ops: list[Op] = []
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
                ops.append(Op("order", row_name(cur.session), f"after {prev.session['name']}", cur.rule,
                              args={"track": cur.session["object_id"], "after": prev.session["object_id"]},
                              row=cur.session["object_id"]))
    return ops


def field_ops(pairs) -> list[Op]:
    """A paired row's name, colour, icon, hidden flag and power, where they differ."""
    ops: list[Op] = []
    for p in pairs:
        if p.session is None:
            continue
        t, s = p.template, p.session
        if t["name"] != s["name"]:
            ops.append(Op("rename", row_name(s), f"-> {t['name']!r}", p.rule,
                          args={"track": s["object_id"], "name": t["name"]}, row=s["object_id"]))
        if t["colour"] != s["colour"]:
            ops.append(Op("colour", row_name(s), f"{s['colour']} -> {t['colour']}", p.rule,
                          args={"track": s["object_id"], "colour": t["colour"]}, row=s["object_id"]))
        if t["icon"] is not None and s["icon"] is not None and t["icon"] != s["icon"]:
            ops.append(Op("icon", row_name(s), f"{s['icon']} -> {t['icon']}", p.rule,
                          args={"track": s["object_id"], "icon": t["icon"]}, row=s["object_id"]))
        if t["hidden"] != s["hidden"]:
            ops.append(Op("hidden", row_name(s), "hide" if t["hidden"] else "show", p.rule,
                          args={"track": s["object_id"], "hidden": t["hidden"]}, row=s["object_id"]))
        if t["on"] != s["on"]:
            ops.append(Op("power", row_name(s), "switch on" if t["on"] else "switch off", p.rule,
                          args={"track": s["object_id"], "on": t["on"]}, row=s["object_id"]))
    return ops
