"""A plug-in slot's side-chain source: payload `+144` the kind, `+145` the zero-based number —
0 with none set, 0x40 an audio track, 0x41 an input of the audio interface, 0x43 an instrument
track, 0x45 a bus. A Compressor pointed at Bus 1, Bus 2 and Audio 1, one save each, changed that
word and nothing else in the project; a Noise Gate and Pro-C 2 at Bus 1 carry the same (the
`sidechain-*` goldens); Input 2 saved as 0x41 1 and Inst 1 as 0x43 0 (`sidechain-input2-logic`,
`sidechain-inst1-logic`). The word is Logic's, alike on a third-party slot, and names the channel
by number, so a strip moved between projects keeps its side chain by the source's *name*: a bus by
the aux it feeds, a track by its name, else the mixer label. An input is the interface's own, the
same in every project, and stays as it is.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .binding import bound_channels, channels
from .environment import channel_objects
from .insert import HEADER

SIDE_CHAIN_AT = 144
KINDS = {0x40: "Audio", 0x41: "Input", 0x43: "Inst", 0x45: "Bus"}
INPUT = 0x41
_BY_LABEL = {v: k for k, v in KINDS.items()}
_LABEL = re.compile(r"^(Audio|Input|Inst|Bus|Aux) (\d+)$")


@dataclass(frozen=True)
class SideChain:
    kind: int
    index: int

    @property
    def label(self) -> str:
        """The mixer label of the source channel."""
        return f"{KINDS.get(self.kind, f'kind 0x{self.kind:02x}')} {self.index + 1}"


def side_chain(payload: bytes) -> SideChain | None:
    if len(payload) < SIDE_CHAIN_AT + 2 or payload[SIDE_CHAIN_AT] == 0:
        return None
    return SideChain(payload[SIDE_CHAIN_AT], payload[SIDE_CHAIN_AT + 1])


def with_side_chain(raw: bytes, sc: SideChain | None) -> bytes:
    """The slot record with its side chain set to ``sc``; None clears it (a record too short
    to carry one has none to clear)."""
    at = HEADER + SIDE_CHAIN_AT
    if at + 2 > len(raw):
        if sc is None:
            return raw
        raise ValueError("the record is too short to carry a side chain")
    buf = bytearray(raw)
    buf[at], buf[at + 1] = (sc.kind, sc.index) if sc else (0, 0)
    return bytes(buf)


def _norm(name: str) -> str:
    return unicodedata.normalize("NFC", name).strip().casefold()


def _names(data: bytes) -> dict[int, str]:
    """owner -> the name of the Environment object its channel is bound to (a track's name,
    an aux return's), where that is not just the mixer label."""
    objects = channel_objects(data)
    out = {}
    for obj, owner in bound_channels(data).items():
        name = (objects[obj].name or "").strip() if obj in objects else ""
        if name:
            out[owner] = name
    return out


def _bus_of(data: bytes, chans: dict, owner: int) -> SideChain | None:
    """The bus an aux channel takes its input from, as a side chain."""
    by_uuid = {c.uuid: c for c in chans.values() if any(c.uuid)}
    bus = by_uuid.get(chans[owner].input_uuid)
    m = _LABEL.match(bus.label) if bus else None
    return SideChain(_BY_LABEL["Bus"], int(m.group(2)) - 1) if m and m.group(1) == "Bus" else None


def _as_source(data: bytes, chans: dict, owner: int) -> SideChain | None:
    m = _LABEL.match(chans[owner].label)
    if not m:
        return None
    if m.group(1) == "Aux":
        return _bus_of(data, chans, owner)
    return SideChain(_BY_LABEL[m.group(1)], int(m.group(2)) - 1)


def source_name(data: bytes, sc: SideChain) -> str:
    """What the project calls the source: the track's or aux return's name, else the label."""
    chans, names = channels(data), _names(data)
    for owner, c in chans.items():
        if c.label == sc.label:
            if sc.kind == _BY_LABEL["Bus"]:
                for aux, ac in chans.items():
                    if ac.input_uuid == c.uuid and any(c.uuid) and names.get(aux) not in (None, ac.label):
                        return names[aux]
            return names.get(owner) or sc.label if names.get(owner) != c.label else sc.label
    return sc.label


def resolve(data: bytes, name: str) -> SideChain:
    """The side chain for the channel ``name`` names: a track's or aux return's name, or a
    mixer label; an aux stands for the bus feeding it. Refuses none or several."""
    chans, names, want = channels(data), _names(data), _norm(name)
    hits = {owner for owner, c in chans.items() if _norm(c.label) == want or _norm(names.get(owner, "")) == want}
    found = {_as_source(data, chans, o) for o in hits}
    if not hits and (m := _LABEL.match(name.strip())) and m.group(1) == "Input":
        return SideChain(INPUT, int(m.group(2)) - 1)          # the interface's input, channel or none
    if not hits:
        have = sorted({n for n in names.values()} | {c.label for c in chans.values() if c.in_use})
        raise ValueError(f"no channel named {name!r}; the project has: {', '.join(have[:12])}"
                         + (" …" if len(have) > 12 else ""))
    if None in found:
        labels = sorted(chans[o].label for o in hits if _as_source(data, chans, o) is None)
        raise ValueError(f"{name!r} is on {', '.join(labels)}, which cannot feed a side chain")
    if len(found) > 1:
        raise ValueError(f"{name!r} names several channels: {', '.join(sorted(s.label for s in found))}")
    return found.pop()


def carry(src: bytes, raw: bytes, dst: bytes) -> tuple[bytes, str | None]:
    """A slot record leaving ``src`` for ``dst``: its side chain re-pointed at the channel of
    the same name there, or cleared, with a note saying which; None when nothing changed."""
    sc = side_chain(raw[HEADER:])
    if sc is None or sc.kind == INPUT:
        return raw, None
    name = source_name(src, sc)
    try:
        new = resolve(dst, name)
    except ValueError as e:
        return with_side_chain(raw, None), f"side chain {name!r} cleared: {e}"
    if new == sc:
        return raw, None
    return with_side_chain(raw, new), f"side chain {name!r}: {sc.label} -> {new.label}"
