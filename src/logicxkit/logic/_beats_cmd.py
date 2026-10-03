"""`logic beats` — patterns from a groovebin library (`groovebin index` builds it; `groovebin
search` and `show` read it) written into a copy of a project as MIDI regions: `place` one pattern,
`compose` a region per arrangement section, `generate` a phrase picked from library bars."""

from __future__ import annotations

import os
import secrets
import sqlite3
import struct
from pathlib import Path

from groovebin.library import default_db as library_default_db
from groovebin.library.compose import SectionPlan, group_patterns
from groovebin.library.generate import Phrase, load_pool, parse_meter, phrase
from groovebin.library.pattern import Pattern, pattern
from groovebin.library.search import find_group, get
from groovebin.maps import NAMES

from ._edit import CommandError, edit_copy, written_alternatives
from .services.midi.beats_compose import compose, plan
from .services.midi.beats_place import place, place_phrase
from .services.project.project import project_metadata
from .services.arrange.retrack import find_project

FAILURES = (OSError, ValueError, OverflowError, struct.error, sqlite3.Error, CommandError)


def default_db() -> Path:
    """groovebin's own default, so `groovebin index` and `logic beats` meet at one file. The
    library reads no environment itself; an empty `XDG_CACHE_HOME` reaches it as unset."""
    return library_default_db(os.environ.get("XDG_CACHE_HOME"))


def _db(args) -> Path:
    return Path(args.db).expanduser() if args.db else default_db()


def _listed(args) -> tuple[Path, bytes, int | None]:
    """The project, its first alternative's data and track count: every write is tried there
    before anything is copied."""
    project = find_project(Path(args.project))
    found = written_alternatives(project)
    if not found:
        raise CommandError(f"no project at {project}")
    return project, found[0].read_bytes(), project_metadata(project, found[0].parent.name).get("tracks")


def _translation(p: Pattern, drum_map: str | None) -> tuple[str, str] | None:
    """From the pattern's own map (as indexed) to ``drum_map``; none when they agree."""
    if drum_map is None or drum_map == p.map:
        return None
    if p.map is None:
        raise CommandError(f"pattern {p.id} was indexed with no drum map: nothing to translate to {drum_map} from")
    return p.map, drum_map


def _placed(r: dict, translation: tuple[str, str] | None) -> str:
    line = (f"  {r['track']!r} region {r['name']!r} at bar {r['bar']:g} for {r['bars']} bar(s): "
            f"{r['notes']} note(s), slot {r['slot']}")
    if r["dropped"]:
        line += f"; {r['dropped']} note(s) at or past the pattern's end dropped"
    if translation:
        left = ", ".join(f"{pitch} x{n}" for pitch, n in r["unmapped"].items())
        line += (f"; remapped {translation[0]} -> {translation[1]}"
                 + (f", no {translation[1]} counterpart, pitch kept: {left}" if left else ""))
    return line


def cmd_place(args) -> int:
    try:
        p = pattern(get(_db(args), args.id))
        translation = _translation(p, args.drum_map)
        options = {"track": args.track, "bar": args.bar, "repeat": args.repeat, "velocity": args.velocity,
                   "remap_maps": translation}
        project, data, count = _listed(args)
        place(data, p, track_count=count, **options)
    except FAILURES as e:
        print(f"  {e}")
        return 1

    def step(data, count, data_file):
        data, report = place(data, p, track_count=count, **options)
        print(f"  {data_file.parent.name}:")
        print(_placed({**report, "bar": args.bar}, translation))
        return data
    try:
        edit_copy(project, Path(args.out), step)
    except FAILURES as e:
        print(f"  {e}")
        return 1
    return 0


def _section(p: SectionPlan) -> str:
    head = f"  {p.section.name or '-':12s} bar {p.start_bar:g}-{p.end_bar:g}  "
    if p.skipped:
        return head + f"skipped: {p.skipped}"
    line = head + f"{p.beat.name!r} ({p.beat.id}) x{p.copies}: {len(p.notes)} note(s)"
    if p.fill:
        line += f", fill {p.fill.name!r} ({p.fill.id}) on bar {p.fill_bar:g} in place of {p.replaced} note(s)"
    elif p.no_fill:
        line += f", no fill: {p.no_fill}"
    if p.dropped:
        line += f"; {p.dropped} note(s) at or past a pattern's or the section's end dropped"
    return line


def cmd_compose(args) -> int:
    try:
        library, group = find_group(_db(args), args.group)
        patterns = group_patterns(_db(args), library, group)
        project, data, count = _listed(args)
        plans = plan(data, patterns, fills=args.fills)
        if not plans:
            raise CommandError("the song has no arrangement sections: nothing to compose")
        if not any(p.beat for p in plans):
            print("\n".join(map(_section, plans)))
            raise CommandError(f"no section has a pattern in group {group!r}: nothing written")
        compose(data, plans, track=args.track, track_count=count)
    except FAILURES as e:
        print(f"  {e}")
        return 1
    print(f"group {group!r}{f' ({library})' if library else ''}: {len(patterns)} pattern(s)")

    def step(data, count, data_file):
        plans = plan(data, patterns, fills=args.fills)
        data, _reports = compose(data, plans, track=args.track, track_count=count)
        print(f"  {data_file.parent.name}:")
        print("\n".join(map(_section, plans)))
        return data
    try:
        edit_copy(project, Path(args.out), step)
    except FAILURES as e:
        print(f"  {e}")
        return 1
    return 0


def _picks(ph: Phrase) -> list[str]:
    lines = []
    for k, p in enumerate(ph.picks, 1):
        line = f"  bar {k:<3d} {'fill ' if p.fill else 'beat '} {p.bar.id} bar {p.bar.index + 1} of {p.bar.count}"
        if p.fill:
            line += f", {p.distance} onset step(s) from the beat bar it replaces"
        lines.append(line)
    if ph.unmapped:
        left = ", ".join(f"{pitch} x{n}" for pitch, n in ph.unmapped.items())
        lines.append(f"  no {ph.map} counterpart, pitch {'dropped' if ph.unmapped_rule == 'drop' else 'kept'}: {left}")
    return lines


def cmd_generate(args) -> int:
    if args.bar < 1:
        print(f"  --bar {args.bar}: bars start at 1")
        return 2
    try:
        sig = parse_meter(args.meter)
        pool = load_pool(_db(args), sig=sig, category=args.category, role=args.role, tempo=args.tempo,
                         intensity=args.intensity, fills=args.fills)
        seed = args.seed if args.seed is not None else secrets.randbelow(2**32)
        ph = phrase(pool, bars=args.bars, seed=seed, fills=args.fills, map_name=args.drum_map, unmapped=args.unmapped)
        project, data, count = _listed(args)
        place_phrase(data, ph, track=args.track, bar=args.bar, track_count=count)
    except FAILURES as e:
        print(f"  {e}")
        return 1
    fills = f", {len(pool.fills)} fill bar(s)" if args.fills else ""
    left = f"; {pool.left_out} pattern(s) with a bar in another meter left out" if pool.left_out else ""
    print(f"pool: {len(pool.bars)} beat bar(s) from {len(pool.patterns)} pattern(s){fills}{left}")
    print(f"seed {seed}: {args.bars} bar(s) of {args.meter.strip()} in {ph.map}, {len(ph.notes)} note(s)")
    print("\n".join(_picks(ph)))

    def step(data, count, data_file):
        data, report = place_phrase(data, ph, track=args.track, bar=args.bar, track_count=count)
        print(f"  {data_file.parent.name}: {args.track!r} region {report['name']!r} at bar {args.bar} "
              f"for {args.bars} bar(s): {report['notes']} note(s), slot {report['slot']}")
        return data
    try:
        edit_copy(project, Path(args.out), step)
    except FAILURES as e:
        print(f"  {e}")
        return 1
    return 0


def register(sub) -> None:
    ap = sub.add_parser("beats", help="patterns from a groovebin library as MIDI regions in a copy of a project")
    beats = ap.add_subparsers(dest="beats_command", required=True, metavar="{place,compose,generate}")
    db_help = f"the groovebin library index (default {default_db()}; `groovebin index` builds it)"

    pl = beats.add_parser("place", help="one pattern as a MIDI region on a software instrument track, in a copy")
    pl.add_argument("project")
    pl.add_argument("id", help="the id `groovebin search` prints, or a unique prefix of it")
    pl.add_argument("--out", required=True, help="output directory")
    pl.add_argument("--track", required=True, metavar="NAME", help="a software instrument track")
    pl.add_argument("--bar", required=True, type=int, metavar="N", help="the bar the region starts on; the project's meter there must be the pattern's")
    pl.add_argument("--repeat", type=int, default=1, metavar="N", help="N copies back to back in the one region (default 1)")
    pl.add_argument("--map", dest="drum_map", choices=NAMES, help="translate the notes from the pattern's own map to this one (default: as indexed)")
    pl.add_argument("--velocity", type=float, default=1.0, metavar="SCALE", help="scale every velocity, held to 1-127 (default 1.0)")
    pl.add_argument("--db", metavar="PATH", help=db_help)
    pl.set_defaults(func=cmd_place)

    co = beats.add_parser("compose", help="a region per arrangement section from one group's patterns, in a copy")
    co.add_argument("project")
    co.add_argument("--out", required=True, help="output directory")
    co.add_argument("--track", required=True, metavar="NAME", help="a software instrument track")
    co.add_argument("--group", required=True, metavar="TEXT", help="the group: its whole name, or a substring of exactly one")
    co.add_argument("--fills", action="store_true", help="each section's last bar from a fill pattern of the group")
    co.add_argument("--db", metavar="PATH", help=db_help)
    co.set_defaults(func=cmd_compose)

    ge = beats.add_parser("generate", help="a phrase picked bar by bar from real library bars (a picker, not a model), "
                                           "as a MIDI region in a copy; `groovebin generate` writes one as a .mid",
                          description="Every bar is a real bar of a matching pattern: the first starts a pattern; each "
                                      "next has the kick and snare onsets nearest those of the bar that followed the "
                                      "last pick in its own pattern. Timing moves up to 5 ticks and velocity up to 6.")
    ge.add_argument("project")
    ge.add_argument("--out", required=True, help="output directory")
    ge.add_argument("--track", required=True, metavar="NAME", help="a software instrument track")
    ge.add_argument("--bar", required=True, type=int, metavar="N", help="the bar the region starts on; the project's meter must be --meter for every bar")
    ge.add_argument("--meter", required=True, metavar="N/D", help="e.g. 4/4; patterns with any bar in another meter are left out")
    ge.add_argument("--bars", required=True, type=int, metavar="N", help="the phrase's length in bars")
    ge.add_argument("--category", help="whole value, any case")
    ge.add_argument("--role", help="intro, verse, pre-chorus, chorus, bridge or outro")
    ge.add_argument("--intensity", metavar="RANGE", help="0.7 or 0.6-0.8, as `groovebin search` takes it")
    ge.add_argument("--tempo", metavar="RANGE", help="100-130, <90 or 98, as `groovebin search` takes it")
    ge.add_argument("--seed", type=int, metavar="N", help="the same seed and index give the same phrase (default: a new one, printed)")
    ge.add_argument("--fills", action="store_true", help="every fourth bar from a fill pattern")
    ge.add_argument("--map", dest="drum_map", choices=NAMES, help="write the notes in this drum map (default: the patterns' own)")
    ge.add_argument("--unmapped", choices=("keep", "drop"), default="keep", help="a note with no counterpart in --map (default keep)")
    ge.add_argument("--db", metavar="PATH", help=db_help)
    ge.set_defaults(func=cmd_generate)
