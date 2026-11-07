"""The mixer's free channel strips: which one a new track binds, and the bytes that bring it into
use (`channel_alloc` makes fresh ones)."""

from __future__ import annotations

from .binding import Channel, stamp_uuids, uuids_of
from .channel_alloc import IN_USE_AT, STACK_INDEX_AT, UUID_LEN, WIDTH
from .mixer import MIXER_MIN
from ..stream.stream import HEADER


SHAPED_STUB_MIN = 240             # a stub Logic pre-shaped for use (245 B here); the 201-byte
                                  # ones are bare and need growing first
BARE_STUB = 201                   # a fresh channel's size too


def is_unused_stub(c: Channel) -> bool:
    """A free bare strip that keeps its own UUID: no track has used it. A deleted track's strip
    loses the UUID (`gone-d2-logic`); a shaped one has grown past the bare size."""
    return not c.in_use and c.size <= BARE_STUB and c.uuid != bytes(len(c.uuid))


def free_audio_stub(chans: dict[int, Channel], only: set[int] | None = None) -> int:
    """The lowest-numbered free `Audio N` strip a track has used — the shaped ones first, the
    order Logic took them in (four adds, 2026-09-04), then a deleted track's bare one
    (`gone-d3-logic`); with ``only``, among those owners alone. A stub no track has used is never
    bound: Logic inserts a fresh strip there instead (`addtrack_pattern.fresh_audio_owner`)."""
    free = [(o, c) for o, c in sorted(chans.items())
            if c.label.startswith("Audio ") and not c.in_use and c.size > MIXER_MIN and not is_unused_stub(c)
            and (only is None or o in only)]
    shaped = [o for o, c in free if c.size >= SHAPED_STUB_MIN]
    if shaped:
        return shaped[0]
    if free:
        return free[0][0]
    raise ValueError("no free Audio channel stub to bind")


def free_aux_stub(chans: dict[int, Channel]) -> int:
    """The lowest-numbered `Aux N` strip no track is using — the one Logic's own Create Track
    Stack (Summing) brought into use for its header (`stack-summing-logic`)."""
    free = [o for o, c in sorted(chans.items())
            if c.label.startswith("Aux ") and not c.in_use and c.size > MIXER_MIN]
    if free:
        return free[0]
    raise ValueError("no free Aux channel stub to bind")


def bind_audio_stub(raw: bytes, *, object_uuid: bytes, input_uuid: bytes,
                    output_uuid: bytes | None, stereo: bool = False, stack_index: int = 0) -> bytes:
    """A stub brought into use: in-use flags, width, the three UUIDs and the stack it sits
    in. The output is only set when the stub has none. An `Aux` stub takes the same bytes
    (Logic's summing header against the save before it, stereo)."""
    p = bytearray(raw[HEADER:])
    p[IN_USE_AT] = p[IN_USE_AT + 1] = 1
    p[STACK_INDEX_AT] = stack_index
    width = 2 if stereo else 1
    for off, by_width in WIDTH.items():
        p[off] = by_width[width]
    out = raw[:HEADER] + bytes(p)
    routed = uuids_of(out)[1] != bytes(UUID_LEN)
    return stamp_uuids(out, own=object_uuid, source=input_uuid,
                       destination=None if routed else output_uuid)
