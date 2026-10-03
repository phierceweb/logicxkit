"""`logic midi` — the MIDI regions of a song, numbered, their export as a Standard MIDI File, and
on a copy a new empty region, a note, or an edit to a region by its number (`_midi_edit_cmd.py`)."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from groovebin.maps import NAMES, stroke

from . import _midi_edit_cmd as edits
from . import _midi_transform_cmd as transforms
from ._edit import CommandError, edit_copy, first_project_data, written_alternatives
from .services.midi.midi import MidiRegion, read_midi
from .services.midi.midi_write import add_note, add_region
from .services.project.project import project_metadata
from .services.song.signature import meter
from .services.midi.smf import meter_map, tempo_map, unexportable, write_smf
from .services.arrange.retrack import find_project


def _describe(e, drum_map: str | None = None) -> str:
    if e.kind == "note":
        named = f"  {stroke(drum_map, e.pitch) or '-'}" if drum_map else ""
        return f"note {e.pitch:3d} vel {e.velocity:3d} len {e.length:5d}{named}"
    if e.kind == "controller":
        return f"cc {e.number:3d} = {e.value}"
    if e.kind == "program":
        return f"program {e.program}"
    if e.kind == "bend":
        return f"bend {e.value}"
    return e.kind


def _event(e, drum_map: str | None) -> dict:
    return {**vars(e), "stroke": stroke(drum_map, e.pitch)} if drum_map and e.kind == "note" else vars(e)


def _print(numbered: list[tuple[int, MidiRegion]], drum_map: str | None) -> None:
    for n, r in numbered:
        loop = "  (loop)" if r.loop else ""
        print(f"  {n:3d}  {r.track or '-':16s} {r.name!r:20s} bar {r.start_bar:6.2f}  {events_count(r)}{loop}")
        for e in r.events:
            print(f"      bar {e.bar:7.3f}  ch {e.channel:2d}  {_describe(e, drum_map)}")


def events_count(r: MidiRegion) -> str:
    """``2 event(s)``, or ``2 event(s), 1 played`` when a split leaves the region holding more than it plays."""
    played = len(r.played)
    return f"{len(r.events)} event(s)" + (f", {played} played" if played != len(r.events) else "")


def _number(text: str, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise CommandError(f"bad {what} {text!r}: a bar number, fractions allowed") from None


def _tick(m, text: str, what: str) -> int:
    try:
        return edits.bar_tick(m, _number(text, what))
    except ValueError as e:
        raise CommandError(f"bad {what} {text!r}: {e}") from None


def _write(args, project: Path) -> int:
    try:
        planned = edits.parse(args.edits)
    except CommandError as e:
        print(f"  {e}")
        return 1
    if not args.track and any(e.number is None for e in planned):
        print("  --remap SRC:DST remaps every region on --track NAME; give one, or a region: N=SRC:DST")
        return 2
    listed = written_alternatives(project)[0]
    try:
        count = project_metadata(project, listed.parent.name).get("tracks")
        resolved = edits.resolve(listed.read_bytes(), count, planned, track=args.track)
        transform = transforms.parse(args.steps, args.select)
        if args.regions and transform is None:
            raise CommandError("region numbers name what a transform touches; give one of its flags")
        found = transforms.targets(listed.read_bytes(), count, args.regions, args.track, args.steps) if transform else []
        seed = transforms.seed_of(args.seed)
    except CommandError as e:
        print(f"  {e}")
        return 1
    if args.seed == "random":
        print(f"  seed {seed}")

    def step(data, count, data_file):
        mine = resolved if data_file.parent.name == listed.parent.name else \
            edits.matched(data, count, resolved, data_file.parent.name)
        data = edits.run(data, count, mine, copies=False)
        if transform:
            # a fresh Random per alternative, so --seed lands the same edit on the same region in each
            data = transforms.run(data, count, found, transform, random.Random(seed), data_file.parent.name,
                                  listed.parent.name, args.steps)
        m = meter(data)
        for spec in args.region or []:
            parts = spec.split(":")
            if len(parts) not in (3, 4):
                raise CommandError(f"bad --region {spec!r}: TRACK:BAR:BARS[:NAME]")
            start, bars = _tick(m, parts[1], "region bar"), _number(parts[2], "region length")
            length = m.ticks(bars, start) if abs(bars) < edits.END_TICK else edits.END_TICK
            if length >= edits.END_TICK - start:
                raise CommandError(f"bad region length {parts[2]!r}: past the end of the sequence")
            data, r = add_region(data, track=parts[0], start=start, length=length,
                                 name=parts[3] if len(parts) == 4 else None, track_count=count)
            print(f"  {r['track']:16s} region {r['name']!r} at bar {parts[1]} for {parts[2]} bar(s), slot {r['slot']}")
        for spec in args.note or []:
            parts = spec.split(":")
            if len(parts) not in (5, 6):
                raise CommandError(f"bad --note {spec!r}: TRACK:BAR:PITCH:VELOCITY:TICKS[:CHANNEL]")
            try:
                data = add_note(data, track=parts[0], tick=_tick(m, parts[1], "note bar"), pitch=int(parts[2]),
                                velocity=int(parts[3]), length=int(parts[4]), channel=int(parts[5]) if len(parts) == 6 else 1,
                                track_count=count)
            except ValueError as e:
                raise CommandError(str(e)) from None
            print(f"  {parts[0]:16s} note {parts[2]} at bar {parts[1]}")
        return edits.run(data, count, mine, copies=True)
    try:
        edit_copy(project, Path(args.out), step)
    except (ValueError, CommandError) as e:
        print(f"  {e}")
        return 1
    return 0


def cmd_midi(args) -> int:
    project = find_project(Path(args.project))
    if args.region or args.note or args.edits or args.steps or args.select or args.regions:
        if not args.out:
            print("  --out is needed to write")
            return 2
        return _write(args, project)
    data = first_project_data(project)
    count = project_metadata(project).get("tracks")
    numbered = [(n, r) for n, r in enumerate(read_midi(data, count), 1) if not args.track or r.track == args.track]
    regions = [r for _n, r in numbered]
    note = sys.stderr if args.json else sys.stdout
    if args.export:
        tempos, meters = tempo_map(data), meter_map(data)
        try:
            smf = write_smf(regions, tempos=tempos, meters=meters)
        except ValueError as e:
            print(f"  {e}", file=note)
            return 1
        left = unexportable(regions)
        if left:
            print("  not in the file: " + ", ".join(f"{n} {kind} event(s)" for kind, n in sorted(left.items())), file=note)
    if args.json:
        print(json.dumps([{"number": n, "track": r.track, "row": r.row, "name": r.name, "start": r.start, "loop": r.loop,
                           "events": [_event(e, args.drum_map) for e in r.events],
                           "played": [_event(e, args.drum_map) for e in r.played]} for n, r in numbered], indent=1))
    else:
        print(f"{project.name}: {len(regions)} MIDI region(s)")
        _print(numbered, args.drum_map)
    if args.export:
        out = Path(args.export)
        out.write_bytes(smf)
        print(f"\nout : {out}  ({len(regions)} track(s), {len(tempos)} tempo event(s) from {tempos[0][1]:g} bpm, "
              f"{len(meters)} time signature(s))", file=note)
    return 0


def register(sub) -> None:
    ap = sub.add_parser("midi", help="read a song's MIDI regions, or export them as a .mid file",
                        description="Edits by region number and the transforms — --select with operations, or a preset — write "
                                    "a copy; a transform touches the regions numbered after the project, or every region on --track.")
    ap.add_argument("project")
    ap.add_argument("--track", metavar="NAME", help="only this track's regions; with a transform, every region on it")
    ap.add_argument("--export", metavar="FILE.mid", help="write a format-1 Standard MIDI File with the song's tempo map and time signatures")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--map", dest="drum_map", choices=NAMES, help="name each note's drum stroke from this map")
    ap.add_argument("--out", help="output directory (needed to write)")
    ap.add_argument("--region", action="append", metavar="TRACK:BAR:BARS[:NAME]", help="a new empty MIDI region")
    ap.add_argument("--note", action="append", metavar="TRACK:BAR:PITCH:VELOCITY:TICKS[:CHANNEL]", help="a note in the track's region that holds BAR")
    edits.add_arguments(ap)
    transforms.add_arguments(ap)
    ap.set_defaults(func=cmd_midi, steps=None)
