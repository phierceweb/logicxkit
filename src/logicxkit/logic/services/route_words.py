"""The routing words a class-7 channel keeps beside its UUIDs (`binding`), written from what the
UUIDs name, so a written record says the same thing both ways, as Logic's own re-save of a written
route makes it (`route-b01-resave`). A word whose channel the decode does not name is left as it
was, and so is an aux's input word when no UUID feeds it: an instrument output keeps its source there."""

from __future__ import annotations

import struct

from .binding import INPUT_WORD_AT, NO_ROUTE, OUTPUT_WORD_AT, channels, output_word, trailer
from .mixer import device_inputs, is_mixer_record
from .stream import HEADER, project_records, reassemble


def input_word(label: str, inputs: int, *, stereo: bool, aux: bool) -> int | None:
    """The `+94` word naming the input ``label`` (`Input 3`, `Input 1-2`, an aux's `Bus 5`):
    `binding._input_by_word` inverted; None where that names no such source."""
    kind, _, number = label.partition(" ")
    first = number.split("-")[0]
    if not first.isdigit():
        return None
    if kind == "Input":
        return int(first) - 1
    if kind == "Bus" and aux:
        return int(first) - 1 + (inputs // 2 if stereo else inputs)
    return None


def _words(c, by_uuid: dict, inputs: int) -> tuple[int | None, int | None]:
    out = NO_ROUTE if not any(c.dest_uuid) else None
    if out is None and c.dest_uuid in by_uuid:
        try:
            out = output_word(by_uuid[c.dest_uuid], inputs)
        except ValueError:
            out = None
    aux = c.label.startswith("Aux ")
    if not c.label.startswith(("Audio ", "Aux ")) or (aux and not any(c.input_uuid)):
        return out, None
    if not any(c.input_uuid):
        return out, NO_ROUTE
    label = by_uuid.get(c.input_uuid)
    return out, None if label is None else input_word(label, inputs, stereo=c.stereo_input, aux=aux)


def with_words(data: bytes, owners) -> bytes:
    """``data`` with the output and input words of ``owners``' channel records set to what their
    UUIDs name."""
    inputs, chans = device_inputs(data), channels(data)
    if not inputs:
        return data
    by_uuid = {c.uuid: c.label for c in chans.values() if any(c.uuid)}
    words = {o: _words(chans[o], by_uuid, inputs) for o in owners
             if o in chans and trailer(chans[o].ver)[1] is not None
             and chans[o].label.startswith(("Audio ", "Inst ", "Aux "))}
    out, changed = [], False
    for r in project_records(data):
        raw = r.raw
        if is_mixer_record(r) and r.owner in words:
            buf = bytearray(raw)
            for at, word in zip((OUTPUT_WORD_AT, INPUT_WORD_AT), words[r.owner], strict=True):
                if word is not None:
                    struct.pack_into("<H", buf, HEADER + at, word)
            raw = bytes(buf)
        changed |= raw != r.raw
        out.append(raw)
    return reassemble(data, out) if changed else data
