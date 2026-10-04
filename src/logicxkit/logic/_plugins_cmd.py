"""`logic plugins` — the plug-ins a project (or every project under a folder) references, and
which of them this Mac lacks."""

from __future__ import annotations

import json
import plistlib
import time
from pathlib import Path

from pf_core.utils.io import atomic_write_bytes

from ._edit import first_project_data
from .services.mixer.plugins import installed_components, project_plugins, validate_components, verdict
from .services.arrange.retrack import find_project

CACHE_AGE = 24 * 3600               # seconds a kept registry scan is used
COMPONENT_FOLDERS = ("/Library/Audio/Plug-Ins/Components", "~/Library/Audio/Plug-Ins/Components")


def _cache_file() -> Path:
    return Path.home() / "Library/Caches/logicxkit/auval-registry.json"


def _bundles() -> list[Path]:
    out = []
    for folder in COMPONENT_FOLDERS:
        try:
            out += sorted(Path(folder).expanduser().iterdir())
        except OSError:
            continue
    return out


def _component_folders() -> list:
    """The two Components folders' entries with their change times: what an install or a removal
    moves. An Audio Unit that ships inside an app shows in neither."""
    out = []
    for bundle in _bundles():
        try:
            out.append([str(bundle), bundle.stat().st_mtime_ns])
        except OSError:
            continue
    return out


def _declared() -> set[tuple[str, str, str]]:
    """The components the bundles in the Components folders say they register."""
    out = set()
    for bundle in _bundles():
        try:
            with (bundle / "Contents/Info.plist").open("rb") as f:
                listed = plistlib.load(f).get("AudioComponents", [])
        except (OSError, ValueError):
            continue
        out |= {(c.get("type"), c.get("subtype"), c.get("manufacturer")) for c in listed if isinstance(c, dict)}
    return out


def _kept_scan() -> tuple[set[tuple[str, str, str]], float] | None:
    """The kept registry scan and when it was made: under a day old, the Components folders as
    they were then."""
    try:
        kept = json.loads(_cache_file().read_text())
        if kept["folders"] == _component_folders() and 0 <= time.time() - kept["at"] < CACHE_AGE:
            return {tuple(c) for c in kept["components"]}, kept["at"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _keep_scan(found: set[tuple[str, str, str]]) -> None:
    """A cache that cannot be written only costs the next scan."""
    try:
        cache = _cache_file()
        cache.parent.mkdir(parents=True, exist_ok=True)
        kept = {"at": time.time(), "folders": _component_folders(), "components": sorted(found)}
        atomic_write_bytes(cache, json.dumps(kept).encode())
    except OSError:
        pass


def _projects(path: Path) -> list[Path]:
    if path.suffix == ".logicx" or (path / "Alternatives").is_dir():
        return [find_project(path)]
    return sorted(p for p in path.rglob("*.logicx") if (p / "Alternatives").is_dir())


def _registry(wanted: set, *, rescan: bool, quiet: bool) -> set[tuple[str, str, str]] | None:
    """What `auval -a` lists: the kept scan, or a new one, run only when a slot needs it. A scan
    that leaves out a wanted component a Components folder holds is neither used nor kept, and
    the run says so: auval lists what the system has registered so far, and that can be part
    of it."""
    kept = None if rescan else _kept_scan()
    if kept is not None and not (wanted - kept[0]) & _declared():
        if not quiet:
            print(f"third-party check from the auval scan of {time.strftime('%Y-%m-%d %H:%M', time.localtime(kept[1]))}"
                  " (--rescan runs it again)")
        return kept[0]
    found = installed_components()
    if found is None:
        return None
    unlisted = (wanted - found) & _declared()
    if not unlisted:
        _keep_scan(found)
    elif not quiet:
        print(f"auval does not list {len(unlisted)} plug-in(s) that a Components folder holds — the system may "
              "still be registering Audio Units, so they read as missing below; run it again")
    return found


def cmd_plugins(args) -> int:
    projects = _projects(Path(args.project))
    refs_by_project = {project: project_plugins(first_project_data(project)) for project in projects}
    third_party = any(r.component and not r.native for refs in refs_by_project.values() for r in refs)
    wanted = {r.component for refs in refs_by_project.values() for r in refs if r.component and not r.native}
    installed = _registry(wanted, rescan=args.rescan, quiet=args.json) if third_party else set()
    validated = None
    if args.validate and installed is not None:
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
                                    "auval -a scan of every installed Audio Unit; with many installed it "
                                    "takes 25 seconds or more, so the scan is kept for a day while the two "
                                    "Components folders stay as they are.")
    ap.add_argument("project", help="a .logicx bundle, or a folder to scan")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="open each listed third-party component with auval -v; a registry entry whose bundle is broken reads as installed otherwise")
    ap.add_argument("--rescan", action="store_true",
                    help="run the auval -a scan again instead of using the kept one (an Audio Unit inside an app "
                         "does not show in the Components folders)")
    ap.set_defaults(func=cmd_plugins)
