"""`build`, `verify`, `pst` and `decode`: `.cst` strips and `.pst` settings from a spec, the round
trip checked without writing, and a strip's EQ and Compressor dumped. `decode` prints the human
dump to stderr and, with ``--json``, a spec stub to stdout, so decode -> edit -> rebuild can pipe
the JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pw_foundation.utils.io import atomic_write_bytes

from ._binary import find_blocks, identify_plugin, read_block_floats
from .services.mixer.comp import decode_comp
from .services.mixer.eq import BAND_ORDER, decode_eq
from .services.mixer.library import under_live_library
from .services.translate.pst import output_root as pst_output_root
from .services.translate.pst import write_psts
from .services.mixer.spec import assemble, load_spec


def _byte_loader():
    """path -> bytes, cached; shared by every preset in a spec run."""
    cache: dict[Path, bytes] = {}

    def load(path: Path) -> bytes:
        if path not in cache:
            cache[path] = Path(path).read_bytes()
        return cache[path]

    return load


def _live_library_blocked(path, install: bool, what: str, elsewhere: str) -> bool:
    """Logic's own library is opt-in: a spec must not reach it by omitting a key."""
    if not under_live_library(path):
        return False
    if not install:
        print(f"logicxkit: refusing to write into Logic's own library at {path}.\n"
              f"  This is the library Logic loads, not a scratch directory. Pass --install to "
              f"write {what} there on purpose,\n"
              f"  or set {elsewhere} (or an absolute output_dir) to write elsewhere.",
              file=sys.stderr)
        return True
    print(f"logicxkit: installing {what} into Logic's own library at {path}.", file=sys.stderr)
    return False


def cmd_build(args) -> int:
    """Build `.cst` strips from a spec; an existing file is kept unless `--overwrite`, and a failed
    preset exits 1."""
    spec = load_spec(Path(args.spec))
    load = _byte_loader()
    out_dir = spec["_output_dir"]
    if _live_library_blocked(out_dir, args.install, "strips", "'output_root'"):
        return 2
    print(f"Template : {spec.get('template', '(per-preset)')}")
    print(f"Output   : {out_dir}\n")
    written = skipped = failed = 0
    for name, preset in spec["presets"].items():
        dest = out_dir / f"{name}.cst"
        if dest.exists() and not args.overwrite:
            print(f"  --  {name}.cst exists; pass --overwrite to replace it")
            skipped += 1
            continue
        try:
            data = assemble(spec, preset, load, name)
        except FileNotFoundError as e:
            from .services.mixer.library import strip_library
            root = spec.get("strip_root") or strip_library()
            print(f"  !!  {name}: no strip at {e.filename} — strips resolve under {root}; set the spec's "
                  "'strip_root' or LOGICXKIT_STRIP_ROOT (a checkout has the examples' under tests/corpus/strips)")
            failed += 1
            continue
        except Exception as e:
            print(f"  !!  {name}: {e}")
            failed += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(dest, data)
        print(f"  OK  {name}.cst")
        written += 1
    print(f"\nDone — {written} written, {skipped} skipped, {failed} failed.")
    if written:
        print("Load in Logic: right-click a channel strip → Load Channel Strip Setting…")
    return 1 if failed else 0


def cmd_verify(args) -> int:
    spec = load_spec(Path(args.spec))
    load = _byte_loader()
    ok = True
    for name, preset in spec["presets"].items():
        data = assemble(spec, preset, load, name)
        got_eq = got_comp = None
        for idx, _s, n in find_blocks(data):
            plug = identify_plugin(data, idx)
            if plug == "Channel EQ" and got_eq is None:
                got_eq = decode_eq(read_block_floats(data, idx, n))
            elif plug == "Compressor" and got_comp is None:
                got_comp = decode_comp(read_block_floats(data, idx, n))

        issues = []
        if "comp" in preset:
            want = preset["comp"]
            for k in ("threshold", "ratio", "attack", "release"):
                if abs(got_comp[k] - float(want[k])) > 0.01:
                    issues.append(f"comp.{k} want={want[k]} got={got_comp[k]}")
            if got_comp["circuit"] != want.get("circuit", "Platinum"):
                issues.append(f"comp.circuit want={want.get('circuit')} got={got_comp['circuit']}")
        if "eq" in preset:
            for role, p in preset["eq"].items():
                if role == "master_gain":
                    continue
                if role not in got_eq:
                    issues.append(f"eq.{role} missing after round-trip")
                elif abs(got_eq[role]["freq"] - float(p["freq"])) > 0.5:
                    issues.append(f"eq.{role}.freq want={p['freq']} got={got_eq[role]['freq']}")

        ok = ok and not issues
        print(f"  {'OK' if not issues else '!!'}  {name}"
              + ("" if not issues else "  — " + "; ".join(issues)))
    print("\nALL ROUND-TRIPS OK" if ok else "\nSOME PRESETS FAILED ROUND-TRIP")
    return 0 if ok else 1


def cmd_pst(args) -> int:
    """Build single-plugin .pst settings — no routing attached, unlike a .cst."""
    spec = json.loads(Path(args.spec).read_text())
    root = pst_output_root(spec)
    if _live_library_blocked(root, args.install, "settings", "'output_root'"):
        return 2
    written = failed = 0
    for dest, status in write_psts(spec, overwrite=args.overwrite):
        mark = "OK " if status == "written" else "!! " if status.startswith("FAILED") else "-- "
        print(f"  {mark} {dest.parent.name}/{dest.name}  {status}")
        written += status == "written"
        failed += status.startswith("FAILED")
    print(f"\nDone — {written} preset(s)" + (f", {failed} failed" if failed else "")
          + ". In Logic: plugin window → Settings menu → the preset name.")
    return 1 if failed else 0


def cmd_decode(args) -> int:
    path = Path(args.file)
    data = path.read_bytes()
    eq_spec = comp_spec = None
    print(f"# {path.name}", file=sys.stderr)
    for idx, _size, n in find_blocks(data):
        plug = identify_plugin(data, idx)
        floats = read_block_floats(data, idx, n)
        if plug == "Channel EQ" and eq_spec is None:
            eq_spec = decode_eq(floats)
        elif plug == "Compressor" and comp_spec is None:
            comp_spec = decode_comp(floats)
        if not args.json:
            print(f"\n[{plug}]  @0x{idx:x}  {n} floats", file=sys.stderr)
            if plug == "Channel EQ":
                for role in BAND_ORDER:
                    i = BAND_ORDER.index(role) * 4
                    q, en, fr, g = floats[i:i + 4]
                    if en > 0.5:
                        print(f"    {role:11s} f={fr:8.0f}Hz  gain/slope={g:6.1f}  Q={q:.2f}",
                              file=sys.stderr)
                if len(floats) > 32:
                    print(f"    master_gain = {floats[32]:.2f} dB", file=sys.stderr)
            elif plug == "Compressor":
                for k, v in decode_comp(floats).items():
                    print(f"    {k:14s} = {v}", file=sys.stderr)

    if args.json:
        entry = {}
        if eq_spec:
            entry["eq"] = eq_spec
        if comp_spec:
            entry["comp"] = comp_spec
        print(json.dumps({path.stem: entry}, indent=2))
    return 0


def register(sub) -> None:
    b = sub.add_parser("build", help="build .cst strips from a JSON spec")
    b.add_argument("spec")
    b.add_argument("--overwrite", action="store_true", help="replace existing .cst files")
    b.add_argument("--install", action="store_true",
                   help="allow writing into Logic's own library (refused without it)")
    b.set_defaults(func=cmd_build)
    v = sub.add_parser("verify", help="round-trip check a spec without writing files")
    v.add_argument("spec")
    v.set_defaults(func=cmd_verify)
    ps = sub.add_parser("pst", help="build single-plugin .pst settings from a spec")
    ps.add_argument("spec")
    ps.add_argument("--overwrite", action="store_true", help="replace existing .pst files")
    ps.add_argument("--install", action="store_true",
                    help="allow writing into Logic's own library (refused without it)")
    ps.set_defaults(func=cmd_pst)
    d = sub.add_parser("decode", help="dump EQ/Comp params from a .cst or .pst")
    d.add_argument("file")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_decode)
