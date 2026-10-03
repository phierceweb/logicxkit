"""A Standard MIDI File (format 1, the project's PPQ) from the regions `midi.read_midi` reads,
written through groovebin: track 0 carries the song's tempo events and time signatures, then one
track per region named after its track and region. Bar 1 is the file's tick 0; times are region
start plus each event's offset; a note-off carries velocity 64. The file has no time before bar
1, so an event there is refused; the meter in force at bar 1 (Logic files it on a bar line
before) goes at 0."""

from __future__ import annotations

from collections import Counter

from groovebin.events import Event, Note
from groovebin.midi import write
from groovebin.song import Part, Song

from ..song.events import BAR_ONE, PPQ
from .midi import MidiRegion
from ..song.signature import read_signatures
from ..song.tempo import project_tempo, read_tempo_events

NOTE_OFF_VELOCITY = 64
STATUS = {"controller": 0xB0, "program": 0xC0, "bend": 0xE0}


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _meta(tick: int, kind: int, payload: bytes) -> Event:
    return Event(tick, bytes([0xFF, kind]) + _vlq(len(payload)) + payload)


def tempo_map(data: bytes) -> list[tuple[int, float]]:
    """``(absolute tick, bpm)`` for every tempo event, ramp points included; the bar-1 tempo
    alone when the song has no tempo track."""
    return [(e.position, e.bpm) for e in read_tempo_events(data)] or [(BAR_ONE, project_tempo(data)[1])]


def meter_map(data: bytes) -> list[tuple[int, int, int]]:
    """``(absolute tick, numerator, denominator)`` for every time signature."""
    return [(s.tick, s.numerator, s.denominator) for s in read_signatures(data)[0]]


def _conductor(tempos: list[tuple[int, float]], meters: list[tuple[int, int, int]]) -> Part:
    early = [t for t, _bpm in tempos if t < BAR_ONE]
    if early:
        raise ValueError(f"a tempo event at tick {early[0]} is before bar 1, which a Standard MIDI File cannot hold")
    events = [_meta(t - BAR_ONE, 0x51, round(60_000_000 / bpm).to_bytes(3, "big")) for t, bpm in tempos]
    ordered = sorted(meters)
    placed = [m for m in ordered if m[0] <= BAR_ONE][-1:] + [m for m in ordered if m[0] > BAR_ONE]
    events += [_meta(max(t - BAR_ONE, 0), 0x58, bytes([n, d.bit_length() - 1, 24, 8])) for t, n, d in placed]
    return Part(PPQ, (), tuple(events))


def unexportable(regions: list[MidiRegion]) -> Counter:
    """Events the file cannot carry, by kind: polyphonic aftertouch and channel pressure read
    from a region are not written, since their order against notes is unmeasured."""
    return Counter(e.kind for r in regions for e in r.played if e.kind != "note" and e.kind not in STATUS)


def _track(r: MidiRegion) -> Part:
    """The events the region plays: a split leaves both pieces holding the parent's list."""
    played = r.played
    if any(e.tick < BAR_ONE for e in played):
        raise ValueError(f"region {r.name!r} on {r.track!r} has events before bar 1, which a Standard MIDI File cannot hold")
    name = f"{r.track}: {r.name}".encode("utf-8")
    notes, events = [], [_meta(0, 0x03, name)]
    for e in played:
        at, ch = e.tick - BAR_ONE, e.channel - 1
        if e.kind == "note":
            notes.append(Note(at, e.length, e.channel, e.pitch, e.velocity, NOTE_OFF_VELOCITY))
        elif e.kind in STATUS:
            data = bytes([STATUS[e.kind] | ch, e.data1]) + (b"" if e.kind == "program" else bytes([e.data2]))
            events.append(Event(at, data))
    return Part(PPQ, tuple(notes), tuple(events))


def write_smf(regions: list[MidiRegion], *, tempos: list[tuple[int, float]], meters: list[tuple[int, int, int]]) -> bytes:
    """``tempos`` and ``meters`` as `tempo_map` and `meter_map` give them."""
    return write(Song(PPQ, 1, (_conductor(tempos, meters), *(_track(r) for r in regions))))
