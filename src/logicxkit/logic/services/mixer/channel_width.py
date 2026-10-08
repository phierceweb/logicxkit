"""A channel record's width, and widening whole channels with the slots they carry."""

from __future__ import annotations

import struct

from ..._binary import find_blocks
from .mixer import CHANNEL_FMT_AT, CHANNEL_TAG
from .slot_width import MONO, STEREO, set_slot_format
from ..stream.stream import BODY_START, HEADER, NO_KEY, TOTAL_AT, project_records
from ..stream.validate import require_full_walk, require_valid

# WIDTH, channel side: three bytes move together, not just the count at +123. The same on every
# session on hand, on both class versions, and on a stereo aux Logic itself wrote. At +78 the
# width is one bit: an audio or aux channel reads 211 mono and 215 stereo, an instrument
# channel 243 and 247 (`instrument-es-m-logic` beside `instrument-es2-logic`).
STEREO_BIT_AT, STEREO_BIT = 78, 0x04
CHANNEL_WIDTH = {86: {MONO: 0, STEREO: 1}, CHANNEL_FMT_AT: {MONO: MONO, STEREO: STEREO}}


def set_channel_format(raw: bytes, fmt: int) -> bytes:
    """Rewrite a channel record's width. Nothing else in the record moves."""
    payload_len = len(raw) - HEADER
    if payload_len <= CHANNEL_FMT_AT or raw[HEADER + CHANNEL_FMT_AT] == fmt:
        return raw
    buf = bytearray(raw)
    at = HEADER + STEREO_BIT_AT
    buf[at] = buf[at] | STEREO_BIT if fmt == STEREO else buf[at] & ~STEREO_BIT
    for off, byfmt in CHANNEL_WIDTH.items():
        buf[HEADER + off] = byfmt[fmt]
    return bytes(buf)


def stereo_strips(records) -> set[int]:
    """Owners whose channel record carries the stereo bit. A deleted stereo track's free strip
    keeps the bit while `+86` and `+123` go back to mono (`gone-d2-logic`: 215, 0, 1)."""
    return {r.owner for r in records if r.tag == CHANNEL_TAG and len(r.raw) - HEADER > STEREO_BIT_AT
            and r.raw[HEADER + STEREO_BIT_AT] & STEREO_BIT}


STEREO_INPUT_AT = 86                 # what feeds the chain is stereo: on an instrument channel, its instrument


def with_channel_io(data: bytes, owner: int, *, stereo_input: bool, output: int | None = None) -> bytes:
    """The project with ``owner``'s channel record saying its input is stereo or not and, with
    ``output``, its width — its slots as they are. The two are separate: under a stereo
    instrument a mono chain keeps the channel mono, `+86` set (`instrument-es2-over-chromaglow-logic`)."""
    out = []
    for r in project_records(data):
        raw = r.raw
        if r.tag == CHANNEL_TAG and r.key == NO_KEY and r.owner == owner and len(raw) - HEADER > CHANNEL_FMT_AT:
            buf = bytearray(set_channel_format(raw, output) if output else raw)
            buf[HEADER + STEREO_INPUT_AT] = int(stereo_input)
            raw = bytes(buf)
        out.append(raw)
    return data[:BODY_START] + b"".join(out)


def widen_channels(data: bytes, want: dict[int, int]) -> tuple[bytes, list[int]]:
    """Set the width of whole channels -> ``(project, [owners actually changed])``.

    Plugins already on the channel are re-stamped to match: a slot carries its own width, so a
    channel widened on its own leaves them at the old one and ``validate_project`` refuses the
    result. Running before ``insert_slots`` also hands it the width to give the slots it places.
    """

    require_full_walk(data)
    from .slot_identity import slot_header
    records = project_records(data)
    # an instrument channel's `+86` is its instrument's width and its instrument keeps the
    # width it was saved at (`instrument-*-logic`): only the chain's output follows a widen there
    instrument_channels = {r.owner for r in records if r.tag == b"UCuA" and r.owner in want
                           and (h := slot_header(r.raw[HEADER:])) is not None and h.instrument}
    out, changed = [], []
    for record in records:
        raw = record.raw
        if record.tag == CHANNEL_TAG and record.key == NO_KEY and record.owner in want:
            new = set_channel_format(raw, want[record.owner])
            if record.owner in instrument_channels:
                buf = bytearray(new)
                buf[HEADER + STEREO_INPUT_AT] = raw[HEADER + STEREO_INPUT_AT]
                new = bytes(buf)
            if new != raw:
                raw = new
                if record.owner not in changed:
                    changed.append(record.owner)
        elif record.owner in want and find_blocks(raw[HEADER:]):
            head = slot_header(raw[HEADER:])
            if head is not None and head.instrument:
                out.append(raw)
                continue
            try:
                raw = set_slot_format(raw, want[record.owner])
            except ValueError as e:
                raise ValueError(f"channel {record.owner} key {record.key}: cannot follow the "
                                 f"channel to width {want[record.owner]} — {e}") from None
        out.append(raw)
    body = b"".join(out)
    head = bytearray(data[:BODY_START])
    struct.pack_into("<I", head, TOTAL_AT, len(body))
    result = bytes(head) + body
    require_valid(result)
    return result, sorted(changed)
