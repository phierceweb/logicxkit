"""Diagnostic commands: recdiff · manifest. Read-only; they report and never write."""

from __future__ import annotations

import json
from pathlib import Path

from .services.recdiff import diff_records, load_project_data, noise_mask, summary


def cmd_recdiff(args) -> int:
    """Positional record diff of two saves; --baseline X Y masks a no-op pair's noise."""
    a, b = load_project_data(args.a), load_project_data(args.b)
    mask = None
    if args.baseline:
        mask = noise_mask(load_project_data(args.baseline[0]),
                          load_project_data(args.baseline[1]))
    diff = diff_records(a, b, mask=mask)
    differs = bool(diff.added or diff.removed or diff.changed)
    if args.json:
        print(json.dumps({
            "summary": summary(diff),
            "added": [e.__dict__ | {"tag": e.tag.decode("latin-1")} for e in diff.added],
            "removed": [e.__dict__ | {"tag": e.tag.decode("latin-1")} for e in diff.removed],
            "changed": [c.__dict__ | {"tag": c.tag.decode("latin-1")} for c in diff.changed],
        }, indent=2))
        return 1 if differs else 0
    print(f"a: {Path(args.a)}  ({len(a)} bytes)\nb: {Path(args.b)}  ({len(b)} bytes)")
    if mask:
        print(f"mask: {sum(len(v) for v in mask.values())} offset(s) over "
              f"{', '.join(t.decode('latin-1') for t in mask)}")
    s = summary(diff)
    print(f"\nsame {s['same']} · changed {sum(s['changed'].values())} · "
          f"added {sum(s['added'].values())} · removed {sum(s['removed'].values())}")
    for name in ("added", "removed"):
        for e in getattr(diff, name):
            print(f"  {name:8s} #{e.index:5d} {e.tag.decode('latin-1')} owner {e.owner} "
                  f"key {e.key} size {e.size}")
    for c in diff.changed:
        offs = ", ".join(str(o) for o in c.offsets[:12]) + (" …" if len(c.offsets) > 12 else "")
        size = f" size {c.size_a} -> {c.size_b}" if c.size_a != c.size_b else ""
        print(f"  changed  #{c.index:5d} {c.tag.decode('latin-1')} owner {c.owner} key {c.key}"
              f"{size}  @ {offs}")
    return 1 if differs else 0


def cmd_manifest(args) -> int:
    """Tracks, stacks and channels of a project from decoded fields only."""
    from .services.manifest import read_manifest
    from .services.retrack import find_project

    m = read_manifest(find_project(Path(args.project)))
    if args.json:
        print(json.dumps(m, indent=2))
        return 0
    md = m["metadata"]
    print(f"# {m['name']} — {md.get('tracks')} tracks · {md.get('logic_version', '?')}\n")
    print("tracks")
    for t in m["tracks"]:
        mark = " (hidden)" if t["hidden"] else ""
        where = f"  in {t['stack']}" if t["stack"] else ""
        print(f"  {t['key']:3d} {t['name'] or '?':16s} {t['label'] or '-':11s}{where}{mark}")
    print("\nstacks")
    for s in m["stacks"]:
        print(f"  {s['name']:12s} Sub {s['index']}  fader {s['fader']}  "
              f"{len(s['members'])} member(s)")
    print("\nchannels")
    for c in m["channels"]:
        sends = " ".join(f"->{s['to'] or s['bus']}" for s in c["sends"])
        chain = " → ".join(p for p, _pre in c["chain"])
        print(f"  {c['label']:11s} {c['object'] or '':14s} out {c['output'] or '-':11s} "
              f"f{c['fader']} p{c['pan']} w{c['width']}  {sends:22s} {chain}")
    return 0


def register(sub) -> None:
    rd = sub.add_parser("recdiff", help="positional record diff of two project saves")
    rd.add_argument("a", help="ProjectData file, backup NN dir, or .logicx")
    rd.add_argument("b")
    rd.add_argument("--baseline", nargs=2, metavar=("X", "Y"),
                    help="a no-op save pair of the same file; its differences are masked")
    rd.add_argument("--json", action="store_true")
    rd.set_defaults(func=cmd_recdiff)
    mf = sub.add_parser("manifest", help="tracks, stacks and channels from decoded fields")
    mf.add_argument("project", help="a .logicx, or a folder containing one")
    mf.add_argument("--json", action="store_true")
    mf.set_defaults(func=cmd_manifest)
