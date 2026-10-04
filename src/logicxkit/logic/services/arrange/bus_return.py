"""A bus put in use, as Logic leaves one that an output or a send first goes to.

Logic 12.4 setting a track's output to a bus nothing used (`route-out-bus-logic`), and its own
sends to unused buses (`send-bus-1-logic`, `send-two-base-3-logic`): the bus takes a UUID of its
own in place of its placeholder, and the lowest free `Aux` comes into use fed from it — stereo,
output Output 1-2, with an environment object, a flat row and a sequence of its own and no
arrange row. A second output to the same bus adds nothing (`route-out-bus-second-logic`).

A bus left on its placeholder shows and plays, and Logic keeps it so on a re-save
(`route-resave-logic`), but it is no shared output to Logic's Create Track Stack
(`stack-summing-placeholder-*`). Every channel and send that named the placeholder is moved to
the new UUID, so a project that carries such a bus comes out as Logic's own.
"""

from __future__ import annotations

from ..mixer.binding import channels, input_labels, stamp_uuids, uuids_of
from ..mixer.channel_alloc import free_aux_stub
from ..mixer.mixer import is_mixer_record
from ..mixer.routing import set_input
from ..mixer.sends import DEST_UUID_AT, is_send
from ..stream.recbuild import fresh_uuid
from ..stream.stream import HEADER, project_records, reassemble
from ..stream.validate import require_full_walk, require_valid
from .addtrack import add_track
from .stack_summing import BUS_PLACEHOLDER

UUID_LEN = 16


def _with_own_uuid(data: bytes, bus_owner: int, placeholder: bytes) -> bytes:
    """The bus on a fresh UUID, and every channel output, channel input and send that named
    its placeholder with it."""
    uuid, out = fresh_uuid(), []
    for r in project_records(data):
        raw = r.raw
        if is_mixer_record(r):
            _own, destination, source = uuids_of(raw)
            if r.owner == bus_owner:
                raw = stamp_uuids(raw, own=uuid)
            if destination == placeholder:
                raw = stamp_uuids(raw, destination=uuid)
            if source == placeholder:
                raw = stamp_uuids(raw, source=uuid)
        elif is_send(r) and raw[HEADER + DEST_UUID_AT:HEADER + DEST_UUID_AT + UUID_LEN] == placeholder:
            raw = raw[:HEADER + DEST_UUID_AT] + uuid + raw[HEADER + DEST_UUID_AT + UUID_LEN:]
        out.append(raw)
    return reassemble(data, out)


def use_bus(data: bytes, bus_owner: int, track_count: int | None = None) -> tuple[bytes, dict]:
    """``data`` with the bus ``bus_owner`` in use -> ``(project, report)``; unchanged when it has
    a UUID of its own and an aux fed from it. ``report["aux"]`` is the aux brought into use, None
    when one was there; a fresh aux strip moves the owners above it, so read them again."""
    require_full_walk(data)
    bus = channels(data)[bus_owner]
    if not bus.label.startswith("Bus "):
        raise ValueError(f"{bus.label} is not a bus")
    report = {"bus": bus.label, "minted": bus.uuid.startswith(BUS_PLACEHOLDER), "aux": None}
    if report["minted"]:
        data = _with_own_uuid(data, bus_owner, bus.uuid)
    chans, feeds = channels(data), input_labels(data)
    if not any(c.in_use and c.label.startswith("Aux ") and feeds.get(o) == bus.label for o, c in chans.items()):
        try:
            name = chans[free_aux_stub(chans)].label
        except ValueError:                      # a fresh strip after the highest, as `add_track` makes one
            name = f"Aux {1 + max(int(c.label[4:]) for c in chans.values() if c.label.startswith('Aux '))}"
        data, made = add_track(data, name=name, after=0, kind="aux", bind_stub=True, arrange=False,
                               track_count=track_count)
        owners = {c.label: o for o, c in channels(data).items()}
        data = set_input(data, made["owner"], owners[bus.label])
        report["aux"] = channels(data)[made["owner"]].label
    if report["minted"] or report["aux"]:
        require_valid(data)
    return data, report
