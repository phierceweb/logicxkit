"""`arrangement` and `tempo`: read a project's sections and tempo track, or edit a copy."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy
from .services.retrack import find_project


def _spec(spec: str, what: str) -> tuple[int, str]:
    number, sep, value = spec.partition("=")
    if not sep or not number.strip().isdigit():
        raise CommandError(f"bad {what} {spec!r}: use N={what.upper()} with N the section number")
    return int(number), value.strip()


def _number(text: str, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise CommandError(f"bad {what} {text!r}: a number of bars, fractions allowed") from None


def _bar_tick(data: bytes, bar: str, what: str) -> int:
    from .services.signature import meter
    return meter(data).tick(_number(bar, what))


def _bar_length(data: bytes, bars: str, what: str, *, at: int) -> int:
    from .services.signature import meter
    return meter(data).ticks(_number(bars, what), at)


def _section_start(data: bytes, n: int) -> int:
    from .services.arrangement import read_sections
    from .services.events import BAR_ONE
    sections = read_sections(data)
    return sections[n - 1].start if 1 <= n <= len(sections) else BAR_ONE


def _print_sections(project: Path, data: bytes) -> None:
    from .services.arrangement import KINDS, read_sections
    from .services.signature import meter, read_signatures
    sections = read_sections(data)
    m = meter(data)
    times = ", ".join(f"{t.numerator}/{t.denominator}" for t in read_signatures(data)[0])
    print(f"{project.name}: {len(sections)} section(s)  ({times})")
    for n, s in enumerate(sections, 1):
        print(f"  {n:2d}. bar {m.bar(s.start):7.2f}  {m.bars(s.length, s.start):6.2f} bars  {s.name:16s} {KINDS.get(s.kind, s.kind):7s} ticks {s.start}+{s.length}")


def cmd_arrangement(args) -> int:
    from logicxkit.logicx import project_data
    from .services import arrangement_write as w
    from .services.arrangement import KINDS
    edits = [a for a in (args.rename, args.move, args.length, args.delete, args.add) if a]
    project = find_project(Path(args.project))
    if not edits:
        _print_sections(project, project_data(project))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2

    def step(data, _count, _file):
        for spec in args.rename or []:
            n, name = _spec(spec, "rename")
            data = w.rename_section(data, n, name)
        for spec in args.move or []:
            n, bar = _spec(spec, "move")
            data = w.move_section(data, n, _bar_tick(data, bar, "move"))
        for spec in args.length or []:
            n, bars = _spec(spec, "length")
            data = w.resize_section(data, n, _bar_length(data, bars, "length", at=_section_start(data, n)))
        for n in sorted(args.delete or [], reverse=True):
            data = w.delete_section(data, n)
        for spec in args.add or []:
            parts = spec.split(":")
            if len(parts) not in (3, 4):
                raise CommandError(f"bad --add {spec!r}: use BAR:BARS:NAME or BAR:BARS:NAME:KIND")
            kind = {v: k for k, v in KINDS.items()}.get(parts[3].lower(), None) if len(parts) == 4 else 0
            if kind is None:
                raise CommandError(f"bad kind {parts[3]!r}: one of {', '.join(KINDS.values())}")
            start = _bar_tick(data, parts[0], "add")
            data = w.add_section(data, parts[2], start=start,
                                 length=_bar_length(data, parts[1], "add", at=start), kind=kind)
        _print_sections(project, data)
        return data
    return _run(project, args.out, step)


def cmd_tempo(args) -> int:
    from logicxkit.logicx import project_data
    from .services.tempo import project_tempo, read_tempo_events
    from .services.tempo_write import add_ramp, add_tempo, set_tempo
    project = find_project(Path(args.project))

    def show(data):
        from .services.signature import meter
        m = meter(data)
        shown, first = project_tempo(data)
        print(f"{project.name}: {shown:g} bpm" + (f" shown at save; {first:g} at bar 1" if first != shown else ""))
        for e in read_tempo_events(data):
            print(f"  bar {m.bar(e.position):8.3f}  {e.bpm:g} bpm   tick {e.position}" + ("   (ramp point)" if e.generated else ""))
    if args.set is None and not args.add and not args.ramp:
        show(project_data(project))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2

    def step(data, _count, _file):
        if args.set is not None:
            data = set_tempo(data, args.set)
        for spec in args.add or []:
            bar, sep, bpm = spec.partition("=")
            if not sep:
                raise CommandError(f"bad --add {spec!r}: use BAR=BPM, for example 33=150")
            try:
                data = add_tempo(data, _bar_tick(data, bar, "add"), float(bpm))
            except ValueError as e:
                raise CommandError(str(e)) from None
        for spec in args.ramp or []:
            a, sep, b = spec.partition(":")
            bar1, s1, bpm1 = a.partition("=")
            bar2, s2, bpm2 = b.partition("=")
            if not (sep and s1 and s2):
                raise CommandError(f"bad --ramp {spec!r}: use BAR=BPM:BAR=BPM, for example 33=176:41=140")
            try:
                data = add_ramp(data, _bar_tick(data, bar1, "ramp"), float(bpm1),
                                _bar_tick(data, bar2, "ramp"), float(bpm2), per_bar=args.density)
            except ValueError as e:
                raise CommandError(str(e)) from None
        show(data)
        return data
    return _run(project, args.out, step)


def _run(project: Path, out: str, step) -> int:
    try:
        edit_copy(project, Path(out), step)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    return 0


def register(sub) -> None:
    ar = sub.add_parser("arrangement", help="read or edit the arrangement track's sections")
    ar.add_argument("project")
    ar.add_argument("--out", help="output directory (needed to write)")
    ar.add_argument("--rename", action="append", metavar="N=NAME", help="rename section N")
    ar.add_argument("--move", action="append", metavar="N=BAR", help="start section N at BAR")
    ar.add_argument("--length", action="append", metavar="N=BARS", help="make section N last BARS")
    ar.add_argument("--delete", action="append", type=int, metavar="N", help="take section N off")
    ar.add_argument("--add", action="append", metavar="BAR:BARS:NAME[:KIND]", help="a new section (kind: custom, verse, chorus, bridge, outro)")
    ar.set_defaults(func=cmd_arrangement)
    tp = sub.add_parser("tempo", help="read the tempo track, or set the project tempo")
    tp.add_argument("project")
    tp.add_argument("--out", help="output directory (needed to write)")
    tp.add_argument("--set", type=float, metavar="BPM", help="the tempo at bar 1")
    tp.add_argument("--add", action="append", metavar="BAR=BPM", help="a tempo change at BAR")
    tp.add_argument("--ramp", action="append", metavar="BAR=BPM:BAR=BPM", help="a linear ramp between two bars")
    tp.add_argument("--density", type=int, default=8, metavar="N", help="ramp events per bar (1, 2, 4, 8 or 16; 8 is Logic's 1/8)")
    tp.set_defaults(func=cmd_tempo)
    register_signature(sub)


def cmd_signature(args) -> int:
    from logicxkit.logicx import project_data
    from .services.settings import read_settings, set_division
    from .services.signature import meter, read_signatures
    from .services.signature_write import add_key_change, add_meter_change, set_key, set_time_signature
    project = find_project(Path(args.project))

    def show(data):
        times, keys = read_signatures(data)
        m = meter(data)
        s = read_settings(data)
        print(f"{project.name}: " + ", ".join(f"{t.numerator}/{t.denominator} from bar {m.bar(t.tick):g}" for t in times)
              + f"; division /{s['division']}; key root {s['key_root']}")
        for k in keys:
            print(f"  key {k.name} from bar {m.bar(k.tick):g}")
    if args.time is None and args.key is None and args.division is None and not args.key_at and not args.time_at:
        show(project_data(project))
        return 0
    if not args.out:
        print("  --out is needed to write")
        return 2

    def step(data, _count, _file):
        if args.time:
            n, _, d = args.time.partition("/")
            if not (n.isdigit() and d.isdigit()):
                raise CommandError(f"bad --time {args.time!r}: use N/D, for example 3/4")
            data = set_time_signature(data, int(n), int(d))
        if args.key:
            data = set_key(data, args.key)
        if args.division:
            data = set_division(data, args.division)
        for spec in args.key_at or []:
            bar, sep, key = spec.partition("=")
            if not sep:
                raise CommandError(f"bad --key-at {spec!r}: use BAR=KEY, for example 33=G")
            data = add_key_change(data, _bar_tick(data, bar, "key-at"), key)
        for spec in args.time_at or []:
            bar, sep, sig = spec.partition("=")
            n, slash, d = sig.partition("/")
            if not (sep and slash and n.isdigit() and d.isdigit()):
                raise CommandError(f"bad --time-at {spec!r}: use BAR=N/D, for example 49=3/4")
            data = add_meter_change(data, _bar_tick(data, bar, "time-at"), int(n), int(d))
        show(data)
        return data
    return _run(project, args.out, step)


def register_signature(sub) -> None:
    sg = sub.add_parser("signature", help="read or set the time signature, key and division")
    sg.add_argument("project")
    sg.add_argument("--out", help="output directory (needed to write)")
    sg.add_argument("--time", metavar="N/D", help="the meter at bar 1 (songs with later changes are refused)")
    sg.add_argument("--key", metavar="KEY", help="the key, e.g. G, Bb or 'A minor'")
    sg.add_argument("--division", type=int, metavar="N", help="the LCD's division, /N")
    sg.add_argument("--key-at", action="append", metavar="BAR=KEY", help="a key change at BAR")
    sg.add_argument("--time-at", action="append", metavar="BAR=N/D", help="a meter change at BAR (on a bar line)")
    sg.set_defaults(func=cmd_signature)
