"""The slot key range and the headroom Logic keeps above it: how many keys sit between the
longest chain and the `.cst` reference, measured from the input, and the move of every
channel's satellites that keeps it when a chain grows (the logic README, "The slot key range
grows")."""

from __future__ import annotations

import struct

from ..stream.recbuild import with_key
from ..stream.stream import HEADER, project_records, reassemble
from .binding import channels
from .slot_identity import KIND_AT, MIDI_KIND
from .slots import is_plugin_slot


def headroom(data: bytes, first: int, base: int) -> int:
    """Keys Logic keeps between the project's highest slot key and the reference: measured
    from the input, since Logic re-lays a project out to its own figure on load (3 on a
    blank-born project, 6 on a session whose slots start at key 4) and drops what lands past the channel
    records' flag words. The MIDI effects past the first on the channel with the most sit in
    those keys and are not headroom (`instrument-fx-two-midi-one-audio-logic`: Logic put an
    audio effect at key 3 under MIDI effects at 4 and 5 and moved nothing). Never under 3."""
    keys, midi = [], {}
    for r in project_records(data):
        if is_plugin_slot(r, base, first):
            keys.append(r.key)
        elif r.tag == b"UCuA" and first <= r.key < base and len(r.raw) - HEADER > KIND_AT + 2 \
                and struct.unpack_from("<H", r.raw, HEADER + KIND_AT)[0] == MIDI_KIND:
            midi[r.owner] = midi.get(r.owner, 0) + 1
    taken = max(0, max(midi.values(), default=0) - 1)
    return max(3, base - max(keys) - taken) if keys else 3


def grow_range(data: bytes, base: int, by: int, index_base: int) -> bytes:
    """Every channel satellite from two keys under the reference at ``base`` moved up ``by``
    keys, on every channel: the records under the reference, the reference, the archives. A
    plug-in slot there stays: Logic's own save of an instrument with one effect puts the effect
    two keys under the reference (`instrument-es2-over-chromaglow-logic`)."""
    owners = set(channels(data))
    out = [with_key(r.raw, r.key + by) if r.tag == b"UCuA" and r.owner in owners and r.key >= base - 2
           and not is_plugin_slot(r, base, index_base) else r.raw for r in project_records(data)]
    return reassemble(data, out)
