"""Writers for the Region inspector's rows beyond the fades (`region_params.py`): the parameters
and the colour on one region, and a crossfade from a region into the one over it, written as
Logic's X-Fade drag writes one — the underneath region's fade-out (ms, curve, type) with `+66` =
0x20 on it and 0x80 on the region over it; `+68`, which Logic rewrites when it edits the length,
is left as found."""

from __future__ import annotations

from dataclasses import replace

from .audio_regions import REGION_TAG, read_audio_regions
from .fades import CROSS_IN, CROSS_OUT, OUT_TYPES, with_fade
from ..stream.stream import HEADER, project_records
from ..midi.midi import COLOUR_AFTER_NAME, name_end
from ..stream.recbuild import rec
from .region_edit import _container, _entry, _finish, _require_sole, _rewrite, located
from .region_params import REGION_COLOUR_AT, RegionParams, with_params
from ..stream.sequence import sequences, triple_by_slot


def _audio(data: bytes, number: int, track_count: int | None, what: str):
    loc = located(data, number, track_count)
    if loc.audio is None:
        raise ValueError(f"region {number} is a MIDI region; {what} is an audio region's")
    return loc


def set_params(data: bytes, number: int, params: RegionParams, track_count: int | None = None) -> bytes:
    loc = _audio(data, number, track_count, "the inspector's Gain, Delay, Transpose, Fine Tune and Reverse")
    records = project_records(data)
    song, payload = _container(records, track_count)
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(payload, loc.audio.at, with_params(_entry(payload, loc), params)))
    return _finish(data, out)


def set_colour(data: bytes, number: int, colour: int, track_count: int | None = None) -> bytes:
    """Region ``number`` coloured ``colour``, a palette index (the Color window's swatch k is 24 + k)."""
    if not 0 <= colour <= 255:
        raise ValueError("a region colour is a palette index 0-255")
    loc = located(data, number, track_count)
    records = project_records(data)
    out = [r.raw for r in records]
    if loc.audio:
        raw = bytearray(records[loc.audio.record].raw)
        raw[HEADER + REGION_COLOUR_AT] = colour
        out[loc.audio.record] = rec(REGION_TAG, records[loc.audio.record].raw, bytes(raw[HEADER:]))
    else:
        _require_sole(loc, "colouring")
        t = triple_by_slot(sequences(records), loc.midi.slot)
        raw = bytearray(records[t.start].raw)
        raw[name_end(raw) + COLOUR_AFTER_NAME] = colour
        out[t.start] = bytes(raw)
    return _finish(data, out)


def overlapped(data: bytes, number: int, spt: float, track_count: int | None = None):
    """The audio region starting inside region ``number``'s span on its track — the one a crossfade
    goes to — with the overlap in ticks; none or several are refused."""
    loc = _audio(data, number, track_count, "a crossfade")
    a = loc.audio
    end = a.start + a.frames / spt
    over = [r for r in read_audio_regions(data, track_count) if r.object_id == a.object_id and a.start < r.start < end]
    if len(over) != 1:
        has = f"{len(over)} regions start" if over else "no region starts"
        raise ValueError(f"region {number} {a.name!r}: {has} inside it on {a.track!r}; a crossfade needs exactly one")
    return loc, over[0], end - over[0].start


def set_crossfade(data: bytes, number: int, *, ms: int | None, curve: int, kind: str, spt: float, rate: int,
                  track_count: int | None = None) -> bytes:
    """A crossfade of ``ms`` (the overlap when None) from region ``number`` into the region over it,
    written as Logic's X-Fade drag writes one."""
    if kind not in OUT_TYPES.values() or kind == "out":
        raise ValueError("a crossfade type is x, eqp or xs")
    loc, top, overlap = overlapped(data, number, spt, track_count)
    length = round(overlap * spt / rate * 1000) if ms is None else ms
    records = project_records(data)
    song, payload = _container(records, track_count)
    under = with_fade(_entry(payload, loc), replace(loc.audio.fade, out_ms=length, out_curve=curve, out_type=kind))
    under = bytearray(under)
    under[CROSS_OUT[0]] |= CROSS_OUT[1]
    over = bytearray(payload[top.at:top.at + len(under)])
    over[CROSS_IN[0]] |= CROSS_IN[1]
    out = [r.raw for r in records]
    new = _rewrite(payload, loc.audio.at, bytes(under))
    at = next(r.at for r in read_audio_regions(data, track_count) if r.record_key == top.record_key)
    out[song.end] = rec(b"qSvE", records[song.end].raw, _rewrite(new, at, bytes(over)))
    return _finish(data, out)
