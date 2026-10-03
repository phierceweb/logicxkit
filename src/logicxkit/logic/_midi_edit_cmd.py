"""`logic midi` edits by region number: parsed and resolved against the listed alternative before
the project is copied, each region found again in every alternative by track, start and name
before its first edit, in-place edits in command-line order and the copies after them."""

from __future__ import annotations

import argparse
import math
import struct
from dataclasses import dataclass, replace

from groovebin import transforms as gt
from groovebin.maps import NAMES

from ._edit import CommandError
from .services.song.events import BAR_ONE, PPQ
from .services.midi.midi import MidiRegion, read_midi
from .services.midi.midi_edit import (END_TICK, EventLines, copy_notes, copy_region, edit, edit_region, is_note, meter_map,
                                 remap, require_no_poly_aftertouch, to_part, from_part)
from .services.song.signature import Meter, meter

SHAPES = {
    "transpose": ("N=SEMITONES", "transpose region N's notes"),
    "velocity": ("N=SCALE|N=+OFFSET", "scale region N's note velocities (0.8), or add to them (+10, -10); held to 1-127"),
    "move": ("N=TICKS", "move every event in region N by TICKS (960 a quarter; negative is earlier)"),
    "delete": ("N[:PITCH]", "delete region N's notes, or only those of PITCH"),
    "quantize": ("N=1/16", "quantize region N's note starts to a grid of 1/1 to 1/64 from each bar line"),
    "remap": ("[N=]SRC:DST", f"translate region N's drum notes between maps ({', '.join(NAMES)}), "
                            "or every region on --track"),
    "copy-region": ("N=TRACK:BAR", "copy region N to a new region on TRACK at BAR"),
    "copy-notes": ("N=[TRACK:]BAR", "merge region N's events into the region on TRACK (N's own by default) "
                                    "that holds BAR, N's start at BAR"),
}
COPIES = ("copy-region", "copy-notes")
VELOCITY_MAX = 127


@dataclass(frozen=True)
class Edit:
    flag: str
    number: int | None         # 1-based, as the listing numbers regions; None is every region on --track
    value: object


class _InOrder(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        flag = option_string.lstrip("-")
        if flag == "quantize" and values.partition("=")[0] in ("position", "length"):
            namespace.steps = [*(getattr(namespace, "steps", None) or []), (flag, values)]      # a transform op
        else:
            namespace.edits = [*(namespace.edits or []), (flag, values)]


def add_arguments(ap) -> None:
    for flag, (shape, text) in SHAPES.items():
        if flag == "quantize":
            shape, text = "N=1/16|position=1/16|length=1/16", f"{text}; position= or length= quantizes the selected notes' field to the nearest multiple"
        ap.add_argument(f"--{flag}", dest="edits", action=_InOrder, metavar=shape, help=f"{text} (repeatable)")


def _bad(flag: str, spec: str) -> CommandError:
    return CommandError(f"bad --{flag} {spec!r}: {SHAPES[flag][0]}")


def _value(flag: str, arg: str):
    if flag in ("transpose", "move"):
        return int(arg)
    if flag == "delete":
        if arg and not 0 <= int(arg) <= 127:
            raise ValueError(arg)
        return int(arg) if arg else None
    if flag == "velocity":
        value = (1.0, int(arg)) if arg[:1] in ("+", "-") else (float(arg), 0)
        if not (0 <= value[0] <= VELOCITY_MAX and abs(value[1]) <= VELOCITY_MAX):
            raise ValueError(arg)
        return value
    if flag == "quantize":
        one, slash, denominator = arg.partition("/")
        if (one, slash) != ("1", "/"):
            raise ValueError(arg)
        return gt.grid_ticks(int(denominator), PPQ)
    if flag == "remap":
        src, sep, dst = arg.partition(":")
        if not sep or src not in NAMES or dst not in NAMES or src == dst:
            raise ValueError(arg)
        return src, dst
    track, _, bar = arg.rpartition(":")
    if (flag == "copy-region" and not track) or not math.isfinite(float(bar)):
        raise ValueError(arg)
    return track or None, float(bar)


def parse(edits: list[tuple[str, str]] | None) -> list[Edit]:
    """``(flag, spec)`` pairs in command-line order -> edits; a bad spec names its shape."""
    out = []
    for flag, spec in edits or []:
        whole_track = flag == "remap" and "=" not in spec
        number, sep, arg = ("", "=", spec) if whole_track else spec.partition(":" if flag == "delete" else "=")
        try:
            if (not whole_track and int(number) < 1) or (sep and not arg) or (flag != "delete" and not sep):
                raise ValueError(spec)
            out.append(Edit(flag, None if whole_track else int(number), _value(flag, arg)))
        except ValueError:
            raise _bad(flag, spec) from None
    return out


def resolve(data: bytes, count: int | None, edits: list[Edit], *,
            track: str | None = None) -> list[tuple[Edit, MidiRegion]]:
    """Each edit with its region; an edit with no number becomes one per region on ``track``."""
    regions = read_midi(data, count)
    out = []
    for e in edits:
        if e.number is None:
            mine = [(n, r) for n, r in enumerate(regions, 1) if r.track == track]
            if not mine:
                raise CommandError(f"--{e.flag}: no MIDI region on track {track!r}")
            out += [(replace(e, number=n), r) for n, r in mine]
        elif e.number > len(regions):
            raise CommandError(f"--{e.flag} {e.number}: the song has {len(regions)} MIDI region(s)")
        else:
            out.append((e, regions[e.number - 1]))
    return out


def matched(data: bytes, count: int | None, resolved: list[tuple[Edit, MidiRegion]],
            alternative: str) -> list[tuple[Edit, MidiRegion]]:
    """Each resolved region found in ``data`` by track, start and name; exactly one must match."""
    regions = read_midi(data, count)
    out = []
    for e, r in resolved:
        hits = [x for x in regions if (x.track, x.start, x.name) == (r.track, r.start, r.name)]
        if len(hits) != 1:
            has = f"{len(hits)} regions" if hits else "no region"
            named = f"--{e.flag} {e.number}" if e.flag else f"region {e.number}"      # a transform names it by number alone
            raise CommandError(f"{named}: alternative {alternative} has {has} {r.name!r} on {r.track!r} "
                               f"at bar {r.start_bar:g}")
        out.append((e, hits[0]))
    return out


def bar_tick(m: Meter, bar: float) -> int:
    """Where ``bar`` falls; a bar outside the sequence is refused."""
    try:
        at = m.tick(bar)
    except (OverflowError, ValueError):
        at = END_TICK if bar > 0 else -1
    if at >= END_TICK:
        raise ValueError(f"bar {bar:g} is past the end of the sequence")
    if at < 0:
        raise ValueError(f"bar {bar:g} is before the start of the sequence")
    return at


def _apply(e: Edit, r: MidiRegion, m: Meter, lines: EventLines) -> tuple[str, EventLines]:
    notes, v = sum(is_note(h) for h, _ls in lines), e.value
    if e.flag == "transpose":
        require_no_poly_aftertouch(lines, "a transpose")
        return f"{notes} note(s) transposed {v:+d}", edit(lines, lambda p: gt.transpose(p, v))
    if e.flag == "velocity":
        factor, offset = v
        return (f"velocity of {notes} note(s) {f'{offset:+d}' if offset else f'x{factor:g}'}",
                edit(lines, lambda p: gt.scale_velocity(p, factor, offset)))
    if e.flag == "move":
        return f"{len(lines)} event(s) moved {v:+d} tick(s)", edit(lines, lambda p: gt.shift(p, v))
    if e.flag == "delete":
        require_no_poly_aftertouch(lines, "a delete")
        kept, gone = gt.delete(to_part(lines), v)
        return f"{gone} note(s){'' if v is None else f' of pitch {v}'} deleted", from_part(kept)
    if e.flag == "remap":
        new, unmapped = remap(lines, *v)
        left = ", ".join(f"{pitch} x{n}" for pitch, n in sorted(unmapped.items()))
        return (f"{notes - sum(unmapped.values())} of {notes} note(s) remapped {v[0]} -> {v[1]}"
                + (f"; no {v[1]} counterpart, pitch kept: {left}" if left else "")), new
    meters = meter_map(m)
    return (f"{notes} note(s) quantized to 1/{PPQ * 4 // v}",
            edit(lines, lambda p: gt.quantize(p, v, meters, start=r.start - BAR_ONE)))


def _in_place(data: bytes, count: int | None, e: Edit, r: MidiRegion, m: Meter) -> bytes:
    said: list[str] = []

    def change(lines: EventLines) -> EventLines:
        text, new = _apply(e, r, m, lines)
        said.append(text)
        return new
    data = edit_region(data, r.slot, change, track_count=count)
    print(f"  region {e.number} {r.name!r} on {r.track!r}: {said[0]}")
    return data


def _copy(data: bytes, count: int | None, e: Edit, r: MidiRegion, m: Meter) -> bytes:
    track, bar = e.value
    at = bar_tick(m, bar)
    if e.flag == "copy-region":
        data, rep = copy_region(data, r.slot, track, at, track_count=count)
        loop = "; its loop flag was not copied" if rep["loop"] else ""
        print(f"  region {e.number} {r.name!r} copied to {track!r} at bar {bar:g}: {rep['events']} event(s), "
              f"slot {rep['slot']}{loop}")
        return data
    data, rep = copy_notes(data, r.slot, at, track=track or r.track, track_count=count)
    print(f"  region {e.number} {r.name!r}: {rep['events']} event(s) into {rep['region']!r} on {rep['track']!r} "
          f"at bar {bar:g}")
    return data


def run(data: bytes, count: int | None, resolved: list[tuple[Edit, MidiRegion]], *, copies: bool) -> bytes:
    """The in-place edits, or with ``copies`` the copies, in command-line order."""
    m = meter(data)
    for e, r in resolved:
        if (e.flag in COPIES) != copies:
            continue
        try:
            data = (_copy if copies else _in_place)(data, count, e, r, m)
        except (ValueError, OverflowError, struct.error) as err:
            raise CommandError(f"--{e.flag} {e.number}: {err}") from None
    return data
