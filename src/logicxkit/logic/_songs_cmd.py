"""`songs`: a live set's songs, found where the named tracks all stop, laid under a setlist and
written as arrangement sections on a copy; without `--out`, the plan — the stops, the stretches of
playing, the setlist over them and where the counts disagree."""

from __future__ import annotations

import math
from pathlib import Path

from ._edit import CommandError, edit_copy, plan_alternatives
from ._quantize_cmd import _wav_finder
from .orchestrators.songs import Settings, SongPlan, apply_songs, plan_songs
from .services.song.arrangement_write import fill_gaps
from .services.arrange.retrack import find_project
from .services.project.project import project_metadata
from .services.song.setlist import read_setlist
from .services.song.signature import meter

FLAGS = (("threshold", "threshold_db"), ("min_gap", "min_gap_s"), ("min_keep", "min_keep_s"), ("merge", "merge_s"),
         ("min_stop", "min_stop_s"), ("min_song", "min_song_s"))


def _clock(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, seconds), 60)
    return f"{int(minutes)}:{rest:04.1f}"


def _settings(args) -> Settings:
    given = {}
    for flag, field in FLAGS:
        value = getattr(args, flag)
        if value is None:
            continue
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"--{flag.replace('_', '-')} {value!r}: a number") from None
        if not math.isfinite(number):
            raise ValueError(f"--{flag.replace('_', '-')} {value!r}: a number")
        if flag == "threshold" and number > 0:
            raise ValueError(f"--threshold {value}: 0 or below, dB under the loud level")
        if flag != "threshold" and number < 0:
            raise ValueError(f"--{flag.replace('_', '-')} {value}: 0 or more seconds")
        given[field] = number
    return Settings(**given)


def _lines(plan: SongPlan, m) -> list[str]:
    s = plan.stops
    span = lambda a, b: f"{_clock(plan.seconds(a)):>8} - {_clock(plan.seconds(b)):>8}  {plan.seconds(b) - plan.seconds(a):6.1f} s"  # noqa: E731
    out = [f"set {_clock(plan.seconds(s.hops))} long: {len(s.stops)} stop(s), {len(s.songs)} stretch(es) of playing, "
           f"{len(plan.setlist)} song(s) on the setlist"]
    out += [f"  stop  {span(a, b)}" for a, b in s.stops]
    for k, (a, b) in enumerate(s.songs, 1):
        name = plan.setlist.songs[k - 1] if plan.matched else f"stretch {k}"
        out.append(f"  song  {span(a, b)}   bar {m.bar(plan.tick(a)):8.2f} - {m.bar(plan.tick(b)):8.2f}   {name}")
    out += [f"  left out  {span(a, b)}  (under the song minimum)" for a, b in s.short]
    if plan.matched:
        for song in sorted(plan.setlist.breaks):
            stop = plan.stop_after(song)
            where = f"stop {_clock(plan.seconds(stop[0]))} - {_clock(plan.seconds(stop[1]))}" if stop else "no stop follows"
            out.append(f"  break after {plan.setlist.songs[song - 1]!r}: {where}")
    else:
        out.append(f"  the setlist names {len(plan.setlist)} song(s), the set holds {len(s.songs)} stretch(es) of playing: "
                   "nothing written — change --min-stop, --merge or --min-song, or the setlist")
    if plan.taken:
        first = plan.taken[0]
        out.append(f"  {len(plan.taken)} section(s) already where the songs play, {first.name!r} at bar {m.bar(first.start):.2f} "
                   "first: nothing written — run on a copy without the songs' sections, or edit them with `arrangement`")
    return out


def cmd_songs(args) -> int:
    try:
        setlist = read_setlist(Path(args.setlist))
        settings = _settings(args)
    except ValueError as e:
        print(f"  {e}")
        return 2
    if not args.track:
        print("  --track NAME (repeatable) names the tracks that go quiet between songs")
        return 2
    if args.breaks is not None and not args.breaks.strip():
        print("  --breaks names the stops' sections; give it a name")
        return 2
    project = Path(args.project)
    plans: dict[str, SongPlan] = {}
    try:
        bundle = find_project(project)
        files = plan_alternatives(bundle)
        for data_file in files:
            alt = data_file.parent.name
            info = project_metadata(bundle, alt)
            data = data_file.read_bytes()
            print(f"{bundle.name}{' ' + alt if len(files) > 1 else ''}:")
            plan = plan_songs(data, list(args.track), _wav_finder(data_file, args.audio), rate=info.get("sample_rate"),
                              settings=settings, track_count=info.get("tracks"), setlist=setlist)
            plans[alt] = plan
            for line in _lines(plan, meter(data)):
                print(f"  {line}")
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    if not all(plan.matched and not plan.taken for plan in plans.values()):
        return 1
    if not args.out:
        return 0
    def step(data, _count, data_file):
        plan = plans[data_file.parent.name]
        data = apply_songs(data, plan)
        return fill_gaps(data, args.breaks, end=plan.end) if args.breaks else data

    try:
        edit_copy(project, Path(args.out), step)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    print(f"  {len(setlist)} section(s) written" + (f", the stops as {args.breaks!r}" if args.breaks else ""))
    return 0


def register(sub) -> None:
    s = Settings()
    p = sub.add_parser("songs", help="a live set's songs, found where the named tracks all stop, as arrangement "
                       "sections named from a setlist, on a copy; without --out, the stops and the plan")
    p.add_argument("project")
    p.add_argument("setlist", help="a text file: one song per line in order, a line reading 'break' after a song the "
                   "band stopped on, blank lines and lines starting with # skipped")
    p.add_argument("--track", action="append", metavar="NAME", help="a track that goes quiet between songs — a bass DI, "
                   "a kick, a snare (repeatable; every named track must be quiet)")
    p.add_argument("--out", help="output directory; without it the plan is printed and nothing written")
    p.add_argument("--threshold", metavar="DB", help=f"a track is quiet while it stays more than DB under its file's loud "
                   f"level, its 95th-percentile peak (default {s.threshold_db:g})")
    p.add_argument("--min-gap", metavar="SECONDS", help=f"a quiet run shorter than this is not a gap (default {s.min_gap_s:g})")
    p.add_argument("--min-keep", metavar="SECONDS", help=f"a sound shorter than this between two gaps is silence too "
                   f"(default {s.min_keep_s:g})")
    p.add_argument("--merge", metavar="SECONDS", help=f"gaps less than this of playing apart are one stop — a band that has "
                   f"stopped noodles and talks (default {s.merge_s:g})")
    p.add_argument("--min-stop", metavar="SECONDS", help=f"a stop this long separates songs (default {s.min_stop_s:g})")
    p.add_argument("--min-song", metavar="SECONDS", help=f"playing shorter than this is listed and left out "
                   f"(default {s.min_song_s:g})")
    p.add_argument("--breaks", metavar="NAME", help="also a section NAME over every stop, from the set's start to the "
                   "first song and after the last to its end, so the sections run contiguous")
    p.add_argument("--audio", metavar="DIR", help="a folder holding the regions' audio files, when they are not where "
                   "the project says")
    p.set_defaults(func=cmd_songs)
