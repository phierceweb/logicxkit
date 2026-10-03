"""`logic regions` — every region on every track, numbered: MIDI ones with their events, audio
ones with their files, mutes, loops, fades, inspector parameters and colours; on a copy, `--audio`
imports a WAV as a new region and the edits take a listing number (`region_edit.py`,
`region_params_write.py`)."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from ._edit import CommandError, edit_copy, first_project_data
from ._midi_cmd import events_count
from .services.regions.audio_regions import read_audio_files
from .services.regions.audio_write import add_audio_region
from .services.project.project import first_alternative, project_metadata
from .services.regions.fades import OUT_CODES
from .services.regions.region_edit import (
    listed, located, move_region, rename_region, renumbered, samples_per_tick_of, set_fade, set_loop, set_mute, split_region,
    trim_region,
)
from .services.regions.region_params_write import set_colour, set_crossfade, set_params
from .services.arrange.retrack import find_project
from .services.song.signature import meter
from .services.arrange.stacks import read_tracks

PARAMS = {"gain": ("gain", "N=DB"), "delay": ("delay", "N=TICKS"), "transpose": ("transpose", "N=SEMITONES"),
          "fine-tune": ("fine_tune", "N=CENTS")}


def _number(text: str, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise CommandError(f"bad {what} {text!r}: a bar number, fractions allowed") from None


def _index(text: str, flag: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise CommandError(f"bad --{flag} {text!r}: N is a region's number in the listing")
    return int(text)


def _split(spec: str, flag: str, shape: str) -> tuple[int, str]:
    n, sep, rest = spec.partition("=")
    if not sep:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}")
    return _index(n, flag), rest


def _switch(spec: str, flag: str) -> tuple[int, bool]:
    n, _sep, rest = spec.partition("=")
    if rest not in ("", "on", "off"):
        raise CommandError(f"bad --{flag} {spec!r}: N, N=on or N=off")
    return _index(n, flag), rest != "off"


def _fade(spec: str, flag: str) -> tuple[int, int | None, int, str]:
    """``N=MS[:CURVE[:TYPE]]`` -> (N, ms, curve, type); a crossfade's MS may be empty (the overlap)."""
    shape = {"fade-in": "N=MS[:CURVE[:speed-up]]", "fade-out": "N=MS[:CURVE[:out|x|eqp|xs]]", "crossfade": "N=[MS][:CURVE[:x|eqp|xs]]"}[flag]
    n, rest = _split(spec, flag, shape)
    parts = rest.split(":")
    try:
        ms = None if flag == "crossfade" and not parts[0] else int(parts[0])
        curve = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}") from None
    kind = parts[2] if len(parts) > 2 else ""
    kinds = {"fade-in": ("", "in", "speed-up"), "fade-out": ("", *OUT_CODES), "crossfade": ("", "x", "eqp", "xs")}[flag]
    if kind not in kinds or len(parts) > 3:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}")
    return n, ms, curve, kind


def _int(spec: str, flag: str, shape: str) -> tuple[int, int]:
    n, rest = _split(spec, flag, shape)
    try:
        return n, int(rest)
    except ValueError:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}") from None


UNVERIFIED = ("transpose",)      # Logic flexed the track for it and the writer does not; the rest re-saved as written


class _Marked(argparse.Action):
    """An edit whose field Logic has not re-saved as written: appended to the edits and marked, so
    the capability notice calls the run DERIVED."""

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.edits = [*(namespace.edits or []), values]
        namespace.unverified = True


class _Tempo:
    """Samples per tick, read only when an edit converts frames — a song whose tempo changes can
    still be muted, renamed or imported into."""

    def __init__(self, data: bytes, rate: int | None):
        self.data, self.rate, self.spt = data, rate, None

    def __call__(self) -> float | None:
        if self.spt is None and self.rate:
            self.spt = samples_per_tick_of(self.data, self.rate)
        return self.spt


def _targets(args, data, count) -> dict:
    """Each edit's region as the listed alternative numbers it: (kind, track, name, start), the
    same region in every alternative."""
    out = {}
    for flag, spec in args.edits:
        loc = located(data, _index(spec.partition("=")[0], flag), count)
        out[(flag, spec)] = (loc.kind, loc.region.track, loc.region.name, loc.region.start)
    return out


def _matched(targets: dict, data, count, alternative: str, listed_alternative: str) -> dict:
    """Each target found in ``data`` (one alternative) -> its `Located`: by number in the listed
    alternative, by track, name and start in the others, where exactly one must match."""
    regions = listed(data, count)
    out = {}
    for (flag, spec), (kind, track, name, start) in targets.items():
        if alternative == listed_alternative:
            out[(flag, spec)] = regions[_index(spec.partition("=")[0], flag) - 1]
            continue
        hits = [loc for loc in regions if (loc.kind, loc.region.track, loc.region.name, loc.region.start) == (kind, track, name, start)]
        if len(hits) != 1:
            has = f"{len(hits)} regions" if hits else "no region"
            raise CommandError(f"--{flag} {spec}: alternative {alternative} has {has} {name!r} on {track!r} "
                               f"at bar {meter(data).bar(start):g}")
        out[(flag, spec)] = hits[0]
    return out


def _edits(args, data, count, tempo: _Tempo, idents: dict) -> bytes:
    """The edits in command-line order, each on the region its number named in the input."""
    m = meter(data)
    for flag, spec in args.edits:
        n = renumbered(data, idents[(flag, spec)], count)
        if flag == "move":
            _n, bar = _split(spec, flag, "N=BAR")
            data = move_region(data, n, m.tick(_number(bar, "bar")), count)
        elif flag == "trim":
            _n, rest = _split(spec, flag, "N=BAR:BARS (either may be empty)")
            start, _sep, bars = rest.partition(":")
            tick = m.tick(_number(start, "bar")) if start else None
            length = None
            if bars:
                first = _number(start, "bar") if start else m.bar(located(data, n, count).region.start)
                length = m.tick(first + _number(bars, "length")) - m.tick(first)
            data = trim_region(data, n, start=tick, length=length, spt=tempo(), track_count=count)
        elif flag == "split":
            _n, bar = _split(spec, flag, "N=BAR")
            data = split_region(data, n, m.tick(_number(bar, "bar")), spt=tempo(), track_count=count)
        elif flag == "loop":
            _n, on = _switch(spec, flag)
            data = set_loop(data, n, on, spt=tempo() if located(data, n, count).audio else None, track_count=count)
        elif flag == "mute":
            _n, on = _switch(spec, flag)
            data = set_mute(data, n, on, count)
        elif flag == "rename":
            _n, name = _split(spec, flag, "N=NAME")
            data = rename_region(data, n, name, count)
        elif flag == "colour":
            _n, index = _int(spec, flag, "N=INDEX")
            data = set_colour(data, n, index, count)
        elif flag in PARAMS or flag == "reverse":
            if flag == "reverse":
                _n, on = _switch(spec, flag)
                change = {"reverse": on}
            else:
                _n, value = _int(spec, flag, PARAMS[flag][1])
                change = {PARAMS[flag][0]: value}
            have = located(data, n, count)
            if have.audio is None:
                raise CommandError(f"region {n} is a MIDI region; --{flag} is an audio region's")
            data = set_params(data, n, replace(have.audio.params, **change), count)
        elif flag == "crossfade":
            _n, ms, curve, kind = _fade(spec, flag)
            if tempo() is None:
                raise CommandError("a crossfade's length needs the project's sample rate")
            data = set_crossfade(data, n, ms=ms, curve=curve, kind=kind or "eqp", spt=tempo(), rate=tempo.rate, track_count=count)
        else:
            _n, ms, curve, kind = _fade(spec, flag)
            have = located(data, n, count)
            if have.audio is None:
                raise CommandError(f"region {n} is a MIDI region; fades are an audio region's")
            fade = have.audio.fade
            fade = replace(fade, in_ms=ms, in_curve=curve, in_type=int(kind == "speed-up")) if flag == "fade-in" \
                else replace(fade, out_ms=ms, out_curve=curve, out_type=kind or "out")
            data = set_fade(data, n, fade, count)
    return data


def _moved(targets: dict, data, count, data_file: Path, listed_alternative: str) -> list:
    """The keys of the regions an edit moves or cuts in this alternative, for the gate."""
    found = _matched(targets, data, count, data_file.parent.name, listed_alternative)
    return [loc.key for (flag, _spec), loc in found.items() if flag in ("move", "trim", "split")]


def _write(args, project: Path) -> int:
    listed_alternative = first_alternative(project)
    targets = _targets(args, first_project_data(project), project_metadata(project).get("tracks"))

    def step(data, count, data_file):
        bundle = data_file.parents[2]
        rate = project_metadata(bundle, data_file.parent.name).get("sample_rate")
        idents = {edit: loc.ident for edit, loc in _matched(targets, data, count, data_file.parent.name, listed_alternative).items()}
        for spec in args.audio or ():
            parts = spec.split(":", 2)
            if len(parts) != 3:
                raise CommandError(f"bad --audio {spec!r}: TRACK:BAR:FILE.wav")
            wav = Path(parts[2]).expanduser()
            if not wav.is_file():
                raise CommandError(f"no such file: {wav}")
            data, r = add_audio_region(data, track=parts[0], start=meter(data).tick(_number(parts[1], "bar")), wav=wav,
                                       media_folder=bundle / "Media" / "Audio Files", rate=rate, track_count=count)
            print(f"  {r['track']:16s} {r['file']} at bar {parts[1]}: {r['frames']} frames as region {r['name']!r}")
        data = _edits(args, data, count, _Tempo(data, rate), idents)
        for flag, spec in args.edits:
            print(f"  --{flag} {spec}")
        return data
    try:
        edit_copy(project, Path(args.out), step,
                  moved=lambda data, count, data_file: _moved(targets, data, count, data_file, listed_alternative))
    except (ValueError, CommandError) as e:
        print(f"  {e}")
        return 1
    return 0


def _listing(project: Path, args) -> int:
    data = first_project_data(project)
    count = project_metadata(project).get("tracks")
    regions = listed(data, count)
    files = read_audio_files(data)
    if args.track:
        regions = [r for r in regions if r.region.track == args.track]
    if args.json:
        midi = [{"number": r.number, "track": r.midi.track, "row": r.midi.row, "name": r.midi.name, "start": r.midi.start,
                 "loop": r.midi.loop, "muted": r.midi.muted, "events": len(r.midi.events), "played": len(r.midi.played),
                 "colour": r.midi.colour} for r in regions if r.midi]
        audio = [{"number": r.number, "track": r.audio.track, "row": r.audio.row, "name": r.audio.name, "start": r.audio.start,
                  "frames": r.audio.frames, "offset": r.audio.offset, "piece": r.audio.piece, "loop": r.audio.loop,
                  "muted": r.audio.muted, "fade": vars(r.audio.fade), "params": vars(r.audio.params), "colour": r.audio.colour,
                  "file": vars(r.audio.file) if r.audio.file else None}
                 for r in regions if r.audio]
        print(json.dumps({"midi": midi, "audio": audio, "files": [vars(f) for f in files]}, indent=1))
        return 0
    n_midi, n_audio = sum(1 for r in regions if r.midi), sum(1 for r in regions if r.audio)
    track_colours = {t["name"]: t["colour"] for t in read_tracks(data, count)}
    print(f"{project.name}: {n_midi} MIDI region(s), {n_audio} audio region(s), {len(files)} audio file(s)")
    for loc in regions:
        r = loc.region
        marks = ("  (loop)" if r.loop else "") + ("  (muted)" if r.muted else "")
        colour = f"  colour {r.colour}" if r.colour != track_colours.get(r.track) else ""
        if loc.midi:
            print(f"  {loc.number:3d} {r.track or '-':16s} {r.name!r:22s} bar {r.start_bar:6.2f}  MIDI   {events_count(r)}{marks}{colour}")
        else:
            f = r.file
            src = f"{f.name} {f.rate} Hz {f.channels} ch {f.bits} bit" if f else "(file record missing)"
            fade = f"  fade {r.fade}" if str(r.fade) else ""
            params = f"  {r.params}" if str(r.params) else ""
            offset = f" from {r.offset}" if r.offset else ""
            print(f"  {loc.number:3d} {r.track or '-':16s} {r.name!r:22s} bar {r.start_bar:6.2f}  audio  {r.frames} frames{offset}  {src}{marks}{fade}{params}{colour}")
    return 0


def cmd_regions(args) -> int:
    project = find_project(Path(args.project))
    args.edits = [(flag, spec) for flag, spec in (args.edits or ())]
    if args.audio or args.edits:
        if not args.out:
            print("  --out is needed to write")
            return 2
        return _write(args, project)
    return _listing(project, args)


def register(sub) -> None:
    ap = sub.add_parser("regions", help="every MIDI and audio region, numbered, with events or files; edits on a copy")
    ap.add_argument("project")
    ap.add_argument("--track", metavar="NAME", help="only this track's regions")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="output directory (needed to write)")
    ap.add_argument("--audio", action="append", metavar="TRACK:BAR:FILE.wav", help="import a PCM WAV at the project's sample rate as a region")
    for flag, shape, text in (("move", "N=BAR", "start region N at BAR"),
                              ("trim", "N=BAR:BARS", "region N from BAR (content kept in place) for BARS; either may be empty"),
                              ("split", "N=BAR", "cut region N at BAR; the rest becomes a new region"),
                              ("loop", "N[=on|off]", "loop region N (on by default)"),
                              ("mute", "N[=on|off]", "mute region N (on by default)"),
                              ("rename", "N=NAME", "rename region N"),
                              ("fade-in", "N=MS[:CURVE[:speed-up]]", "fade in over MS ms, curve -99..99"),
                              ("fade-out", "N=MS[:CURVE[:TYPE]]", "fade out over MS ms, curve -99..99, type out, x, eqp or xs"),
                              ("crossfade", "N=[MS][:CURVE[:TYPE]]", "a crossfade from region N into the region over it: MS (the overlap "
                                                                     "when empty), curve, type x, eqp (default) or xs"),
                              ("gain", "N=DB", "region N's Gain, -30..30 dB"),
                              ("delay", "N=TICKS", "region N's Delay in ticks (negative is earlier)"),
                              ("transpose", "N=SEMITONES", "region N's Transpose (Logic flexes the track on its own; the entry's field alone is written)"),
                              ("fine-tune", "N=CENTS", "region N's Fine Tune, -50..50 cents"),
                              ("reverse", "N[=on|off]", "region N's Reverse (on by default)"),
                              ("colour", "N=INDEX", "region N's colour, a palette index 0-255 (the Color window's swatch k is 24 + k)")):
        ap.add_argument(f"--{flag}", dest="edits", action=_Marked if flag in UNVERIFIED else "append", type=lambda s, f=flag: (f, s),
                        metavar=shape, help=text)
    ap.set_defaults(func=cmd_regions, unverified=False)
