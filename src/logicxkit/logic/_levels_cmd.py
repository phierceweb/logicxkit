"""`logic levels`: list channel faders and pans, set them by mixer label, or carry a project's
onto a copy of another."""

from __future__ import annotations

import json
from pathlib import Path

from ._edit import CommandError, edit_copy, owner_by_label
from .services.levels import (
    PAN_CENTRE, UNITY, copy_levels, db_text, fader_word, read_levels, set_levels)
from .services.retrack import find_project


def _wanted(args, data: bytes) -> dict[int, dict[str, int]]:
    """owner -> the fader word and pan byte ``--fader`` and ``--pan`` ask for."""
    want: dict[int, dict[str, int]] = {}
    try:
        for spec in args.fader or []:
            label, _, db = spec.rpartition("=")
            want.setdefault(owner_by_label(data, label), {})["fader_fixed"] = fader_word(float(db))
        for spec in args.pan or []:
            label, _, pan = spec.rpartition("=")
            if not -64 <= int(pan) <= 63:
                raise ValueError("a pan is -64 (left) to 63 (right)")
            want.setdefault(owner_by_label(data, label), {})["pan"] = int(pan) + PAN_CENTRE
    except ValueError as e:
        raise CommandError(f"{spec!r}: {e}") from None
    return want


def _set(args) -> int:
    def step(data, _count, data_file):
        out, changed = set_levels(data, _wanted(args, data))
        print(f"  {data_file.parent.name}: {len(changed)} channel(s) changed")
        return out
    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print("\nUnverified until opened in Logic.")
    return 0


def cmd_levels(args) -> int:
    """Dump a project's fader/pan, set them, or carry them onto another project's copy."""
    from .services.chains import channel_references

    if args.fader or args.pan:
        if args.to or not args.out:
            print("logic levels: --fader and --pan need --out, and do not go with --to")
            return 2
        return _set(args)
    src_project = find_project(Path(args.project))
    sources = sorted(src_project.glob("Alternatives/*/ProjectData"))
    if not sources:
        print(f"logic levels: {args.project} is not a project (no Alternatives/*/ProjectData)")
        return 2
    src = sources[0].read_bytes()

    if not args.to:
        refs = channel_references(src)
        rows = read_levels(src)
        if args.json:
            print(json.dumps({str(o): dict(v, ref=refs.get(o))
                              for o, v in sorted(rows.items())}, indent=2))
            return 0
        print(f"{'owner':>5}  {'ref':24s} {'fader':>5} {'dB':>7} {'pan':>5}")
        for owner, v in sorted(rows.items()):
            if v["fader"] == UNITY and v["pan"] == PAN_CENTRE and not refs.get(owner):
                continue
            print(f"{owner:5d}  {str(refs.get(owner, '')):24s} "
                  f"{v['fader']:5d} {db_text(v['fader_db']):>7} {v['pan_display']:+5d}")
        return 0

    if not args.out:
        print("logic levels: --to needs --out")
        return 2
    total = 0

    def step(data, _count, data_file):
        nonlocal total
        out, report = copy_levels(src, data, by=args.by)
        total += len(report["changed"])
        print(f"  {data_file.parent.name}: {report['matched']} matched, "
              f"{len(report['changed'])} changed, {report['unchanged']} already equal")
        if report["unmatched"]:
            print(f"    no counterpart in the source: {len(report['unmatched'])} channel(s)")
        return out

    print(f"levels from : {src_project}")
    try:
        edit_copy(Path(args.to), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print(f"\nSet levels on {total} channel(s).")
    return 0


def register(sub) -> None:
    lv = sub.add_parser("levels",
                        help="list channel fader/pan, set them, or copy them onto a project")
    lv.add_argument("project", help="the project to read levels from, or to set them on")
    lv.add_argument("--fader", action="append", metavar="CHANNEL=DB",
                    help="set a fader in dB, e.g. 'Audio 5=-6' or 'Bus 1=-inf' (needs --out)")
    lv.add_argument("--pan", action="append", metavar="CHANNEL=N",
                    help="set a pan, -64 (left) to 63 (right) (needs --out)")
    lv.add_argument("--to", help="project to write this one's levels onto (a copy is made)")
    lv.add_argument("--out", help="output directory, required to write")
    lv.add_argument("--by", choices=("reference", "owner", "label"), default="reference",
                    help="how --to pairs channels (default: channel-strip reference)")
    lv.add_argument("--json", action="store_true")
    lv.set_defaults(func=cmd_levels)
