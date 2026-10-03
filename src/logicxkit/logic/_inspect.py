"""Inspection commands: project · diff · image · neural · ocr · stacks · levels.
`image` writes the extracted JPEG; `stacks --move` and `levels --to` write a copy through
`_edit.edit_copy`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


from .services.mixer.library import strip_library
from .services.translate.neural import read_neural
from .services.stream.projdiff import diff_against_library, diff_projects
from .services.project.project import project_metadata, read_project, window_image_path

_NEURAL_NOISE = {"metronomeParameters", "tunerParameters"}  # UI state, not tone


def _shown(value):
    """A stored float32 as the figure it was set to: six significant digits, a hair off zero as 0."""
    if not isinstance(value, float):
        return value
    return 0.0 if abs(value) < 1e-9 else float(f"{value:.6g}")


def cmd_project(args) -> int:
    """Read-only inventory of a .logicx project: per-channel chains, presets, track names."""
    report = read_project(Path(args.logicx))
    if args.json:
        print(json.dumps(report, indent=2, default=list))
        return 0
    md = report["metadata"]
    print(f"# {report['name']}")
    print(f"  {md.get('tracks')} tracks · {md.get('bpm')} BPM · {md.get('key')} · "
          f"{md.get('sig')} · {md.get('logic_version', '?')}")
    print(f"\n  channels with inserts: {len(report['channels'])}")
    for c in report["channels"]:
        chain = " → ".join(p + (f" [{pre}]" if pre else "") for p, pre in c["chain"])
        cst = f"   ⟨loads {', '.join(c['cst'])}⟩" if c.get("cst") else ""
        print(f"    {c['label']:10s} {chain}{cst}")
        for plug, params in c.get("native", []):
            shown = {k: _shown(v) for k, v in params.items()}
            print(f"        {plug}: {shown}")
    names = report["track_names"]
    if names:
        print(f"\n  track names ({len(names)}): " + ", ".join(n for n, _ in names))
    return 0


def cmd_diff(args) -> int:
    """Diff two projects, or one project against the saved channel-strip library.

    Exit 0 = no differences / all strips match; 1 = differences or drift found.
    """
    a = read_project(Path(args.a))
    if args.library is not None:
        rows = diff_against_library(a, Path(args.library) if args.library else strip_library())
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                if r["status"] == "match":
                    print(f"  ok      {r['label']:10s} {r['cst']}")
                elif r["status"] == "missing":
                    print(f"  MISSING {r['label']:10s} {r['cst']} — not in library")
                else:
                    print(f"  DRIFT   {r['label']:10s} {r['cst']}")
                    print(f"          project: {' → '.join(r['project'])}")
                    print(f"          strip  : {' → '.join(r['strip'])}")
            bad = sum(1 for r in rows if r["status"] != "match")
            print(f"\n{len(rows)} referenced strip(s), {bad} drift/missing")
        return 1 if any(r["status"] != "match" for r in rows) else 0
    if not args.b:
        print("logic diff: need a second .logicx or --library")
        return 2
    d = diff_projects(a, read_project(Path(args.b)))
    if args.json:
        print(json.dumps(d, indent=2))
    else:
        for k, (va, vb) in d["metadata"].items():
            print(f"  {k}: {va} -> {vb}")
        for e in d["channels"]:
            if e["status"] == "changed":
                print(f"  ~ {e['label']}")
                print(f"      a: {' → '.join(p for p, _ in e['a'])}")
                print(f"      b: {' → '.join(p for p, _ in e['b'])}")
            else:
                side = e["a"] if e["status"] == "removed" else e["b"]
                sign = "-" if e["status"] == "removed" else "+"
                print(f"  {sign} {e['label']}: {' → '.join(p for p, _ in side)}")
        print(f"\n{len(d['channels'])} channel(s) differ, "
              f"{len(d['metadata'])} metadata field(s) differ")
    return 1 if (d["metadata"] or d["channels"]) else 0


def cmd_image(args) -> int:
    """Extract the auto-saved WindowImage.jpg (the view open at save — may be partial)."""
    try:
        src = window_image_path(Path(args.logicx))
    except FileNotFoundError as e:
        print(e)
        return 1
    out = Path(args.out) if args.out else Path(f"{Path(args.logicx).stem} - WindowImage.jpg")
    if out.exists() and not args.overwrite:
        print(f"{out} exists; pass --overwrite to replace it")
        return 1
    shutil.copyfile(src, out)
    print(f"wrote {out.resolve()}  (whatever view was open at save — possibly partial)")
    return 0


def cmd_neural(args) -> int:
    """Dump decoded Neural DSP plugin state from a .cst strip or .logicx bundle."""
    states = read_neural(Path(args.file))
    if args.json:
        print(json.dumps(states, indent=2))
        return 0
    if not states:
        print("no decodable Neural DSP plugin state found")
        return 1
    for s in states:
        where = f"{s['channel']}: " if s.get("channel") else ""
        print(f"\n{where}NDSP/{s['subtype']}  [{s['format']}]  @0x{s['offset']:x}")
        meta = {k: v for k, v in s["meta"].items()
                if isinstance(v, (str, int, float)) and v != ""}
        for k in sorted(meta):
            print(f"  {k} = {meta[k]}")
        for sec, params in s["sections"].items():
            if sec in _NEURAL_NOISE:
                continue
            print(f"  [{sec}]")
            for k, v in params.items():
                print(f"    {k:24s} = {v}")
    return 0


def cmd_ocr(args) -> int:
    from .services.project.ocr import OcrClient, fader_row
    client = OcrClient()
    p = Path(args.file)
    d = client.ocr_logicx(p) if p.is_dir() else client.ocr_image(p)
    if args.json:
        print(json.dumps(d, indent=2))
        return 0
    row = fader_row(d["items"])
    print(f"{d['image']}  ({d['width']}x{d['height']}, {d['count']} text items)")
    if row:
        print("fader row (left→right; pair with the mixer channel order by hand):")
        print("  " + "  ".join(t["text"] for t in row))
    else:
        print("no fader-row dB tokens found (view saved without the mixer?)")
    print("(--json for every token with positions)")
    return 0


def cmd_stacks(args) -> int:
    """Track stacks and the arrange track list; --move puts a track into one."""
    from .services.arrange.stacks import read_stacks, read_tracks

    from .services.arrange.retrack import find_project

    project = find_project(Path(args.logicx))
    if args.move or args.move_out or getattr(args, "flatten", None) or getattr(args, "convert", None):
        return _move_into_stack(args, project)
    from ._edit import written_alternatives
    listed = written_alternatives(project)[0]
    data = listed.read_bytes()
    count = project_metadata(project, listed.parent.name).get("tracks")
    stacks = read_stacks(data, count)


    if args.tracks:
        for row in read_tracks(data, count):
            mark = " (hidden)" if row["hidden"] else ""
            group = "> " if row["grouping"] else "  "
            print(f"  {row['key']:3d} {group}{row['name'] or '?'}{mark}")
        return 0
    if args.json:
        print(json.dumps([{"name": s.name, "kind": s.kind, "track_key": s.track_key,
                           "object_id": s.object_id, "index": s.index, "owner": s.owner,
                           "depth": s.depth, "parent": s.parent,
                           "members": [n for _k, n in s.members]} for s in stacks], indent=2))
        return 0
    from .services.mixer.levels import read_levels
    from .services.arrange.stacks import stack_parents
    parents = stack_parents(data)
    levels = read_levels(data)
    rows = read_tracks(data, count)
    print(f"# {project.stem} — {len(stacks)} stack(s)\n")
    for stack in stacks:
        fader = levels.get(stack.owner, {}).get("fader")
        pad = "    " * stack.depth
        print(f"  {pad}{stack.name}  [{stack.kind}]  {stack.strip} · fader {fader} · "
              f"track {stack.track_key}{'  (in ' + next(s.name for s in stacks if s.object_id == stack.parent) + ')' if stack.parent else ''}")
        for key, name in stack.members:
            oid = next((r["object_id"] for r in rows if r["key"] == key), None)
            moved = "  (dragged in)" if parents.get(oid) == stack.object_id else ""
            nested = "  [stack]" if any(s.object_id == oid for s in stacks) else ""
            print(f"      {pad}{name}{moved}{nested}")
    return 0


def _move_into_stack(args, project: Path) -> int:
    """`--move "Track:Stack"`, `--move-out Track`, `--flatten Stack` and `--convert Stack` —
    writes a copy, never the input; each alternative read with its own track count. Moves in
    come first, then moves out, flattens, converts."""
    from ._edit import CommandError, bump_track_count, edit_copy, object_by_name, written_alternatives
    from .services.arrange.stack_convert import convert_to_summing
    from .services.arrange.stack_moves import flatten_stack, move_out_of_stack, move_to_stack
    from .services.arrange.stacks import read_stacks
    from .services.arrange.trackname import stack_named

    if not args.out:
        print("logic stacks: --move, --move-out, --flatten and --convert need --out")
        return 2

    def named(data, count, name):
        stacks = read_stacks(data, count)
        found = stack_named(stacks, name)
        if found is None:
            have = ", ".join(sorted(s.name for s in stacks))
            raise CommandError(f"no stack named {name!r} (have: {have})")
        return found

    def step(data, count, data_file):
        for pair in args.move or []:
            stacks = read_stacks(data, count)
            track, _, stack = pair.partition(":")
            track_object = object_by_name(data, track, count)
            found = stack_named(stacks, stack)
            if found is None:
                have = ", ".join(sorted(s.name for s in stacks))
                raise CommandError(f"no stack named {stack!r} (have: {have})")
            data = move_to_stack(data, track_object, found.object_id, track_count=count)
            print(f"  {data_file.parent.name}: {track} -> {stack}")
        for track in args.move_out or []:
            moved = move_out_of_stack(data, object_by_name(data, track, count), track_count=count)
            if moved == data:
                raise CommandError(f"{track!r} is already at the top level")
            data = moved
            print(f"  {data_file.parent.name}: {track} one level out")
        for name in getattr(args, "flatten", None) or []:
            found = named(data, count, name)
            try:
                data = flatten_stack(data, found.object_id, track_count=count)
            except ValueError as e:
                raise CommandError(f"{name}: {e}") from None
            count = bump_track_count(data_file, -1)
            print(f"  {data_file.parent.name}: {name} flattened, {len(found.members)} member(s) up a level")
        for name in getattr(args, "convert", None) or []:
            found = named(data, count, name)
            try:
                data, made = convert_to_summing(data, found.object_id, track_count=count)
            except ValueError as e:
                raise CommandError(f"{name}: {e}") from None
            print(f"  {data_file.parent.name}: {name} -> {made['name']} on {made['label']} fed from {made['bus']}; "
                  f"{made['sub']} out of use")
            if made["level_left"] is not None:
                level = "-inf" if made["level_left"] == float("-inf") else f"{made['level_left']:.1f} dB"
                print(f"    {made['sub']}'s fader ({level}) stays on it, as Logic's convert leaves it; "
                      f"{made['label']} is at 0 dB")
        return data

    print(f"in  : {project}")
    try:
        dest = edit_copy(project, Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    written = written_alternatives(dest)[0]
    for stack in read_stacks(written.read_bytes(), project_metadata(dest, written.parent.name).get("tracks")):
        print(f"\n  {stack.name}: {', '.join(n for _k, n in stack.members) or '(empty)'}")
    return 0
