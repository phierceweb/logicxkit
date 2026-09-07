"""The Signature track — time signatures and key signatures. Read from the files on hand
(2026-09-06: eleven 4/4 songs and one in 5/4 with a change to 4/4) and two of Logic's own
edits of that song (5/4 -> 3/4 at bar 1, C -> G major).

The first sequence triple of the record stream. Its `qSvE` events (`events.py`):

    type 0x30  time signature      head +12  numerator      head +11  denominator, log2
                                   data +8   i16 bar index, bar 1 = 0    data +12  u32 bar 1's tick
    type 0x32  key signature       head +12  7 + sharps, plus 0x10 for a minor key (C major 7,
                                             G major 8, A minor 0x17, E minor 0x18; from
                                             Logic's own edits)

Bit 7 of head +15 marks the event Logic last edited. The first time signature sits on the
earliest bar line before bar 1 — tick 0 for 4/4 and 5/4, tick 960 for 3/4. The song record
also carries the key's root in semitones above C at `gnoS +179` and +879 (0 -> 7 on that edit).
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import BAR_ONE, PPQ, Event, events
from .insert import HEADER, project_records
from .sequence import sequences

TIME_TYPE, KEY_TYPE = 0x30, 0x32
DENOM_LOG2_AT, NUMERATOR_AT = 11, 12
BAR_INDEX_AT, TICK_AT = 8, 12
KEY_AT = 12


@dataclass(frozen=True)
class TimeSignature:
    tick: int
    numerator: int
    denominator: int

    @property
    def bar_ticks(self) -> int:
        return PPQ * 4 * self.numerator // self.denominator


MAJOR_KEYS = ("Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#")
MINOR_KEYS = ("Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#")
KEY_OF_C = 7
MINOR = 0x10


@dataclass(frozen=True)
class KeySignature:
    tick: int
    number: int

    @property
    def name(self) -> str:
        """``G major`` or ``E minor``: the accidentals from the low nibble, the mode from bit 0x10."""
        idx, minor = self.number & 0x0F, bool(self.number & MINOR)
        if not 0 <= idx < len(MAJOR_KEYS):
            return f"key {self.number}"
        return f"{MINOR_KEYS[idx]} minor" if minor else f"{MAJOR_KEYS[idx]} major"

    @property
    def root(self) -> str:
        return self.name.split(" ")[0]


def key_number(name: str) -> int:
    """The signature track's number for a key name: ``G``, ``Bb``, ``F#``, ``A minor``."""
    words = name.strip().split()
    if not words:
        raise ValueError("no key name")
    mode = words[1].lower() if len(words) > 1 else "major"
    if mode not in ("major", "minor"):
        raise ValueError(f"{name!r}: the mode must be major or minor")
    n = words[0][0].upper() + words[0][1:].replace("B", "b") if len(words[0]) > 1 else words[0].upper()
    table = MINOR_KEYS if mode == "minor" else MAJOR_KEYS
    if n not in table:
        raise ValueError(f"{name!r} is not a {mode} key Logic names; one of {', '.join(table)}")
    return table.index(n) | (MINOR if mode == "minor" else 0)


def signature_sequence(records) -> int | None:
    for t in sequences(records)[:6]:
        if any(e.type in (TIME_TYPE, KEY_TYPE) for e in events(records[t.end].raw[HEADER:])):
            return t.end
    return None


def _time(e: Event) -> TimeSignature:
    return TimeSignature(e.tick, e.head[NUMERATOR_AT], 1 << e.head[DENOM_LOG2_AT])


def read_signatures(data: bytes) -> tuple[list[TimeSignature], list[KeySignature]]:
    """(time signatures, key signatures) in tick order; a 4/4 at tick 0 when the track is missing."""
    records = project_records(data)
    i = signature_sequence(records)
    if i is None:
        return [TimeSignature(0, 4, 4)], []
    evs = events(records[i].raw[HEADER:])
    times = sorted((_time(e) for e in evs if e.type == TIME_TYPE), key=lambda s: s.tick)
    keys = sorted((KeySignature(e.tick, e.head[KEY_AT]) for e in evs if e.type == KEY_TYPE), key=lambda k: k.tick)
    return times or [TimeSignature(0, 4, 4)], keys


class Meter:
    """Bar arithmetic over a song's time signatures."""

    def __init__(self, times: list[TimeSignature]):
        self.times = times

    def bar(self, tick: int) -> float:
        """The display's bar number, fractional inside a bar; bar 1 is at tick 38400."""
        return self._forward(tick)

    def _forward(self, tick: int) -> float:
        # count whole bars from BAR_ONE in either direction, honouring each signature's span
        sigs = [s for s in self.times if s.tick <= BAR_ONE] or self.times[:1]
        current = sigs[-1]
        pos, bar = BAR_ONE, 1.0
        if tick >= BAR_ONE:
            later = [s for s in self.times if s.tick > BAR_ONE]
            for s in later:
                if tick < s.tick:
                    break
                bar += (s.tick - pos) / current.bar_ticks
                pos, current = s.tick, s
            return bar + (tick - pos) / current.bar_ticks
        return 1.0 - (BAR_ONE - tick) / current.bar_ticks

    def bars(self, ticks: int, at: int) -> float:
        """A length in bars of the signature in force at ``at``."""
        current = ([s for s in self.times if s.tick <= at] or self.times[:1])[-1]
        return ticks / current.bar_ticks


def meter(data: bytes) -> Meter:
    return Meter(read_signatures(data)[0])
