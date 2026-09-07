"""`apply-template`: plan and run the chain of atomic edits that gives a session a
template's layout. Writes a copy; `--plan` only prints."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, bump_track_count, edit_copy, first_project_data, object_by_name
from .orchestrators.apply_template import KINDS, apply_template, lineage_problem, plan
from .services.pairing import format_map, parse_map_full, propose_map
from .services.project import project_metadata
from .services.retrack import find_project


def _rebased(data: bytes) -> bytes:
    """A project made before Logic 11.2 first gets Logic 12's slot-key layout, so nothing the
    template brings can land on a key the old numbering used for something else."""
    from .services.slotkeys import needs_rebase, rebase
    if not needs_rebase(data):
        return data
    data, report = rebase(data)
    print(f"  slot keys moved to Logic 12's layout first ({report['moved']} record(s), base "
          f"{report['from']} -> {report['to']})")
    return data


def _copy_display(template_project: Path, alternative: Path) -> list[str]:
    """The template's track header components and control bar onto one alternative of the
    output — DisplayState, not ProjectData, so it sits beside the record ops."""
    from .services.controlbar import alternative_dirs, copy_layout
    from .services.header import read_components, write_components
    from .services.toolbar import copy_toolbar
    src = next(iter(alternative_dirs(template_project)), None)
    if src is None or not (alternative / "DisplayState.plist").exists():
        return ["display  (no DisplayState.plist to copy from or to)"]
    lines = []
    for label, copy in (("header", lambda: write_components(alternative, read_components(src))),
                        ("controlbar", lambda: copy_layout(src, alternative)),
                        ("toolbar", lambda: copy_toolbar(src, alternative))):
        try:
            shown = copy()
        except (ValueError, KeyError) as e:          # a converted project can lack the blob
            lines.append(f"{label:10} left as it was ({e})")
            continue
        noun = {"header": "components", "controlbar": "controls", "toolbar": "buttons"}[label]
        lines.append(f"{label:10} {sum(shown.values())} of {len(shown)} {noun} shown, as the template")
    return lines


def _skip(spec: str | None) -> tuple[str, ...]:
    kinds = tuple(k.strip() for k in (spec or "").split(",") if k.strip())
    bad = [k for k in kinds if k not in KINDS + ("display", "modes", "metronome")]
    if bad:
        raise CommandError(f"unknown kind(s) {bad}; choose from {', '.join(KINDS)}")
    return kinds


def _only(args, session: bytes, count: int | None) -> set[int] | None:
    """The session rows named by ``--track`` and ``--stack`` (a stack's members), or None."""
    if not (args.track or args.stack):
        return None
    from .services.stacks import read_stacks, read_tracks
    rows = {r["key"]: r["object_id"] for r in read_tracks(session, count)}
    only = {object_by_name(session, name, count) for name in args.track or []}
    stacks = {s.name: s for s in read_stacks(session, count)}
    for name in args.stack or []:
        if name not in stacks:
            raise CommandError(f"no stack named {name!r} (have: {', '.join(sorted(stacks))})")
        only.update(rows[key] for key, _n in stacks[name].members)
    return only


def cmd_apply_template(args) -> int:
    template_project = find_project(Path(args.template))
    template = first_project_data(template_project)
    template_count = project_metadata(template_project).get("tracks")
    try:
        skip = _skip(args.skip) + (("levels",) if args.keep_levels else ())
    except CommandError as e:
        print(f"  {e}")
        return 2
    print(f"template: {template_project}")

    session_project = find_project(Path(args.project))
    if args.propose_map:
        from .services.stacks import read_tracks
        session = first_project_data(session_project)
        entries = propose_map(read_tracks(template, template_count),
                              read_tracks(session, project_metadata(session_project).get("tracks")))
        text = format_map(entries, read_tracks(template, template_count))
        Path(args.propose_map).write_text(text)
        print(f"session : {session_project}\nwrote   : {args.propose_map}\n\n{text}")
        return 0
    forced, excluded = None, None
    if args.map:
        try:
            forced, excluded = parse_map_full(Path(args.map).read_text())
        except (OSError, ValueError) as e:
            print(f"  {e}")
            return 2
        print(f"map     : {args.map} ({sum(t is not None for t in forced.values())} track(s) mapped, "
              f"{sum(t is None for t in forced.values())} left alone, {len(excluded)} template track(s) left out)")
    problem = None if forced else lineage_problem(template, first_project_data(session_project),
                              template_count=template_count,
                              session_count=project_metadata(session_project).get("tracks"))
    if problem and not args.force:
        print(f"session : {session_project}\n\n  REFUSING — {problem}\n"
              "  Pass --force only if you have read the plan and want it anyway.")
        return 2
    if problem:
        print(f"\n  ⚠️  FORCED past the lineage check — {problem}\n")

    if args.plan:
        session = _rebased(first_project_data(session_project))
        count = project_metadata(session_project).get("tracks")
        try:
            only = _only(args, session, count)
        except CommandError as e:
            print(f"  {e}")
            return 2
        try:
            ops = plan(template, session, template_count=template_count, session_count=count, skip=skip,
                       only=only, forced=forced, excluded=excluded)
        except ValueError as e:
            print(f"  {e}")
            return 2
        print(f"session : {session_project}" + (f"\nonly    : {len(only)} row(s)" if only else "") + "\n")
        for op in ops:
            print("  " + op.line())
        print(f"\n{sum(op.status == 'planned' for op in ops)} op(s) to run, "
              f"{sum(op.status == 'refused' for op in ops)} refused, "
              f"{sum(op.status == 'skipped' for op in ops)} skipped")
        return 0

    outcome = {"failed": 0}

    def step(data, count, data_file):
        data = _rebased(data)
        only = _only(args, data, count)
        if only:
            print(f"  only {len(only)} row(s)")
        try:
            out, ops, added = apply_template(template, data, template_count=template_count,
                                             session_count=count, skip=skip, only=only, forced=forced,
                                             excluded=excluded)
        except ValueError as e:
            others = [p for p in data_file.parent.parent.glob("*/ProjectData") if p != data_file]
            if not forced or "map names a session track" not in str(e) or not others:
                raise
            print(f"  {data_file.parent.name}: left as it was — {e}")   # another alternative's layout
            return data
        for op in ops:
            print("  " + op.line())
        if not only and "display" not in skip:
            for line in _copy_display(template_project, data_file.parent):
                print("  " + line)
        if not only and "modes" not in skip:
            from .services.modes import copy_modes
            out, modes = copy_modes(template, out)
            lit = [name for name, on in modes.items() if on is True]
            print(f"  modes    {', '.join(lit) if lit else 'none'} lit, count-in {modes['Count-in']}, as the template")
        if not only and "metronome" not in skip:
            from .services.metronome import copy_metronome
            out, met = copy_metronome(template, out)
            on = [name for name, v in met.items() if v is True]
            print(f"  metronome {len(on)} boxes on, {sum(r['on'] for r in met['MIDI click'].values())} MIDI click rows, as the template")
        if added:
            print(f"  NumberOfTracks -> {bump_track_count(data_file, added)}")
        outcome["failed"] += sum(op.status == "failed" for op in ops)
        print(f"\n  {sum(op.status == 'done' for op in ops)} done, "
              f"{sum(op.status == 'refused' for op in ops)} refused, "
              f"{sum(op.status == 'skipped' for op in ops)} skipped, {outcome['failed']} failed")
        return out
    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print("\nOpen the copy in Logic before trusting it.")
    return 1 if outcome["failed"] else 0


def register(sub) -> None:
    ap = sub.add_parser("apply-template", help="give a session a template's layout (writes a copy)")
    ap.add_argument("template", help="the template project (read only)")
    ap.add_argument("project", help="the session to apply it to (a copy is made)")
    ap.add_argument("--out", help="output directory (not needed with --plan)")
    ap.add_argument("--plan", action="store_true", help="print the ops and stop")
    ap.add_argument("--keep-levels", action="store_true", help="leave faders and pans alone")
    ap.add_argument("--skip", metavar="KIND,...", help=f"ops to leave out: {', '.join(KINDS)}")
    ap.add_argument("--track", action="append", metavar="NAME",
                    help="apply to this track only (repeatable; 'Drums (Aux 2)' picks among duplicates)")
    ap.add_argument("--stack", action="append", metavar="NAME",
                    help="apply to the members of this stack only (repeatable)")
    ap.add_argument("--propose-map", metavar="FILE",
                    help="write a guessed track map for a project of another lineage, then stop")
    ap.add_argument("--map", metavar="FILE", help="pair tracks as this map file says (skips the lineage check)")
    ap.add_argument("--force", action="store_true",
                    help="run even when the two projects are not the same lineage")
    ap.set_defaults(func=cmd_apply_template)
