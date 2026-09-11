"""argparse CLI for the Logic strip tools: build / verify / decode.

  python -m logicxkit.logic.cli build  spec.json
  python -m logicxkit.logic.cli verify spec.json
  python -m logicxkit.logic.cli decode "Strip.cst" [--json]

decode prints the human dump to stderr and (with --json) a spec stub to stdout, so the
decode->edit->rebuild workflow can pipe the JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


from pf_core.utils.io import atomic_write_bytes

from ._binary import find_blocks, identify_plugin, read_block_floats
from ._apply import register as register_apply
from ._apply_template import register as register_template
from ._apply_tracks import register as register_tracks
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
from ._prefs import register as register_prefs
from ._chains_cmd import register as register_chains
from ._diagnose import register as register_diagnose
from ._inspect import (
    cmd_diff,
    cmd_image,
    cmd_neural,
    cmd_ocr,
    cmd_project,
    cmd_stacks,
)
from .services.comp import decode_comp
from .services.library import factory_settings, strip_library, under_live_library
from .services.eq import BAND_ORDER, decode_eq
from .services.levels import PAN_CENTRE, UNITY, copy_levels, read_levels
from .services.pst import output_root as pst_output_root
from .services.pst import write_psts
from .services.donors import harvest_donors, load_donor_library
from .services.retrack import copy_project, find_project, missing_strips, retrack_bundle
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
    """A relative `output_dir` resolves into Logic's own strip library, so an existing file is
    kept unless `--overwrite` says otherwise, and a failed preset is a non-zero exit."""
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
    written = 0
    for dest, status in write_psts(spec, overwrite=args.overwrite):
        print(f"  {'OK ' if status == 'written' else '-- '} {dest.parent.name}/{dest.name}  {status}")
        written += status == "written"
    print(f"\nDone — {written} preset(s). In Logic: plugin window → Settings menu → the preset name.")
    return 0


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


def cmd_donors(args) -> int:
    """Harvest plugin-slot donor records from a project into the reusable library."""
    from ..utils.data import data_dir
    lib = Path(args.library) if args.library else data_dir("donors")
    names = {}
    settings = factory_settings()
    if settings.is_dir():
        for folder in settings.iterdir():
            for preset in list(folder.glob("*.pst"))[:3] if folder.is_dir() else []:
                blocks = find_blocks(preset.read_bytes())
                if blocks:
                    names.setdefault(blocks[0][1], folder.name)
                    break
    total = []
    src = Path(args.project)
    if src.suffix == ".cst":
        total += harvest_donors(src.read_bytes(), lib, names, start=0)
    elif src.is_dir() and src.suffix != ".logicx" and not list(src.glob("*.logicx")):
        for strip in sorted(src.rglob("*.cst")):        # a folder of strips
            total += harvest_donors(strip.read_bytes(), lib, names, start=0)
    else:
        for data_file in sorted(find_project(src).glob("Alternatives/*/ProjectData")):
            total += harvest_donors(data_file.read_bytes(), lib, names)
    have = load_donor_library(lib)
    print(f"library: {lib}\n  added {len(total)}: {', '.join(total) or '(nothing new)'}")
    print(f"  now holds {len(have)} donor(s):")
    for key, (_raw, type_id, ver) in sorted(have.items()):
        print(f"    {key:12s} {names.get(type_id, 'type %d' % type_id):22s} class v{ver}")
    return 0


def _project_data_paths(project: Path) -> list[Path]:
    return sorted(project.glob("Alternatives/*/ProjectData"))


def cmd_levels(args) -> int:
    """Dump a project's fader/pan, or carry them onto another project's copy."""
    from .services.chains import channel_references

    src_project = find_project(Path(args.project))
    src = _project_data_paths(src_project)[0].read_bytes()

    if not args.to:
        refs = channel_references(src)
        rows = read_levels(src)
        if args.json:
            print(json.dumps({str(o): dict(v, ref=refs.get(o))
                              for o, v in sorted(rows.items())}, indent=2))
            return 0
        print(f"{'owner':>5}  {'ref':24s} {'fader':>5} {'pan':>5}")
        for owner, v in sorted(rows.items()):
            if v["fader"] == UNITY and v["pan"] == PAN_CENTRE and not refs.get(owner):
                continue
            print(f"{owner:5d}  {str(refs.get(owner, '')):24s} "
                  f"{v['fader']:5d} {v['pan_display']:+5d}")
        return 0

    if not args.out:
        print("logic levels: --to needs --out")
        return 2
    copied = copy_project(Path(args.to), Path(args.out))
    dest = copied["dest"]
    print(f"levels from : {src_project}")
    print(f"into        : {dest}")
    total = 0
    for data_file in _project_data_paths(dest):
        out, report = copy_levels(src, data_file.read_bytes(), by=args.by)
        atomic_write_bytes(data_file, out)
        total += len(report["changed"])
        print(f"  {data_file.parent.name}: {report['matched']} matched, "
              f"{len(report['changed'])} changed, {report['unchanged']} already equal")
        if report["unmatched"]:
            print(f"    no counterpart in the source: {len(report['unmatched'])} channel(s)")
    print(f"\nSet levels on {total} channel(s).")
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
              "propose_map", "export", "from_", "config")


def _expand_paths(args) -> None:
    for name in _PATH_ARGS:
        value = getattr(args, name, None)
        if isinstance(value, str) and value.startswith("~"):
            setattr(args, name, str(Path(value).expanduser()))


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
    dn = sub.add_parser("donors", help="harvest plugin-slot donors from a project")
    dn.add_argument("project")
    dn.add_argument("--library", default=None, help="donor library (default: the data root's donors/)")
    dn.set_defaults(func=cmd_donors)
    register_chains(sub)
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
    lv = sub.add_parser("levels", help="dump channel fader/pan, or copy them onto a project")
    lv.add_argument("project", help="the project to read levels FROM")
    lv.add_argument("--to", help="project to write them onto (a copy is made)")
    lv.add_argument("--out", help="output directory, required with --to")
    lv.add_argument("--by", choices=("reference", "owner", "label"), default="reference",
                    help="how to pair channels (default: channel-strip reference)")
    lv.add_argument("--json", action="store_true")
    lv.set_defaults(func=cmd_levels)
    st = sub.add_parser("stacks", help="track stacks and the arrange track list")
    st.add_argument("logicx", help="a .logicx, or a folder containing one")
    st.add_argument("--tracks", action="store_true", help="list every track in display order")
    st.add_argument("--json", action="store_true")
    st.add_argument("--move", action="append", metavar="TRACK:STACK",
                    help="move a track into a stack (repeatable); writes a copy")
    st.add_argument("--out", help="output directory, required with --move")
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
    im.set_defaults(func=cmd_image)
    oc = sub.add_parser("ocr", help="OCR a WindowImage (or any image) via Apple Vision")
    oc.add_argument("file", help=".logicx bundle or an image file")
    oc.add_argument("--json", action="store_true", help="full token dump with positions")
    oc.set_defaults(func=cmd_ocr)
    register_diagnose(sub)
    register_apply(sub)
    register_tracks(sub)
    register_template(sub)
    args = ap.parse_args(argv)
    _expand_paths(args)
    emit_notice(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
