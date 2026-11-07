"""`retrack`: a project's channel-strip references repointed at their tracking versions, by a
project-wide map or one channel at a time, on a copy."""

from __future__ import annotations

import json
from pathlib import Path

from .services.arrange.project_copy import left_line
from .services.arrange.retrack import missing_strips, retrack_bundle
from .services.mixer.library import strip_library


def cmd_retrack(args) -> int:
    """Repoint a project's channel-strip references at their tracking versions."""
    if args.channel:
        return _retrack_channels(args)
    if not args.map:
        print("  --map FILE, or --channel 'LABEL=Name.cst' (repeatable)")
        return 2
    cfg = json.loads(Path(args.map).read_text())
    mapping, category = cfg["mapping"], cfg["category"]
    gone = missing_strips(mapping, strip_library())
    if gone:
        print("REFUSING — mapped strips are not in the library:")
        for g in gone:
            print(f"    {g}")
        return 1
    r = retrack_bundle(Path(args.project), Path(args.out), mapping, category)
    print(f"in  : {r['source']}\nout : {r['dest']}\n")
    for name, rep in r["alternatives"]:
        print(f"  Alternatives/{name}: {rep['repointed']} reference(s) repointed")
    for name, word in r["left"].items():
        print(f"  {left_line(name, word)}")
    for old, new in r["changes"]:
        print(f"    {old:32s} -> {new}")
    if r["untouched"]:
        print("\n  left as-is (no mapping): " + ", ".join(r["untouched"]))
    print("\nFile length unchanged — verify with: bin/run logic project <out project>")
    return 0


def _retrack_channels(args) -> int:
    """`--channel 'Audio 5=Rack 1.cst'`: each named channel's reference repointed on its own,
    so channels that share a name can part ways. The strips must be in the library."""
    from ._edit import CommandError, edit_copy
    from .services.mixer.binding import channels
    from .services.arrange.retrack import retrack_channels
    wanted = {}
    for spec in args.channel:
        label, _, name = spec.partition("=")
        if not label.strip() or not name.strip():
            print(f"  bad --channel {spec!r}: use LABEL=Name.cst")
            return 2
        wanted[label.strip()] = name.strip()
    gone = missing_strips({k: v for k, v in wanted.items()}, strip_library())
    if gone:
        print("REFUSING — strips are not in the library: " + ", ".join(gone))
        return 1

    def step(data, _count, _file):
        by_label = {c.label: o for o, c in channels(data).items()}
        unknown = [label for label in wanted if label not in by_label]
        if unknown:
            raise CommandError(f"no channel labelled {unknown}")
        out, report = retrack_channels(data, {by_label[label]: name for label, name in wanted.items()})
        for owner, old, new in report["changes"]:
            print(f"  {old:32s} -> {new}  (owner {owner})")
        return out

    try:
        dest = edit_copy(Path(args.project), Path(args.out), step)
    except CommandError as e:
        print(f"  {e}")
        return 1
    print(f"\nout : {dest}\nA label, not a chain — verify the Setting buttons in Logic.")
    return 0


def register(sub) -> None:
    rt = sub.add_parser("retrack", help="repoint a project's strip references (writes a copy)")
    rt.add_argument("project", help="a .logicx, or a folder containing one")
    rt.add_argument("--out", required=True, help="output directory")
    rt.add_argument("--map", help="JSON mapping config (name -> name, project-wide)")
    rt.add_argument("--channel", action="append", metavar="LABEL=NAME.cst",
                    help="repoint one channel's reference (repeatable); the folder stays")
    rt.set_defaults(func=cmd_retrack)
