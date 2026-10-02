"""argparse CLI for `logicxkit logic`. `decode` prints the human dump to stderr and, with
``--json``, a spec stub to stdout, so decode -> edit -> rebuild can pipe the JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


from pf_core.utils.io import atomic_write_bytes

from ._binary import find_blocks, identify_plugin, read_block_floats
from ._add_plugin_cmd import register as register_add_plugin
from ._donors_cmd import register as register_donors
from ._settings_cmd import register as register_settings
from ._apply import register as register_apply
from ._apply_template import register as register_template
from ._apply_tracks import register as register_tracks
from ._beats_cmd import register as register_beats
from ._capabilities import emit_notice
from ._capabilities import register as register_capabilities
from ._controlbar import register as register_controlbar
from ._toolbar import register as register_toolbar
from ._modes import register as register_modes
from ._metronome import register as register_metronome
from ._width import register as register_width
from ._groups import register as register_groups
from ._song import register as register_song
from ._header import register as register_header
from ._levels_cmd import register as register_levels
from ._prefs import register as register_prefs
from ._chains_cmd import register as register_chains
from ._midi_cmd import register as register_midi
from ._migrate_cmd import register as register_migrate
from ._plugins_cmd import register as register_plugins
from ._patch_cmd import register as register_patch
from ._regions_cmd import register as register_regions
from ._markers_cmd import register as register_markers
from ._automation_cmd import register as register_automation
from ._swap_plugin_cmd import register as register_swap_plugin
from ._tracking_chains_cmd import register as register_tracking_chains
from ._sessionplayer_cmd import register as register_sessionplayer
from ._quantize_cmd import register as register_quantize
from ._diagnose import register as register_diagnose
from ._drums_to_midi_cmd import register as register_drums_to_midi
from ._inspect import (
    cmd_diff,
    cmd_image,
    cmd_neural,
    cmd_ocr,
    cmd_project,
    cmd_stacks,
)
from .services.comp import decode_comp
from .services.library import strip_library, under_live_library
from .services.eq import BAND_ORDER, decode_eq
from .services.pst import output_root as pst_output_root
from .services.pst import write_psts
from .services.retrack import missing_strips, retrack_bundle
from .services.spec import assemble, load_spec

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
            from .services.library import strip_library
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
    from .services.binding import channels
    from .services.retrack import retrack_channels
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


# Every path argument, so a quoted "~/Music/…" is a path and not a directory named "~".
_PATH_ARGS = ("project", "logicx", "out", "to", "spec", "library", "file", "image", "map",
              "propose_map", "export", "from_", "config", "template", "src", "dst", "a", "b",
              "baseline", "apply", "backup_dir", "controlbar_from", "build", "audio",
              "save_map", "db", "maps")


def _expand(value):
    return str(Path(value).expanduser()) if isinstance(value, str) and value.startswith("~") else value


def _expand_paths(args) -> None:
    for name in _PATH_ARGS:
        if not hasattr(args, name):
            continue
        value = getattr(args, name)
        setattr(args, name, [_expand(v) for v in value] if isinstance(value, list) else _expand(value))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="logicxkit logic",
                                 description="Build/decode Logic native EQ+Compressor strips.")
    sub = ap.add_subparsers(dest="cmd", required=True)
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
    rt = sub.add_parser("retrack", help="repoint a project's strip references (writes a copy)")
    rt.add_argument("project", help="a .logicx, or a folder containing one")
    rt.add_argument("--out", required=True, help="output directory")
    rt.add_argument("--map", help="JSON mapping config (name -> name, project-wide)")
    rt.add_argument("--channel", action="append", metavar="LABEL=NAME.cst",
                    help="repoint one channel's reference (repeatable); the folder stays")
    rt.set_defaults(func=cmd_retrack)
    register_donors(sub)
    register_add_plugin(sub)
    register_chains(sub)
    register_midi(sub)
    register_beats(sub)
    register_plugins(sub)
    register_patch(sub)
    register_regions(sub)
    register_markers(sub)
    register_sessionplayer(sub)
    register_automation(sub)
    register_swap_plugin(sub)
    register_tracking_chains(sub)
    register_quantize(sub)
    register_drums_to_midi(sub)
    register_settings(sub)
    register_capabilities(sub)
    register_header(sub)
    register_controlbar(sub)
    register_toolbar(sub)
    register_modes(sub)
    register_metronome(sub)
    register_width(sub)
    register_groups(sub)
    register_song(sub)
    register_prefs(sub)
    register_levels(sub)
    st = sub.add_parser("stacks", help="track stacks and the arrange track list")
    st.add_argument("logicx", help="a .logicx, or a folder containing one")
    st.add_argument("--tracks", action="store_true", help="list every track in display order")
    st.add_argument("--json", action="store_true")
    st.add_argument("--move", action="append", metavar="TRACK:STACK",
                    help="move a track into a stack (repeatable); writes a copy")
    st.add_argument("--move-out", action="append", metavar="TRACK",
                    help="move a track one level out of its stack (repeatable); writes a copy")
    st.add_argument("--out", help="output directory, required with --move and --move-out")
    st.set_defaults(func=cmd_stacks)
    d = sub.add_parser("decode", help="dump EQ/Comp params from a .cst or .pst")
    d.add_argument("file")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_decode)
    p = sub.add_parser("project", help="read-only inventory of a .logicx project")
    p.add_argument("logicx", help="path to a .logicx bundle")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_project)
    nr = sub.add_parser("neural", help="decode Neural DSP knob values from a .cst or .logicx")
    nr.add_argument("file", help="path to a .cst strip or .logicx bundle")
    nr.add_argument("--json", action="store_true")
    nr.set_defaults(func=cmd_neural)
    df = sub.add_parser("diff", help="diff two projects, or one project vs the strip library")
    df.add_argument("a", help=".logicx bundle")
    df.add_argument("b", nargs="?", help="second .logicx bundle")
    df.add_argument("--library", nargs="?", const="", default=None, metavar="DIR",
                    help="compare referenced .cst strips instead "
                         "(default DIR: Channel Strip Settings)")
    df.add_argument("--json", action="store_true")
    df.set_defaults(func=cmd_diff)
    im = sub.add_parser("image", help="extract a bundle's auto-saved WindowImage.jpg")
    im.add_argument("logicx", help="path to a .logicx bundle")
    im.add_argument("-o", "--out", help="output path (default: '<name> - WindowImage.jpg')")
    im.add_argument("--overwrite", action="store_true", help="replace an existing file at the output path")
    im.set_defaults(func=cmd_image)
    oc = sub.add_parser("ocr", help="OCR a WindowImage (or any image) via Apple Vision")
    oc.add_argument("file", help=".logicx bundle or an image file")
    oc.add_argument("--json", action="store_true", help="full token dump with positions")
    oc.set_defaults(func=cmd_ocr)
    register_diagnose(sub)
    register_apply(sub)
    register_tracks(sub)
    register_template(sub)
    register_migrate(sub)
    args = ap.parse_args(argv)
    _expand_paths(args)
    emit_notice(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
