"""`prefs`: read Logic's own settings (the behaviours no project carries), set them by name
while Logic is closed, export and apply a set, or make a project's control bar the default."""

from __future__ import annotations

import json
from pathlib import Path

from .services.prefs import (
    BY_NAME, SETTINGS, backup, controlbar_default, parse_value, read_settings, write_controlbar_default,
    write_settings,
)


def _match(name: str) -> str:
    wanted = name.strip().lower().replace("_", " ")
    hits = [s.name for s in SETTINGS if s.name.lower() == wanted]
    if not hits:
        hits = [s.name for s in SETTINGS if wanted in s.name.lower()]
    if len(hits) != 1:
        raise ValueError(f"{name!r}: {'no' if not hits else 'more than one'} setting matches; "
                         f"choose from {', '.join(s.name for s in SETTINGS)}")
    return hits[0]


def _print(state: dict, pane: str | None = None) -> None:
    """The settings grouped by pane; ``pane`` keeps only panes whose label contains it."""
    wanted = (pane or "").strip().lower()
    last = None
    for name, value in state.items():
        label = BY_NAME[name].pane
        if wanted and wanted not in label.lower():
            continue
        if label != last:
            print(f"\n{label}")
            last = label
        shown = "unset" if value is None else (("on" if value else "off") if isinstance(value, bool) else str(value))
        print(f"  {name:60} {shown}")


def cmd_prefs(args) -> int:
    if not (args.set or args.apply or args.controlbar_from or args.export):
        _print(read_settings(), args.pane)
        default = controlbar_default()
        print(f"\n  control bar default: {'set' if default else 'none saved'}")
        return 0
    try:
        want: dict[str, bool | int] = {}
        for spec in args.set or []:
            if "=" not in spec:
                raise ValueError(f"{spec!r}: write NAME=on or NAME=off")
            name, _eq, text = spec.partition("=")
            want[_match(name)] = parse_value(_match(name), text)
        if args.apply:
            loaded = json.loads(Path(args.apply).read_text())
            want.update({_match(k): parse_value(_match(k), str(v)) for k, v in loaded.items()})
        if args.export:
            state = {k: v for k, v in read_settings().items() if v is not None}
            Path(args.export).write_text(json.dumps(state, indent=2) + "\n")
            print(f"wrote : {args.export}")
            if not (want or args.controlbar_from):
                return 0
        saved = backup(Path(args.backup_dir))
        print(f"backup: {saved.resolve()}")
        if want:
            write_settings(want)
        if args.controlbar_from:
            from .services.controlbar import alternative_dirs, read_layout
            from .services.retrack import find_project
            src = find_project(Path(args.controlbar_from))
            alts = alternative_dirs(src)
            if not alts:
                raise ValueError(f"{src}: no alternative carries a DisplayState.plist")
            write_controlbar_default(read_layout(alts[0])[0])
            print(f"control bar default taken from {src}")
    except (ValueError, RuntimeError, OSError) as e:
        print(f"  {e}")
        return 2
    _print(read_settings(), args.pane)
    print("\nTakes effect when Logic next starts.")
    return 0


def register(sub) -> None:
    pr = sub.add_parser("prefs", help="Logic's own settings: show, set by name (Logic closed), "
                        "export/apply a set, or make a project's control bar the default")
    pr.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="e.g. 'Marquee tool click zones=on', 'Right mouse button=Opens Tool Menu', 'undo=200'")
    pr.add_argument("--export", metavar="FILE", help="write the known settings as JSON")
    pr.add_argument("--apply", metavar="FILE", help="set every setting named in this JSON file")
    pr.add_argument("--controlbar-from", dest="controlbar_from", metavar="PROJECT",
                    help="make this project's control bar the default for new projects")
    pr.add_argument("--pane", help="list only panes whose name contains this, e.g. 'View' or 'MIDI > Sync'")
    pr.add_argument("--backup-dir", default="prefs-backup",
                    help="where the pre-write copy goes (relative to the working directory)")
    pr.set_defaults(func=cmd_prefs)
