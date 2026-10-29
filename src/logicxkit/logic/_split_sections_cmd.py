"""`split-sections`: the named tracks' regions cut at the edges of the sections called NAME and,
with `--to`, what plays inside them moved onto another track, on a copy; without `--out`, the plan
alone."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy, plan_alternatives
from ._silence_cmd import _clock
from ._silence_spec import LONGEST_S
from .orchestrators.split_sections import RegionPlan, apply_split, plan_split
from .services.arrange.retrack import find_project
from .services.project.project import project_metadata
from .services.song.signature import meter


def _lines(plan: RegionPlan, m, section: str) -> list[str]:
    r = plan.region
    head = f"{r.track:16s} {r.name!r:24s}"
    if plan.unchanged:
        out = [f"{head} unchanged"]
    else:
        what = f"{len(plan.spans)} piece(s)" if plan.cuts else "whole"
        out = [f"{head} {what}, {len(plan.moves)} moved" if plan.to else f"{head} {what}"]
    for tick in plan.cuts:
        out.append(f"    cut   {_clock(plan.seconds(tick)):>8s}              bar {m.bar(tick):8.2f}")
    for span in plan.moves:
        out.append(f"    move  {_clock(plan.seconds(span.start)):>8s} - {_clock(plan.seconds(span.end)):>8s}   "
                   f"bar {m.bar(span.start):8.2f} - {m.bar(span.end):8.2f}   onto {plan.to!r}")
    for span in plan.spans:
        for a, b, inside in span.slivers:
            out.append(f"    left  {(b - a) * plan.spt / plan.rate:.1f} s {'inside' if inside else 'outside'} {section!r} "
                       f"at bar {m.bar(a):.2f} - {m.bar(b):.2f}, with the {'piece' if plan.cuts else 'region'} "
                       f"{'before' if a > span.start else 'after'}")
    return out


def cmd_split_sections(args) -> int:
    tracks = list(args.track)
    if args.onto and len(args.onto) != len(tracks):
        print("  --to names one track per --track, in the same order")
        return 2
    if not 0 <= args.min_piece <= LONGEST_S:
        print(f"  --min-piece {args.min_piece:g}: seconds, 0 to {LONGEST_S}")
        return 2
    to = dict(zip(tracks, args.onto or (), strict=False))
    project = Path(args.project)
    plans: dict[str, list[RegionPlan]] = {}
    try:
        bundle = find_project(project)
        files = plan_alternatives(bundle)
        for data_file in files:
            alt = data_file.parent.name
            info = project_metadata(bundle, alt)
            data = data_file.read_bytes()
            m = meter(data)
            print(f"{bundle.name}{' ' + alt if len(files) > 1 else ''}:")
            plans[alt] = plan_split(data, tracks, args.section, to, rate=info.get("sample_rate"),
                                    min_piece_s=args.min_piece, track_count=info.get("tracks"))
            for plan in plans[alt]:
                for line in _lines(plan, m, args.section):
                    print(f"  {line}")
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    if all(plan.unchanged for found in plans.values() for plan in found):
        print("  nothing to cut; no copy written")
        return 0
    if not args.out:
        return 0

    def step(data, count, data_file):
        data, made = apply_split(data, plans[data_file.parent.name], track_count=count)
        print(f"  {data_file.parent.name}: {made['regions']} region(s) cut into {made['pieces']} piece(s), {made['moved']} moved")
        return data

    try:
        edit_copy(project, Path(args.out), step,
                  moved=lambda data, count, data_file: [p.key for p in plans[data_file.parent.name] if p.head_moves])
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    return 0


def register(sub) -> None:
    p = sub.add_parser("split-sections", help="cut audio tracks' regions at the edges of the arrangement sections of one "
                       "name and, with --to, move what plays inside them onto another track, on a copy; without --out, the plan")
    p.add_argument("project")
    p.add_argument("--section", required=True, metavar="NAME", help="the arrangement sections to cut at, by name")
    p.add_argument("--track", action="append", required=True, metavar="NAME", help="an audio track whose regions are cut (repeatable)")
    p.add_argument("--to", dest="onto", action="append", metavar="NAME",
                   help="the track the pieces inside the sections go onto, where they are in time: one per --track, in order")
    p.add_argument("--min-piece", type=float, default=1.0, metavar="SECONDS",
                   help="a stretch shorter than this at a section's edge stays with its neighbour, uncut (default 1)")
    p.add_argument("--out", help="output directory; without it the plan is printed and nothing written")
    p.set_defaults(func=cmd_split_sections)
