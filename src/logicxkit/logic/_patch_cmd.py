"""`logic patch` — what a Library patch bundle holds: nodes, channels, strips, plug-ins; `--build`
makes one from a `.cst`, into Logic's own library only with `--install`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .services.mixer.library import under_live_library
from .services.mixer.patch import build_patch, read_patch


def _patches(path: Path) -> list[Path]:
    if path.suffix == ".patch":
        return [path]
    return sorted(p for p in path.rglob("*.patch") if p.is_dir())


def _build(args) -> int:
    out_dir = Path(args.out).expanduser()
    if under_live_library(out_dir):
        if not args.install:
            print(f"logicxkit: refusing to write into Logic's own library at {out_dir}.\n"
                  "  This is the library Logic loads, not a scratch directory. Pass --install to write the patch "
                  "there on purpose, or give --out elsewhere.", file=sys.stderr)
            return 2
        print(f"logicxkit: installing a patch into Logic's own library at {out_dir}.", file=sys.stderr)
    try:
        dest = build_patch(Path(args.build).expanduser(), name=args.name, out_dir=out_dir, overwrite=args.overwrite)
    except (OSError, ValueError) as e:
        print(f"  {e}")
        return 1
    try:
        (ch,) = read_patch(dest).channels
        print(f"out : {dest}\n  {ch.name}: {' → '.join(ch.plugins) or '(no plug-ins)'}")
    except (OSError, ValueError) as e:
        print(f"  {dest} was written but does not read back: {e}")
        return 1
    return 0


def cmd_patch(args) -> int:
    if args.build:
        if not (args.name and args.out):
            print("  --build needs --name and --out")
            return 2
        return _build(args)
    if not args.patch:
        print("  a .patch bundle or a folder is needed (or --build)")
        return 2
    report = []
    for p in _patches(Path(args.patch)):
        try:
            patch = read_patch(p)
        except (ValueError, OSError, KeyError) as e:
            print(f"{p.name}: {e}")
            continue
        report.append({"path": str(patch.path), "name": patch.name, "nodes": patch.nodes,
                       "channels": [vars(c) for c in patch.channels]})
        if args.json:
            continue
        print(f"{patch.name}: {len(patch.nodes)} node(s) {patch.nodes}, {len(patch.channels)} channel(s)")
        for c in patch.channels:
            vol = f"{c.volume:.3f}" if c.volume is not None else (f"{c.fader}" if c.fader is not None else "-")
            pan = c.pan if c.pan is not None else (c.pan_byte if c.pan_byte is not None else "-")
            width = {1: "mono", 2: "stereo"}.get(c.width, str(c.width))
            flags = "".join(f for f, on in (("M", c.muted), ("S", c.solo)) if on) or "-"
            print(f"  {c.name:20s} {c.strip or '-':28s} vol {vol:6s} pan {pan!s:6s} {width:6s} -> {c.output or '-':10s} {flags:2s} {' → '.join(c.plugins) or '(no plug-ins)'}")
    if args.json:
        print(json.dumps(report, indent=1))
    return 0 if report else 1


def register(sub) -> None:
    ap = sub.add_parser("patch", help="read a Library .patch bundle, or every one under a folder")
    ap.add_argument("patch", nargs="?", help="a .patch bundle, or a folder to scan")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--build", metavar="STRIP.cst", help="make a patch from this channel strip")
    ap.add_argument("--name", help="the patch's name (with --build)")
    ap.add_argument("--out", help="directory to write the .patch into (with --build)")
    ap.add_argument("--install", action="store_true", help="allow --out inside Logic's own library")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing .patch")
    ap.set_defaults(func=cmd_patch)
