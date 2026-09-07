"""Channel-level apply commands: transplant · bypass · clear-slots · route · send · strip-save.
Each writes a copy (or a new .cst) and never the input; each is one step an orchestrator can
chain."""

from __future__ import annotations

from pathlib import Path

from pf_core.utils.io import atomic_write_bytes

from ._edit import CommandError, edit_copy, first_project_data, owner_by_label, pairs
from .services.retrack import find_project
from .services.transplant import remove_slots, set_bypass, transplant


def cmd_route(args) -> int:
    """Set channel outputs and inputs by mixer label."""
    from .services.routing import set_input, set_output

    def step(data, _count, _file):
        for spec, setter, word in ((args.output or [], set_output, "->"),
                                   (args.input or [], set_input, "<-")):
            for item in spec:
                channel, _, target = item.partition("=")
                data = setter(data, owner_by_label(data, channel), owner_by_label(data, target))
                print(f"  {channel.strip()} {word} {target.strip()}")
        return data
    return _run(args, step)


def _bus_number(spec: str) -> int:
    digits = "".join(ch for ch in spec if ch.isdigit())
    if not digits:
        raise CommandError(f"{spec!r}: give a bus as 'Bus 15' or '15'")
    return int(digits)


def cmd_send(args) -> int:
    """Add, copy or remove sends on named channels."""
    from .services.sends_write import add_send, copy_sends, remove_sends

    if args.copy and not args.src:
        print("  --copy needs --from SRC_PROJECT")
        return 2
    src = first_project_data(Path(args.src)) if args.src else None

    def step(data, _count, _file):
        for label in args.remove or []:
            data = remove_sends(data, owner=owner_by_label(data, label))
            print(f"  {label.strip():11s} sends removed")
        for spec in args.add or []:
            channel, _, bus = spec.partition("=")
            data, report = add_send(data, owner=owner_by_label(data, channel),
                                    bus=_bus_number(bus), key=args.key)
            print(f"  {channel.strip():11s} -> Bus {report['bus']} (send {report['key']}"
                  f"{', replaced' if report['replaced'] else ''})")
        for dst_label, src_label in pairs(args.copy or []):
            data, report = copy_sends(src, data, src_owner=owner_by_label(src, src_label),
                                      dst_owner=owner_by_label(data, dst_label))
            print(f"  {dst_label:11s} <- {src_label:11s} sends {report['keys']} to buses "
                  f"{report['buses']}{' replacing ' + str(report['replaced']) if report['replaced'] else ''}")
        return data
    return _run(args, step, note="\nUnverified until opened in Logic.")


def cmd_transplant(args) -> int:
    """Clone plugin slots channel-for-channel from SRC onto a copy of DST."""
    src_project = find_project(Path(args.src))
    src = first_project_data(src_project)
    print(f"from : {src_project}")
    total = 0

    def step(data, _count, _file):
        nonlocal total
        for dst_label, src_label in pairs(args.channel):
            s, d = owner_by_label(src, src_label), owner_by_label(data, dst_label)
            data, report = transplant(src, data, src_owner=s, dst_owner=d, bypass=args.bypass,
                                      force=args.force)
            warn = "  WIDTH MISMATCH" if report["width_mismatch"] else ""
            print(f"  {dst_label:11s} <- {src_label:11s} {report['slots']} slot(s)"
                  f"{' replacing ' + str(report['replaced']) if report['replaced'] else ''}"
                  f"{'  bypassed' if args.bypass else ''}{warn}")
            total += report["slots"]
        return data
    args.project = args.dst
    code = _run(args, step)
    if code == 0:
        print(f"\nTransplanted {total} slot(s). Open the copy in Logic before trusting it.")
    return code


def cmd_bypass(args) -> int:
    """Bypass (or --enable) every plugin slot on the named channels."""
    def step(data, _count, _file):
        for label in args.channel:
            data, keys = set_bypass(data, owner_by_label(data, label), bypassed=not args.enable)
            print(f"  {label:11s} {'enabled' if args.enable else 'bypassed'} slot keys {keys}")
        return data
    return _run(args, step)


def cmd_clear_slots(args) -> int:
    """Remove every plugin slot from the named channels."""
    def step(data, _count, _file):
        for label in args.channel:
            data, keys = remove_slots(data, owner_by_label(data, label))
            print(f"  {label:11s} removed slot keys {keys}" if keys else f"  {label:11s} carried no slots")
        return data
    return _run(args, step, note="\nUnverified until opened in Logic.")


def cmd_strip_save(args) -> int:
    """Export one channel as a .cst, the way Logic's Save Channel Strip Setting does."""
    from .services.stripsave import export_strip

    data = first_project_data(Path(args.project))
    try:
        owner = owner_by_label(data, args.channel)
    except CommandError as e:
        print(f"  {e}")
        return 1
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        print(f"  {out} exists; pass --overwrite")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(out, export_strip(data, owner))
    print(f"wrote {out} ({args.channel}, owner {owner})")
    return 0


def _run(args, step, note: str = "") -> int:
    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    if note:
        print(note)
    return 0


def register(sub) -> None:
    tp = sub.add_parser("transplant",
                        help="clone plugin slots channel-for-channel (writes a copy)")
    tp.add_argument("src", help="project to take slots FROM")
    tp.add_argument("dst", help="project to put them ON (a copy is made)")
    tp.add_argument("--out", required=True, help="output directory")
    tp.add_argument("--channel", action="append", required=True, metavar="LABEL[=SRC_LABEL]",
                    help="mixer label, e.g. 'Audio 20' (repeatable)")
    tp.add_argument("--bypass", action="store_true", help="clone the slots bypassed")
    tp.add_argument("--force", action="store_true",
                    help="write past a refusal — a move that overruns the slot key range "
                         "deletes the channel's .cst reference record")
    tp.set_defaults(func=cmd_transplant)
    bp = sub.add_parser("bypass", help="bypass every slot on a channel (writes a copy)")
    bp.add_argument("project")
    bp.add_argument("--out", required=True)
    bp.add_argument("--channel", action="append", required=True, metavar="LABEL")
    bp.add_argument("--enable", action="store_true", help="un-bypass instead")
    bp.set_defaults(func=cmd_bypass)
    cs = sub.add_parser("clear-slots", help="remove every plugin slot from a channel (writes a copy)")
    cs.add_argument("project")
    cs.add_argument("--out", required=True)
    cs.add_argument("--channel", action="append", required=True, metavar="LABEL")
    cs.set_defaults(func=cmd_clear_slots)
    rt = sub.add_parser("route", help="set a channel's output or input by label (writes a copy)")
    rt.add_argument("project")
    rt.add_argument("--out", required=True)
    rt.add_argument("--output", action="append", metavar="CHANNEL=DEST", help="e.g. 'Inst 6=Output 1-2'")
    rt.add_argument("--input", action="append", metavar="CHANNEL=INPUT", help="e.g. 'Audio 27=Input 3'")
    rt.set_defaults(func=cmd_route)
    sd = sub.add_parser("send", help="add, copy or remove sends by channel label (writes a copy)")
    sd.add_argument("project")
    sd.add_argument("--out", required=True)
    sd.add_argument("--add", action="append", metavar="CHANNEL=BUS", help="e.g. 'Audio 5=Bus 15'")
    sd.add_argument("--key", type=int, choices=(0, 1, 2), help="send slot for --add (default: lowest free)")
    sd.add_argument("--remove", action="append", metavar="CHANNEL", help="drop every send on it")
    sd.add_argument("--copy", action="append", metavar="LABEL[=SRC_LABEL]",
                    help="replace its sends with the source channel's (needs --from)")
    sd.add_argument("--from", dest="src", metavar="SRC_PROJECT", help="project the copied sends come from")
    sd.set_defaults(func=cmd_send)
    ss = sub.add_parser("strip-save", help="export a channel as a .cst channel strip setting")
    ss.add_argument("project")
    ss.add_argument("--channel", required=True, metavar="LABEL", help="e.g. 'Audio 1'")
    ss.add_argument("-o", "--out", required=True, help="output .cst path (never the Logic library)")
    ss.add_argument("--overwrite", action="store_true")
    ss.set_defaults(func=cmd_strip_save)
