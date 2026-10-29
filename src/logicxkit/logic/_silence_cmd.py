"""`strip-silence`: the silent stretches cut out of the named tracks' regions on a copy, the cut
edges faded; without `--out`, the plan alone."""

from __future__ import annotations

import math
from pathlib import Path

from ._edit import CommandError, edit_copy, plan_alternatives
from ._quantize_cmd import _wav_finder
from ._silence_spec import KEYS, Group, read_spec, settings_from
from .orchestrators.strip_silence import RegionPlan, Settings, apply_strip, piece_room, plan_strip
from .services.arrange.retrack import find_project
from .services.project.project import project_metadata
from .services.song.signature import meter


def _clock(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, seconds), 60)
    return f"{int(minutes)}:{rest:04.1f}"


def _lines(plan: RegionPlan, m) -> list[str]:
    r = plan.region
    head = f"{r.track:16s} {r.name!r:24s}"
    if plan.silent:
        if plan.floor_db is not None and plan.floor_db > -math.inf:
            return [f"{head} never heard over its bleed floor of {plan.floor_db:.1f} dBFS: muted"]
        return [f"{head} silent throughout: muted"]
    if plan.unchanged:
        return [f"{head} unchanged" + (f" ({plan.note})" if plan.note else "")]
    if plan.floor_db is not None:
        levels = f"bleed floor {plan.floor_db:.1f} dBFS, heard over {plan.limit_db:.1f} dBFS"
        if plan.above_db is not None:
            levels += f" and {plan.above_db:g} dB over the bleed"
    else:
        levels = f"loud {plan.loud_db:.1f} dBFS, silent under {plan.limit_db:.1f}, edges under {plan.edge_db:.1f} dBFS"
    out = [f"{head} {levels}: {len(plan.keeps)} kept, {plan.cuts} cut" + (f" ({plan.note})" if plan.note else "")]
    for a, b in plan.keeps:
        out.append(f"    keep {_clock(plan.seconds(a)):>8s} - {_clock(plan.seconds(b)):>8s}"
                   f"   bar {m.bar(plan.tick(a)):8.2f} - {m.bar(plan.tick(b)):8.2f}")
    return out


def _groups(args) -> list[Group]:
    """The track groups a run cuts: the spec's, or one from the flags."""
    given = {k: getattr(args, k) for k in KEYS}
    if args.spec:
        if args.track or any(v is not None for v in given.values()):
            raise ValueError("--spec is instead of --track and the settings flags; give one or the other")
        return read_spec(Path(args.spec))
    if not args.track:
        raise ValueError("--track NAME (repeatable) names what to cut, or --spec FILE.json")
    return [Group(tuple(args.track), settings_from(given))]


def cmd_strip_silence(args) -> int:
    try:
        groups = _groups(args)
    except ValueError as e:
        print(f"  {e}")
        return 2
    project = Path(args.project)
    plans: dict[str, list[list[RegionPlan]]] = {}
    try:
        bundle = find_project(project)
        files = plan_alternatives(bundle)
        for data_file in files:
            alt = data_file.parent.name
            info = project_metadata(bundle, alt)
            data = data_file.read_bytes()
            m = meter(data)
            cache: dict = {}
            print(f"{bundle.name}{' ' + alt if len(files) > 1 else ''}:")
            plans[alt] = []
            for k, group in enumerate(groups, 1):
                found = plan_strip(data, list(group.tracks), _wav_finder(data_file, args.audio), rate=info.get("sample_rate"),
                                   settings=group.settings, track_count=info.get("tracks"), cache=cache)
                plans[alt].append(found)
                if len(groups) > 1:
                    print(f"  group {k}: {', '.join(group.tracks)}")
                for plan in found:
                    for line in _lines(plan, m):
                        print(f"  {line}")
            piece_room(data, [plan for found in plans[alt] for plan in found])
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    if all(plan.unchanged for found in plans.values() for group in found for plan in group):
        print("  nothing to cut; no copy written")
        return 0
    if not args.out:
        return 0

    def step(data, count, data_file):
        totals = {"regions": 0, "pieces": 0, "muted": 0}
        for group, found in zip(groups, plans[data_file.parent.name], strict=True):
            data, made = apply_strip(data, found, settings=group.settings, track_count=count)
            for key in totals:
                totals[key] += made[key]
        print(f"  {data_file.parent.name}: {totals['regions']} region(s) changed, {totals['pieces']} piece(s) kept, "
              f"{totals['muted']} muted")
        return data

    try:
        edit_copy(project, Path(args.out), step,
                  moved=lambda data, count, data_file: [p.key for found in plans[data_file.parent.name] for p in found if not p.unchanged])
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    return 0


def register(sub) -> None:
    s = Settings()
    p = sub.add_parser("strip-silence", help="cut the silent stretches out of audio tracks' regions and fade the cuts, "
                       "on a copy; without --out, the plan")
    p.add_argument("project")
    p.add_argument("--track", action="append", metavar="NAME", help="an audio track to cut (repeatable)")
    p.add_argument("--spec", metavar="FILE.json", help="groups of tracks, each with its own settings, cut in one run — "
                   "instead of --track and the flags; config/example-strip-silence.json is the shape")
    p.add_argument("--out", help="output directory; without it the plan is printed and nothing written")
    p.add_argument("--threshold", metavar="DB",
                   help=f"a stretch is silent while it stays more than DB under the file's loud level, its 95th-percentile "
                        f"peak (default {s.threshold_db:g})")
    p.add_argument("--edge", metavar="DB",
                   help=f"a gap's edges crop outward over sound more than DB under the loud level — hum, string noise, "
                        f"room — a click of under 50 ms stepped over (default {s.edge_db:g}; --threshold or above)")
    p.add_argument("--min-gap", metavar="SECONDS",
                   help=f"a silent stretch shorter than this is left in (default {s.min_gap_s:g}; a rest between "
                        f"phrases is shorter, a gap between songs far longer)")
    p.add_argument("--min-keep", metavar="SECONDS",
                   help=f"a sound shorter than this between two silent stretches is silence too (default {s.min_keep_s:g})")
    p.add_argument("--pad", metavar="MS[:MS]",
                   help=f"kept before the sound starts and after it stops, one figure or BEFORE:AFTER "
                        f"(default {s.pad_ms[0]}); a drum rings on, so give it more after than before")
    p.add_argument("--fade", metavar="MS", help=f"the fade in and out at every cut (default {s.fade_ms})")
    p.add_argument("--ref", action="append", metavar="NAME",
                   help="a track whose playing says when the band plays, for a mic that is never silent then — a vocal "
                        "mic full of bleed: the mic's bleed floor is read while the reference plays, and it is heard "
                        "where it rises --above that floor and --above the bleed the references predict, each scaled by "
                        "the mic's usual ratio to it (repeatable: the overheads and, for a backing mic, the lead mics; "
                        "the envelope is then an RMS)")
    p.add_argument("--band", metavar="LOW:HIGH",
                   help="measure within this band in Hz, as an RMS — 300:3000 for a voice over drums and amps")
    p.add_argument("--above", metavar="DB",
                   help=f"with --ref: a mic is heard where it rises more than DB over its bleed floor (default {s.above_db:g})")
    p.add_argument("--gate", metavar="DB",
                   help="with --ref: a mic is never heard under DB over its bleed floor (default --above); a backing "
                        "singer off the mic, whose lines sit near the floor, wants it lower, 3")
    p.add_argument("--window", metavar="MS",
                   help=f"with --ref: the running median the levels are read on (default {s.window_ms}); a vocal "
                        f"wants it long enough to ignore drum hits in the bleed, a drum short enough to keep its own")
    p.add_argument("--against-band", metavar="LOW:HIGH",
                   help="with --ref: a second band of the mic itself; each sound is kept only if, at its peak, it is --tilt "
                        "dB louder in --band than here — a tom's fundamental against 400:2000, where a snare lives")
    p.add_argument("--tilt-band", metavar="LOW:HIGH|auto",
                   help="with --against-band: the band the tilt is read in instead of --band — the tom's fundamental, while the "
                        "level rule stays on the wide band; auto reads the file's fundamental itself")
    p.add_argument("--tilt", metavar="DB", help=f"with --against-band: how much louder (default {s.tilt_db:g})")
    p.add_argument("--audio", metavar="DIR", help="a folder holding the regions' audio files, when they are not "
                   "where the project says")
    p.set_defaults(func=cmd_strip_silence)
