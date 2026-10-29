"""argparse CLI for `logicxkit logic`: every command module registers its parser here; path
arguments are expanded and the capability notice printed before the command runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path



from ._add_plugin_cmd import register as register_add_plugin
from ._donors_cmd import register as register_donors
from ._settings_cmd import register as register_settings
from ._strip_cmd import register as register_strip
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
from ._retrack_cmd import register as register_retrack
from ._markers_cmd import register as register_markers
from ._automation_cmd import register as register_automation
from ._swap_plugin_cmd import register as register_swap_plugin
from ._tracking_chains_cmd import register as register_tracking_chains
from ._sessionplayer_cmd import register as register_sessionplayer
from ._quantize_cmd import register as register_quantize
from ._diagnose import register as register_diagnose
from ._drums_to_midi_cmd import register as register_drums_to_midi
from ._silence_cmd import register as register_strip_silence
from ._songs_cmd import register as register_songs
from ._split_sections_cmd import register as register_split_sections
from ._inspect import (
    cmd_diff,
    cmd_image,
    cmd_neural,
    cmd_ocr,
    cmd_project,
    cmd_stacks,
)

# Every path argument, so a quoted "~/Music/…" is a path and not a directory named "~".
_PATH_ARGS = ("project", "logicx", "out", "to", "spec", "library", "file", "image", "map",
              "propose_map", "export", "from_", "config", "template", "src", "dst", "a", "b",
              "baseline", "apply", "backup_dir", "controlbar_from", "build", "audio",
              "save_map", "db", "maps", "setlist",
)


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
    register_strip(sub)
    register_retrack(sub)
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
    register_strip_silence(sub)
    register_songs(sub)
    register_split_sections(sub)
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
    st.add_argument("--flatten", action="append", metavar="STACK",
                    help="take a stack apart, its members up a level (repeatable); writes a copy")
    st.add_argument("--convert", action="append", metavar="STACK",
                    help="make a folder stack a summing stack (repeatable); writes a copy")
    st.add_argument("--out", help="output directory, required with --move, --move-out, --flatten and --convert")
    st.set_defaults(func=cmd_stacks)
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
