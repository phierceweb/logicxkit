"""`logic sessionplayer` — each Session Player region's drummer, preset, settings and how much
it generated."""

from __future__ import annotations

import json
from pathlib import Path

from ._edit import first_project_data
from .services.arrange.retrack import find_project
from .services.regions.sessionplayer import SETTINGS_ROLES, read_session_players


def cmd_sessionplayer(args) -> int:
    project = find_project(Path(args.project))
    players = read_session_players(first_project_data(project))
    if args.json:
        print(json.dumps([{"region": p.region, "character": p.character, "preset": p.preset, "settings": p.settings,
                           "memento": p.memento, "notes": p.notes, "generated_bars": p.generated_bars} for p in players], indent=1))
        return 0
    print(f"{project.name}: {len(players)} Session Player region(s)")
    for p in players:
        print(f"  {p.region!r}: {p.character} — preset {p.preset!r}{' (edited)' if p.settings.get('PresetDirty') else ''}; {p.notes} notes over {p.generated_bars} bars")
        for key, role in SETTINGS_ROLES.items():
            if key in p.settings:
                v = p.settings[key]
                print(f"      {role:16s} {v:.2f}" if isinstance(v, float) else f"      {role:16s} {v}")
        on = [k for k in ("kickEnabled", "snareEnabled", "systemsEnabled", "FollowEnabled", "manualMode") if p.settings.get(k)]
        print(f"      {'on':16s} {', '.join(on) or '-'}")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("sessionplayer", help="Session Player regions: drummer, preset, settings, generated notes")
    ap.add_argument("project")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_sessionplayer)
