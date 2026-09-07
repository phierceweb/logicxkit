"""Events inside a sequence's `qSvE` payload — the tempo track, the arrangement track.

The payload is 16-byte lines. A line whose byte 7 has its top bit clear starts an event:
type u16 at +0 (a tempo event Logic added carried a nonzero word at +2, undecoded), tick u32
at +4 (960 per quarter, bar 1 at tick 38400). A line whose byte 7
has the top bit set continues the event before it — 0x88 carries the event's data, 0xb4
and 0xb1 a tempo event's curve. Type 0xf1 at tick 0x3fffffff ends the sequence. Read the
same way in every song on hand (2026-09-06).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

LINE = 16
END_TYPE = 0xF1
DATA_LINE = 0x88
KIND_AT = 7
PPQ = 960
BAR_ONE = 38400


@dataclass(frozen=True)
class Event:
    type: int
    tick: int
    head: bytes                # the 16-byte first line
    lines: tuple[bytes, ...]   # its continuation lines, in order

    @property
    def extra(self) -> int:
        """The word at +2 — nonzero on a tempo event Logic added, meaning unknown."""
        return struct.unpack_from("<H", self.head, 2)[0]

    def line(self, kind: int) -> bytes | None:
        return next((ln for ln in self.lines if ln[KIND_AT] == kind), None)

    @property
    def data(self) -> bytes:
        return self.line(DATA_LINE) or b"\0" * LINE


def is_continuation(line: bytes) -> bool:
    return len(line) == LINE and bool(line[KIND_AT] & 0x80)


def events(payload: bytes) -> list[Event]:
    """Every event before the end marker, with its continuation lines."""
    out: list[Event] = []
    head, lines = None, []
    for off in range(0, len(payload) - LINE + 1, LINE):
        ln = payload[off:off + LINE]
        if is_continuation(ln):
            if head is not None:
                lines.append(ln)
            continue
        if head is not None:
            out.append(_event(head, lines))
        if struct.unpack_from("<H", ln, 0)[0] == END_TYPE:
            return out
        head, lines = ln, []
    if head is not None:
        out.append(_event(head, lines))
    return out


def _event(head: bytes, lines: list[bytes]) -> Event:
    kind, _extra, tick = struct.unpack_from("<HHI", head, 0)
    return Event(kind, tick, head, tuple(lines))


def bar(tick: int, beats_per_bar: int = 4) -> float:
    """Bar number for a constant meter — the display's number, fractional inside a bar."""
    return (tick - BAR_ONE) / (PPQ * beats_per_bar) + 1
