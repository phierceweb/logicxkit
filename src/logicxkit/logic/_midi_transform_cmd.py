"""`logic midi` transforms: Logic's Transform window as flags — `--select` with the operations, and
the presets — over the regions numbered on the command line or every region on `--track`,
parsed before the copy and applied one region at a time through `midi_transform`."""

from __future__ import annotations

import argparse
import random
import secrets

from groovebin.transforms import BY_NAME, WHOLE_PART, parse_operation, parse_select, parse_value

from ._edit import CommandError
from ._midi_edit_cmd import Edit, matched
from .services.song.events import PPQ
from .services.midi.midi import MidiRegion, read_midi
from .services.midi.midi_transform import Transform, apply_transform

OPS = {
    "set": ("FIELD=VALUE", "set a field of every selected note"),
    "add": ("FIELD=VALUE", "add to a field (negative subtracts)"),
    "mul": ("FIELD=FACTOR", "multiply a field"),
    "min": ("FIELD=VALUE", "raise what is below VALUE to it"),
    "max": ("FIELD=VALUE", "cut what is above VALUE to it"),
    "random": ("FIELD=SPREAD", "move a field by up to ±SPREAD"),
    "flip": ("FIELD=PIVOT", "mirror a field around PIVOT"),
    "crescendo": ("[FIELD=]LO..HI", "ramp a field from LO at the first selected note to HI at the last (velocity without FIELD)"),
    "exp": ("velocity=EXPONENT", "a velocity curve; above 1 softens the middle"),
    "reverse": ("position|pitch", "mirror the selection's span, first for last"),
}
PRESETS = {
    "humanize": ("[pos=10t,vel=8,len=5]", "move each note's position, velocity and length at random (the defaults are ours; Logic's manual states none)"),
    "fixed-velocity": ("VELOCITY", "every selected note at one velocity"),
    "velocity-limit": ("[LO..HI]", "hold velocities inside LO..HI (default 20..110)"),
    "random-velocity": ("[SPREAD]", "move each velocity by up to ±SPREAD (default 20)"),
    "reverse-position": (None, "mirror the selected notes' positions, first for last"),
    "reverse-pitch": ("[PIVOT]", "mirror pitches around PIVOT, else around the selection's lowest and highest"),
    "exp-velocity": ("[EXPONENT]", "velocities through a power curve (default 1.5)"),
    "fixed-length": ("TICKS|1/N", "every selected note one length"),
    "max-length": ("TICKS|1/N", "cut notes longer than the length"),
    "min-length": ("TICKS|1/N", "stretch notes shorter than the length"),
    "half-speed": (None, "double every position and length, the region's other events too"),
    "double-speed": (None, "halve every position and length, the region's other events too"),
    "legato": ("[PERCENT]", "each note lasts PERCENT of the way to the next note's start (default 100)"),
    "staccato": ("[PERCENT]", "each note's length times PERCENT (default 50)"),
    "swing": ("PERCENT[:1/N]", "notes on the grid, every second line late by grid x (2·swing - 1); 50% straight; 1/16 by default"),
}
FIELDS = "position (song bars; a whole number is the whole bar), pitch, velocity, length (ticks, 240t or 1/16) or channel"
OPTIONAL = tuple(f for f, (shape, _t) in PRESETS.items() if shape and shape.startswith("["))


class _InOrder(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        namespace.steps = [*(namespace.steps or []), (option_string.lstrip("-"), values)]


def add_arguments(ap) -> None:
    ap.add_argument("regions", nargs="*", type=int, metavar="N",
                    help="the regions to transform, by listing number, before the transform flags")
    ap.add_argument("--select", action="append", metavar="COND[,COND…]",
                    help=f"which notes a transform touches: FIELD=VALUE, FIELD=LO-HI, or FIELD <, <=, >, >=, != VALUE over {FIELDS}; "
                         "every note without it (repeatable, all must hold)")
    for flag, (shape, text) in OPS.items():
        ap.add_argument(f"--{flag}", dest="steps", action=_InOrder, metavar=shape, help=f"{text} (repeatable)")
    for flag, (shape, text) in PRESETS.items():
        if shape is None:
            ap.add_argument(f"--{flag}", dest="steps", action=_InOrder, nargs=0, help=text)
        elif shape.startswith("["):
            ap.add_argument(f"--{flag}", dest="steps", action=_InOrder, nargs="?", metavar=shape.strip("[]"), help=text)
        else:
            ap.add_argument(f"--{flag}", dest="steps", action=_InOrder, metavar=shape, help=text)
    ap.add_argument("--seed", default="0", metavar="N|random", help="the seed for random moves and humanize (default 0, so a run repeats)")


def _bad(flag: str, spec, message: str) -> CommandError:
    shown = "" if spec in (None, []) else f" {spec!r}"
    return CommandError(f"bad --{flag}{shown}: {message}")


def parse(steps: list[tuple[str, object]] | None, selects: list[str] | None) -> Transform | None:
    """The transform flags in command-line order -> a Transform, or None when there are none;
    consecutive operations form one pass, each preset its own."""
    ranges = {}
    for text in selects or []:
        try:
            found = parse_select(text, ppq=PPQ)
        except ValueError as e:
            raise _bad("select", text, str(e)) from None
        twice = sorted(set(found) & set(ranges))
        if twice:
            raise _bad("select", text, f"{twice[0]} is given twice")
        ranges.update(found)
    out: list = []
    for flag, spec in steps or []:
        try:
            if (flag in OPS or flag == "quantize") and not (flag == "crescendo" and "=" not in spec):
                op = parse_operation(flag, spec, ppq=PPQ)
                if out and out[-1][0] == "ops":
                    out[-1][1].append(op)
                else:
                    out.append(("ops", [op]))
                continue
            name = flag
            preset = BY_NAME[name]
            value = parse_value(preset, None if spec in (None, []) else spec, ppq=PPQ)
        except ValueError as e:
            raise _bad(flag, spec, str(e)) from None
        if ranges and name in WHOLE_PART:
            raise _bad(flag, spec, f"{name} takes the whole region; drop --select")
        out.append(("preset", (name, value)))
    if not out and not ranges:
        return None
    if not out:
        raise CommandError("--select needs an operation or a preset to apply")
    return Transform(ranges, tuple(out))


def seed_of(text: str) -> int:
    if text == "random":
        return secrets.randbelow(2**32)
    if not text.isdecimal():
        raise CommandError(f"bad --seed {text!r}: 0 or more, or random")
    return int(text)


def _swallowed(steps: list[tuple[str, object]] | None) -> tuple[str, str] | None:
    """The optional-value preset that took a bare region number as its own value: argparse hands
    ``--staccato 3`` the 3, leaving the trailing region list empty."""
    return next(((f, s) for f, s in steps or [] if f in OPTIONAL and isinstance(s, str) and s.isdigit()), None)


def targets(data: bytes, count: int | None, numbers: list[int], track: str | None,
            steps: list[tuple[str, object]] | None = None) -> list[tuple[int, MidiRegion]]:
    """The regions the transform touches on the listed alternative: those numbered, else every MIDI
    region on ``track``."""
    if not numbers and track is None:
        eaten = _swallowed(steps)
        if eaten:
            raise CommandError(f"--{eaten[0]} took {eaten[1]!r} as its own value, so no region is named: put the "
                               f"region numbers before --{eaten[0]}, or name the track with --track")
        raise CommandError("name the regions to transform by number, or --track NAME for every region on a track")
    regions = read_midi(data, count)
    if numbers:
        for n in numbers:
            if not 1 <= n <= len(regions):
                raise CommandError(f"region {n}: the song has {len(regions)} MIDI region(s)")
        return [(n, regions[n - 1]) for n in dict.fromkeys(numbers)]
    mine = [(n, r) for n, r in enumerate(regions, 1) if r.track == track]
    if not mine:
        raise CommandError(f"no MIDI region on track {track!r}")
    return mine


def run(data: bytes, count: int | None, found: list[tuple[int, MidiRegion]], transform: Transform, rng: random.Random,
        alternative: str, listed: str, steps: list[tuple[str, object]]) -> bytes:
    """The transform on each target region of one alternative, in listing order."""
    if alternative != listed:
        found = [(e.number, r) for e, r in matched(data, count, [(Edit("", n, None), r) for n, r in found], alternative)]
    said = "; ".join(flag if spec in (None, []) else f"{flag} {spec}" for flag, spec in steps)
    for n, r in found:
        try:
            data, report = apply_transform(data, r, transform, rng=rng, track_count=count)
        except ValueError as e:
            raise CommandError(f"region {n} {r.name!r} on {r.track!r}: {e}") from None
        print(f"  region {n} {r.name!r} on {r.track!r}: {report.selected} of {report.notes} note(s) selected; {said}")
    return data
