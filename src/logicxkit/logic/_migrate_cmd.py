"""`logic migrate`: propose-map (or a map file), apply-template, the output renamed
`CLAUDE migrated - <song>.logicx`, the checklist, and with `--verify` Logic's re-save compared."""

from __future__ import annotations

import shutil
from pathlib import Path

from ._apply_template import _copy_display, _left_alone, _rebased, _skip
from ._edit import CommandError, bump_track_count, edit_copy, first_project_data
from .orchestrators import migrate
from .orchestrators.apply_template import apply_template, session_only
from .services.project.project import project_metadata
from .services.arrange.retrack import find_project, project_folder

DIFFERENCES_SHOWN = 20


def _one_song(song: Path, project: Path) -> None:
    """Refuse when the folder the copy takes holds another project: it would come along
    under its own name."""
    root = song if song.is_dir() and song.suffix != ".logicx" else project_folder(project)
    if root == project:
        return
    others = sorted(str(p.relative_to(root)) for p in root.rglob("*.logicx") if p != project
                    and not any(part.endswith(".logicx") for part in p.relative_to(root).parts[:-1]))
    if not others:
        return
    if root == song:
        raise CommandError(f"{song} holds more than one project ({project.relative_to(root)}, "
                           f"{', '.join(others)}); name the song")
    raise CommandError(f"{root} holds another project beside {project.name} ({', '.join(others)}); "
                       "the copy takes the whole folder, so it would carry that too")


def _pairing(args, template: bytes, template_count, session: bytes, session_count) -> migrate.Pairing | int:
    """The pairing to apply, or an exit code once it has said why there is none."""
    map_text = None
    if args.map:
        try:
            map_text = Path(args.map).expanduser().read_text()
        except OSError as e:
            print(f"  {e}")
            return 2
    try:
        p = migrate.choose_pairing(template, session, template_count=template_count,
                                   session_count=session_count, map_text=map_text)
    except ValueError as e:
        print(f"  {e}")
        return 2
    if p.source == "map":
        print(f"map     : {args.map} ({sum(t is not None for t in p.forced.values())} track(s) mapped, "
              f"{sum(t is None for t in p.forced.values())} left alone, {len(p.excluded)} template track(s) left out)")
    if args.save_map and p.proposal is not None:
        target = Path(args.save_map).expanduser()
        if target.exists():
            print(f"  REFUSING — {target} exists; a map is hand-edited, so it is never overwritten")
            return 2
        target.write_text(p.proposal)
        print(f"map     : proposal written to {target}")
    if p.source == "object id":
        print("pairing : by object id — the session is the template's lineage, so the proposal is not applied")
    elif p.source == "proposal":
        print(f"pairing : propose-map's draft\n\n{p.proposal}")
    if p.problem and not args.force and p.source == "map":
        print(f"  REFUSING — the map pairs no tracks, and the projects are of different lineages: {p.problem}\n"
              "  Pair the tracks in it, or pass --force to apply it as it stands.")
        return 2
    if p.problem and not args.force:
        print(f"  REFUSING the unreviewed draft — {p.problem}\n"
              "  Pass --save-map FILE, correct it and rerun with --map FILE; or --force to apply "
              "the pairing above as it stands.")
        return 2
    if p.problem:
        print(f"\n  ⚠️  FORCED: the {'map' if p.source == 'map' else 'draft'} is applied past the lineage "
              f"check — {p.problem}\n")
    return p


def _place(dest: Path, staging: Path, out_dir: Path, name: str) -> Path:
    """Move the copy out of staging under the migrated name; a song kept in a folder with its
    recordings moves as that folder, renamed too."""
    root = staging / dest.relative_to(staging).parts[0]
    if root == dest:
        return dest.rename(out_dir / name)
    folder = root.rename(out_dir / Path(name).stem)
    bundle = folder / dest.relative_to(root)
    return bundle.rename(bundle.with_name(name))


def cmd_migrate(args) -> int:
    if args.map and args.save_map:
        print("  --save-map writes propose-map's draft; with --map nothing is proposed")
        return 2
    if args.verify and (problem := migrate.verify_problem()):
        print(f"  --verify refused: {problem}")
        return 2
    try:
        skip = _skip(args.skip)
        song, out_dir = Path(args.project).expanduser(), Path(args.out).expanduser()
        project, template_project = find_project(song), find_project(Path(args.template).expanduser())
        template, session = first_project_data(template_project), first_project_data(project)
        _one_song(song, project)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 2
    name = migrate.output_name(project)
    taken = [p for p in (out_dir / name, out_dir / Path(name).stem) if p.exists()]
    if taken:
        print(f"  REFUSING — {taken[0]} already exists; migrate never overwrites an output")
        return 2
    template_count = project_metadata(template_project).get("tracks")
    print(f"template: {template_project}\nsession : {project}")
    pairing = _pairing(args, template, template_count, session, project_metadata(project).get("tracks"))
    if isinstance(pairing, int):
        return pairing

    outcomes: list[migrate.Outcome] = []

    def step(data, count, data_file):
        original, data = data, _rebased(data)
        alt = data_file.parent.name
        try:
            kept = session_only(template, data, template_count=template_count, session_count=count,
                                forced=pairing.forced, excluded=pairing.excluded)
            out, ops, added = apply_template(template, data, template_count=template_count, session_count=count,
                                             skip=skip, forced=pairing.forced, excluded=pairing.excluded)
        except ValueError as e:
            if not _left_alone(e, pairing.forced, data_file):
                raise
            print(f"  {alt}: left as it was — {e}")
            outcomes.append(migrate.Outcome(alt, note=str(e)))
            return original
        for op in ops:
            print("  " + op.line())
        if "display" not in skip:
            for line in _copy_display(template_project, data_file.parent):
                print("  " + line)
        if "modes" not in skip:
            from .services.song.modes import copy_modes
            out, modes = copy_modes(template, out)
            print(f"  modes    {', '.join(n for n, on in modes.items() if on is True) or 'none'} lit, as the template")
        if "metronome" not in skip:
            from .services.song.metronome import copy_metronome
            out, met = copy_metronome(template, out)
            print(f"  metronome {sum(v is True for v in met.values())} boxes on, as the template")
        if added:
            print(f"  NumberOfTracks -> {bump_track_count(data_file, added)}")
        outcomes.append(migrate.Outcome(alt, ops, kept))
        return out

    staging = out_dir / f".{Path(name).stem}.partial"
    fresh = not out_dir.exists()
    try:
        dest = edit_copy(song, staging, step)
        bundle = _place(dest, staging, out_dir, name)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if fresh and out_dir.is_dir() and not any(out_dir.iterdir()):
            out_dir.rmdir()
    failed = sum(op.status == "failed" for o in outcomes for op in o.ops)
    print(f"\noutput  : {bundle}\n\nchecklist")
    for line in migrate.checklist(outcomes, bundle, verify=args.verify):
        print(line)
    if not args.verify:
        return 1 if failed else 0
    return _report(migrate.verify(bundle, out_dir), failed)


def _report(verdict: migrate.Verdict, failed: int) -> int:
    print("\nverify")
    if verdict.problem:
        print(f"  not verified — {verdict.problem}")
        return 1
    print(f"  Logic's save: {verdict.resave}")
    for alt in verdict.only_ours:
        print(f"  {alt}: not compared — Logic's save holds only the open alternative")
    for alt in verdict.only_logic:
        print(f"  {alt}: only in Logic's save")
    for alt in verdict.compared:
        lines = verdict.differences[alt]
        if not lines:
            print(f"  {alt}: the row lists match")
            continue
        print(f"  {alt}: ROWS DIFFER")
        for line in lines[:DIFFERENCES_SHOWN]:
            print(f"    {line}")
        if len(lines) > DIFFERENCES_SHOWN:
            print(f"    … and {len(lines) - DIFFERENCES_SHOWN} more")
    return 0 if verdict.matched and not failed else 1


def register(sub) -> None:
    ap = sub.add_parser("migrate", help="give a song a template's layout in one run (writes a renamed copy)")
    ap.add_argument("project", metavar="SONG", help="the song to migrate (a copy is made)")
    ap.add_argument("--template", required=True, help="the template project (read only)")
    ap.add_argument("--out", required=True, help="output directory; the copy is 'CLAUDE migrated - <song>.logicx'")
    ap.add_argument("--map", metavar="FILE", help="pair tracks as this map file says, instead of propose-map's draft")
    ap.add_argument("--save-map", metavar="FILE", help="write propose-map's draft here (never overwrites)")
    ap.add_argument("--skip", metavar="KIND,...", help="ops to leave out, as apply-template's --skip")
    ap.add_argument("--force", action="store_true",
                    help="apply even when the two projects are not the same lineage and no map was given")
    ap.add_argument("--verify", action="store_true",
                    help="have Logic Pro re-save the output and compare the row lists (macOS, a checkout)")
    ap.set_defaults(func=cmd_migrate)
