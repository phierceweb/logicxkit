"""Channel-level apply commands: transplant · bypass · clear-slots · route · send · strip-save.
Each writes a copy (or a new .cst) and never the input; each is one step an orchestrator can
chain."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pf_core.utils.io import atomic_write_bytes

from ._edit import CommandError, edit_copy, first_project_data, owner_by_label, pairs
from .services.arrange.retrack import find_project
from .services.mixer.transplant import remove_slots, set_bypass, transplant


def _bus_in_use(data: bytes, bus: str, count: int | None, alt: str) -> bytes:
    """``bus`` as Logic leaves one an output or a send first goes to (`bus_return`), said when
    it changes anything; a label that is no bus is left to the caller."""
    from .services.arrange.bus_return import use_bus
    from .services.mixer.binding import channels
    owner = next((o for o, c in channels(data).items() if c.label == bus), None)
    if owner is None or not bus.startswith("Bus "):
        return data
    data, made = use_bus(data, owner, count)
    if made["aux"]:
        print(f"  {alt}: {bus} put in use: {made['aux']} fed from it, output Output 1-2, as Logic's own does")
    elif made["minted"]:
        print(f"  {alt}: {bus} given a UUID of its own, as Logic's own has")
    return data


def cmd_route(args) -> int:
    """Set channel outputs and inputs by mixer label."""
    from .services.mixer.routing import set_input, set_output

    def step(data, count, data_file):
        alt = data_file.parent.name
        for item in args.output or []:
            channel, _, target = item.partition("=")
            data = _bus_in_use(data, target.strip(), count, alt)
            data = set_output(data, owner_by_label(data, channel), owner_by_label(data, target))
            print(f"  {alt}: {channel.strip()} -> {target.strip()}")
        for item in args.input or []:
            channel, _, target = item.partition("=")
            data = set_input(data, owner_by_label(data, channel), owner_by_label(data, target))
            print(f"  {alt}: {channel.strip()} <- {target.strip()}")
        return data
    return _run(args, step)


def _bus_number(spec: str) -> int:
    digits = "".join(ch for ch in spec if ch.isdigit())
    if not digits:
        raise CommandError(f"{spec!r}: give a bus as 'Bus 15' or '15'")
    return int(digits)


def cmd_send(args) -> int:
    """Add, set, copy or remove sends on named channels."""
    from .services.mixer.levels import shown_db
    from .services.mixer.sends import read_sends
    from .services.mixer.sends_write import add_send, copy_sends, remove_sends, set_send

    if args.copy and not args.src:
        print("  --copy needs --from SRC_PROJECT")
        return 2
    settings = {"level_db": args.level, "mode": args.mode and args.mode.replace("-", " "),
                "bypass": {"on": True, "off": False}.get(args.bypass)}
    if args.set and all(v is None for v in settings.values()):
        print("  --set needs --level, --mode or --bypass")
        return 2
    if not (args.add or args.set) and any(v is not None for v in settings.values()):
        print("  --level, --mode and --bypass go with --add or --set")
        return 2
    src = first_project_data(Path(args.src)) if args.src else None

    def told(data, channel: str, report: dict) -> str:
        s = next(s for s in read_sends(data)[report["owner"]] if s.key == report["key"])
        return (f"{channel.strip():11s} -> Bus {report['bus']} (send {report['key']}): "
                f"{shown_db(s.level_exact)} dB, {s.mode}{', bypassed' if s.bypassed else ''}")

    def step(data, count, data_file):
        alt = data_file.parent.name
        for label in args.remove or []:
            data = remove_sends(data, owner=owner_by_label(data, label))
            print(f"  {alt}: {label.strip():11s} sends removed")
        for spec in args.add or []:
            channel, _, bus = spec.partition("=")
            data = _bus_in_use(data, f"Bus {_bus_number(bus)}", count, alt)
            data, report = add_send(data, owner=owner_by_label(data, channel),
                                    bus=_bus_number(bus), key=args.key, **settings)
            print(f"  {alt}: " + told(data, channel, report) + (", replaced" if report["replaced"] else ""))
        for spec in args.set or []:
            channel, _, bus = spec.partition("=")
            try:
                data, report = set_send(data, owner=owner_by_label(data, channel),
                                        bus=_bus_number(bus), **settings)
            except ValueError as e:
                raise CommandError(f"{channel.strip()}: {e}") from None
            print(f"  {alt}: " + told(data, channel, report))
        for dst_label, src_label in pairs(args.copy or []):
            data, report = copy_sends(src, data, src_owner=owner_by_label(src, src_label),
                                      dst_owner=owner_by_label(data, dst_label))
            print(f"  {alt}: {dst_label:11s} <- {src_label:11s} sends {report['keys']} to buses "
                  f"{report['buses']}{' replacing ' + str(report['replaced']) if report['replaced'] else ''}")
        return data
    return _run(args, step, note="\nUnverified until opened in Logic.")


def cmd_transplant(args) -> int:
    """Clone plugin slots channel-for-channel from SRC onto a copy of DST."""
    if not (args.channel or args.stack):
        print("  name the channels with --channel or --stack")
        return 2
    src_project = find_project(Path(args.src))
    src = first_project_data(src_project)
    print(f"from : {src_project}")
    total = 0

    def step(data, count, data_file):
        nonlocal total
        alt = data_file.parent.name
        targets = _targets(args, data, count)
        uses = Counter(src_label for _dst, src_label in targets)
        for dst_label, src_label in targets:
            s, d = owner_by_label(src, src_label), owner_by_label(data, dst_label)
            try:
                data, report = transplant(src, data, src_owner=s, dst_owner=d, bypass=args.bypass,
                                          force=args.force, fan_out=uses[src_label] > 1)
            except ValueError as e:
                raise CommandError(f"{alt}: {dst_label} <- {src_label}: {e}") from None
            warn = "  WIDTH MISMATCH" if report["width_mismatch"] else ""
            shared = "  SHARED ID" if report["ids"] == "unmeasured" else ""
            print(f"  {alt}: {dst_label:11s} <- {src_label:11s} {report['slots']} slot(s)"
                  f"{' replacing ' + str(report['replaced']) if report['replaced'] else ''}"
                  f"{'  bypassed' if args.bypass else ''}{warn}{shared}")
            total += report["slots"]
        return data
    args.project = args.dst
    code = _run(args, step)
    if code == 0:
        print(f"\nTransplanted {total} slot(s). Open the copy in Logic before trusting it.")
    return code


def _targets(args, data: bytes, count: int | None) -> list[tuple[str, str]]:
    """(destination label, source label) for every ``--channel`` and every channel a ``--stack``
    member is bound to, each destination once."""
    from .services.arrange.stacks import read_stacks, read_tracks, rows_below
    from .services.arrange.trackname import stack_named

    out = pairs(args.channel or [])
    if args.stack:
        stacks = read_stacks(data, count)
        labels = {r["key"]: r["label"] for r in read_tracks(data, count)}
        for spec in args.stack:
            name, sep, src_label = (part.strip() for part in spec.partition("="))
            stack = stack_named(stacks, name)
            if not sep or not src_label:
                raise CommandError(f"--stack takes NAME=SRC_LABEL, e.g. 'Drums=Audio 2'; got {spec!r}")
            if stack is None:
                raise CommandError(f"no stack named {name!r} (have: {', '.join(sorted(s.name for s in stacks))})")
            out += [(labels[key], src_label) for key, _n in rows_below(stacks, stack, headers=False)
                    if labels.get(key)]
    first: dict[str, str] = {}
    for dst_label, src_label in out:
        first.setdefault(dst_label, src_label)
    return list(first.items())


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
    from .services.mixer.stripsave import export_strip

    data = first_project_data(Path(args.project))
    try:
        owner = owner_by_label(data, args.channel)
    except CommandError as e:
        print(f"  {e}")
        return 1
    out = Path(args.out)
    from .services.mixer.library import under_live_library
    if under_live_library(out) and not args.install:
        print(f"  refusing to write into Logic's own library at {out}: this is the library Logic loads, not a "
              "scratch directory. Pass --install to write there on purpose, or give -o elsewhere.")
        return 2
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
    tp.add_argument("--channel", action="append", metavar="LABEL[=SRC_LABEL]",
                    help="mixer label, e.g. 'Audio 20' (repeatable)")
    tp.add_argument("--stack", action="append", metavar="NAME=SRC_LABEL",
                    help="every member of this folder stack takes SRC_LABEL's slots (repeatable)")
    tp.add_argument("--bypass", action="store_true", help="clone the slots bypassed")
    tp.add_argument("--force", action="store_true",
                    help="write past a refusal — a move that overruns the slot key range "
                         "deletes the channel's .cst reference record; a third-party slot of the "
                         "other width loads at its saved width; copies with no measurable "
                         "instance id share one")
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
    sd = sub.add_parser("send",
                        help="add, set, copy or remove sends by channel label (writes a copy)")
    sd.add_argument("project")
    sd.add_argument("--out", required=True)
    sd.add_argument("--add", action="append", metavar="CHANNEL=BUS", help="e.g. 'Audio 5=Bus 15'")
    sd.add_argument("--set", action="append", metavar="CHANNEL=BUS",
                    help="an existing send to give --level, --mode or --bypass")
    sd.add_argument("--level", type=float, metavar="DB",
                    help="the level of every --add and --set, -inf to 6 (--level=-inf)")
    sd.add_argument("--mode", choices=("post-pan", "post-fader", "pre-fader"),
                    help="the mode of every --add and --set")
    sd.add_argument("--bypass", choices=("on", "off"), help="bypass every --add and --set, or not")
    sd.add_argument("--key", type=int, choices=(0, 1, 2), help="send slot for --add (default: lowest free)")
    sd.add_argument("--remove", action="append", metavar="CHANNEL", help="drop every send on it")
    sd.add_argument("--copy", action="append", metavar="LABEL[=SRC_LABEL]",
                    help="replace its sends with the source channel's (needs --from)")
    sd.add_argument("--from", dest="src", metavar="SRC_PROJECT", help="project the copied sends come from")
    sd.set_defaults(func=cmd_send)
    ss = sub.add_parser("strip-save", help="export a channel as a .cst channel strip setting")
    ss.add_argument("project")
    ss.add_argument("--channel", required=True, metavar="LABEL", help="e.g. 'Audio 1'")
    ss.add_argument("-o", "--out", required=True, help="output .cst path; under Logic's own library only with --install")
    ss.add_argument("--overwrite", action="store_true")
    ss.add_argument("--install", action="store_true", help="allow writing into Logic's own library (refused without it)")
    ss.set_defaults(func=cmd_strip_save)
