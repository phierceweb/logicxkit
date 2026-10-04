"""A row that becomes a direct member of a summing stack outputs to that stack's bus: Logic's own
drag into one (`stack-summing-dragged-in-logic`), and a summing stack dragged in, whose aux takes
the outer bus while its members keep theirs (`stack-summing-into-summing-after-logic`). A row
entering a folder inside a summing stack keeps its output (`stack-drag-into-folder-after-logic`),
and so do the members of a folder moved in (`stack-folder-into-summing-after-logic`). A row
that leaves an inner stack for a direct place in the summing stack around it takes the bus too
(`stack-out-of-folder-after-logic`, `stack-out-of-inner-summing-after-logic`). A row already a
direct member keeps whatever output it has, as Logic's own saves keep subtracks routed
elsewhere."""

from __future__ import annotations

import struct

from ..mixer.binding import OUTPUT_WORD_AT, bound_channels, channels, output_word, stamp_uuids
from ..mixer.mixer import device_inputs, is_mixer_record
from ..stream.stream import HEADER, project_records, reassemble


def summing_bus(data: bytes, stack) -> str | None:
    """The `Bus N` feeding a summing stack's aux, None when nothing does."""
    chans = channels(data)
    feed = chans[stack.owner].input_uuid
    return next((c.label for c in chans.values() if c.uuid == feed and c.label.startswith("Bus ")), None)


def to_summing_bus(data: bytes, routes: dict) -> bytes:
    """``data`` with each track object in ``routes`` sending its output, by UUID and word, to the
    bus feeding the summing stack it maps to."""
    owners, chans = bound_channels(data), channels(data)
    feeds: dict[int, tuple[bytes, int]] = {}
    for o, stack in routes.items():
        bus = summing_bus(data, stack)
        if o in owners and bus is not None:
            feeds[owners[o]] = (chans[stack.owner].input_uuid, output_word(bus, device_inputs(data) or 0))
    if not feeds:
        return data
    out = []
    for r in project_records(data):
        raw = r.raw
        if is_mixer_record(r) and r.owner in feeds:
            uuid, word = feeds[r.owner]
            buf = bytearray(raw)
            struct.pack_into("<H", buf, HEADER + OUTPUT_WORD_AT, word)
            raw = stamp_uuids(bytes(buf), destination=uuid)
        out.append(raw)
    return reassemble(data, out)
