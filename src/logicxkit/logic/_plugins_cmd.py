"""`logic plugins` — the plug-ins a project (or every project under a folder) references, and
which of them this Mac lacks."""

from __future__ import annotations

import json
from pathlib import Path

from ._edit import first_project_data
from .services.plugins import installed_components, project_plugins, validate_components, verdict
from .services.retrack import find_project


def _projects(path: Path) -> list[Path]:
    if path.suffix == ".logicx" or (path / "Alternatives").is_dir():
        return [find_project(path)]
    return sorted(p for p in path.rglob("*.logicx") if (p / "Alternatives").is_dir())


def cmd_plugins(args) -> int:
    projects = _projects(Path(args.project))
    refs_by_project = {project: project_plugins(first_project_data(project)) for project in projects}
    third_party = any(r.component and not r.native for refs in refs_by_project.values() for r in refs)
    installed = installed_components() if third_party else set()      # the registry scan only when a slot needs it
    validated = None
    if args.validate and installed is not None:
        wanted = {r.component for refs in refs_by_project.values() for r in refs if r.component and not r.native}
        progress = None if args.json else (lambda comp: print(f"  auval -v {' '.join(comp)} …", flush=True))
        validated = validate_components(wanted & installed, progress=progress)
    report = []
    for project in projects:
        v = verdict(refs_by_project[project], installed, validated)
        report.append({"project": str(project), "clean": v.clean,
                       "slots": [{"channel": r.channel, "key": r.key, "name": r.name, "native": r.native,
                                  "component": list(r.component) if r.component else None, "status": s,
                                  "side_chain": r.side_chain}
                                 for r, s in v.slots]})
        if args.json:
            continue
        broken = sum(1 for _r, s in v.slots if s == "broken")
        summary = "clean" if v.clean else f"{len(v.missing) - broken} missing" + (f", {broken} broken" if broken else "")
        if installed is None:
            summary = "third-party status unknown (no auval on this machine, or its registry scan timed out)"
        print(f"{project.name}: {len(v.slots)} plug-in slot(s), {summary}")
        if len(projects) == 1 or not v.clean:
            for r, status in v.slots:
                if len(projects) > 1 and status not in ("missing", "broken"):
                    continue
                ident = " ".join(r.component) if r.component else "native"
                tail = f"  side chain: {r.side_chain}" if r.side_chain else ""
                print(f"  {r.channel:16s} key {r.key:2d}  {r.name:28s} {ident:16s} {status}{tail}")
    if args.json:
        print(json.dumps(report, indent=1))
    elif len(projects) > 1:
        bad = [r for r in report if not r["clean"]]
        print(f"\n{len(projects)} project(s), {len(bad)} with missing plug-ins")
    return 0 if all(r["clean"] for r in report) else 1


def register(sub) -> None:
    ap = sub.add_parser("plugins", help="which plug-ins a project references and which this Mac lacks",
                        description="Every plug-in the project's slots reference, and which third-party "
                                    "ones this Mac lacks. Checking a third-party plug-in runs Apple's "
                                    "auval -a scan of every installed Audio Unit, once per run; with many "
                                    "installed it takes 25 seconds or more.")
    ap.add_argument("project", help="a .logicx bundle, or a folder to scan")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="open each listed third-party component with auval -v; a registry entry whose bundle is broken reads as installed otherwise")
    ap.set_defaults(func=cmd_plugins)
