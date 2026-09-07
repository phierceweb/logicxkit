"""au CLI — decode plugin presets and embedded strip states.

    logicxkit au preset <file>                 .ffp / .aupreset / .pst / extracted .plist
    logicxkit au strip  <file.cst|Song.logicx> every embedded 3rd-party state
    logicxkit au params <type> <subtype> <manu>  live AU parameter table (needs swift)
    logicxkit au tables                        list the AU parameter tables in the data root

Decode ladder per state: NDSP -> JUCE decoders, Waves -> static XPst, else the
headless AU host (--no-host to force the static table join).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from logicxkit.au._views import format_preset, format_strip
from logicxkit.au.services.host import AuHost
from logicxkit.au.services.report import decode_preset_bytes, decode_strip_path
from logicxkit.au.services.tables import available_tables


def _host_or_none(args) -> AuHost | None:
    if args.no_host or not AuHost.available():
        return None
    return AuHost()


def _emit(payload, text: str, as_json: bool) -> int:
    print(json.dumps(payload, indent=2) if as_json else text)
    return 0


def cmd_preset(args) -> int:
    p = Path(args.file).expanduser()   # every real preset lives under ~/Library or ~/Music
    out = decode_preset_bytes(p.read_bytes(), suffix=p.suffix.lower(),
                              host=_host_or_none(args), name_hint=p.stem)
    return _emit(out, format_preset(out, args.all), args.json)


def cmd_strip(args) -> int:
    states = decode_strip_path(args.file, host=_host_or_none(args))
    return _emit(states, format_strip(states, args.all), args.json)


def cmd_params(args) -> int:
    dump = AuHost().list_params(args.type, args.subtype, args.manufacturer)
    payload = {"component": dump.component, "params": [vars(p) for p in dump.params]}
    text = "\n".join(f"[{p.id:>5}] {p.name:<44} {p.unit:<8} "
                     f"{p.min:.4g}..{p.max:.4g} (default {p.default:.4g})"
                     for p in dump.params)
    return _emit(payload, f"{dump.component} — {len(dump.params)} params\n{text}", args.json)


def cmd_tables(args) -> int:
    names = available_tables()
    print("\n".join(names) if names else "no tables checked in")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="logicxkit au", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--all", action="store_true", help="show unchanged params too")
        p.add_argument("--json", action="store_true")
        p.add_argument("--no-host", action="store_true",
                       help="skip the AU host; static decode only")

    p = sub.add_parser("preset", help="decode a preset file")
    p.add_argument("file")
    common(p)
    p.set_defaults(fn=cmd_preset)

    p = sub.add_parser("strip", help="decode embedded states in a .cst/.pst/.logicx")
    p.add_argument("file")
    common(p)
    p.set_defaults(fn=cmd_strip)

    p = sub.add_parser("params", help="live AU parameter table")
    p.add_argument("type")
    p.add_argument("subtype")
    p.add_argument("manufacturer")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_params)

    p = sub.add_parser("tables", help="list the AU parameter tables in the data root")
    p.set_defaults(fn=cmd_tables)

    args = ap.parse_args(argv)
    return args.fn(args)
