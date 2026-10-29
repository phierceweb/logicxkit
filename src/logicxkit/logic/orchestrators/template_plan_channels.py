"""The channel steps of a template plan: each paired row's bound channel (width, plug-in chain,
strip reference, output and input, the instrument output it takes, sends, fader and pan), the
groups, and the session's mixer-only bus returns silenced once a template return listens to the
same bus. `channel_ops` hands `return_ops` the reads both need."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.mixer.binding import channels, input_labels, output_labels
from ..services.mixer.chains import channel_references
from ..services.arrange.groups import read_groups
from ..services.mixer.instout import read_instrument_outputs
from ..services.mixer.mixer import channel_formats
from ..services.stream.stream import HEADER
from ..services.mixer.levels import FIXED_ONE, read_levels
from ..services.arrange.retrack import cst_references
from ..services.mixer.sends import read_sends
from ..services.mixer.transplant import channel_slots, slot_class_version
from .ops import Op
from .template_plan_rows import row_name


@dataclass(frozen=True)
class ChannelReads:
    """What the channel step read and the bus-return step reads again."""
    t_ch: dict
    s_ch: dict
    t_inp: dict
    s_inp: dict
    t_inst: dict
    s_inst: dict
    inst_rows: dict


def _by_label(chans) -> dict[str, int]:
    """Routing targets by mixer label — buses and inputs are never marked in use, so all
    channels count."""
    return {c.label: o for o, c in chans.items()}



def channel_ops(template: bytes, session: bytes, pairs) -> tuple[list[Op], ChannelReads]:
    """The channel fields on the bound channels of paired rows, with the reads kept."""
    ops: list[Op] = []
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
        name = row_name(p.session)
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
    return ops, ChannelReads(t_ch, s_ch, t_inp, s_inp, t_inst, s_inst, inst_rows)


def group_ops(template: bytes, session: bytes, pairs) -> list[Op]:
    """A paired row follows its template row's group, matched by name (or number)."""
    ops: list[Op] = []
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
            ops.append(Op("group", row_name(s), f"leave group {sg.label}", p.rule,
                          args={"track": s["object_id"], "leave": True}, row=s["object_id"]))
        else:
            ops.append(Op("group", row_name(s), f"-> group {tg.label} ({', '.join(tg.settings)})", p.rule,
                          args={"track": s["object_id"], "label": tg.label, "name": tg.name,
                                "flags": tg.flags}, row=s["object_id"]))
    return ops


def return_ops(reads: ChannelReads, pairs, s_rows, session: bytes) -> list[Op]:
    """The session's mixer-only bus returns, once a paired row's aux returns the same bus or takes
    the same instrument output (read from the template side: the input ops that feed the added
    returns run in this pass)."""
    t_ch, s_ch, t_inp, s_inp = reads.t_ch, reads.s_ch, reads.t_inp, reads.s_inp
    t_inst, s_inst, inst_rows = reads.t_inst, reads.s_inst, reads.inst_rows
    ops: list[Op] = []
    returned: dict[str, str] = {}                   # session bus label -> the row returning it
    for p in pairs:
        if p.session is None or p.template["owner"] is None or p.session["owner"] is None:
            continue
        to = p.template["owner"]
        if to in t_ch and t_ch[to].label.startswith("Aux ") and t_inp.get(to) is not None:
            returned.setdefault(t_inp[to], row_name(p.session))
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
            taken.setdefault((int(s_ch[s_inst_owner].label.split()[1]), tb.name), row_name(p.session))
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
