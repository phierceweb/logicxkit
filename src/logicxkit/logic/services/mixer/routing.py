"""Set where a channel outputs to, and which input it records from.

Both are 16-byte UUIDs at the tail of the `OCuA` channel record (see `binding.py`): the
destination's own UUID at `[len-32 : len-16]`, the `Input N` channel's own UUID at
`[len-16 :]`. Every record the owner has is rewritten, as `levels` does, with its routing words
to match (`route_words`). A class-6 record carries neither and is refused (`binding.TRAILER`).
"""

from __future__ import annotations

from .binding import UUID_LEN, channels, stamp_uuids
from .mixer import CHANNEL_TAG
from .route_words import with_words
from ..stream.stream import HEADER, NO_KEY, project_records
from ..stream.validate import require_full_walk, require_valid

_MIN_PAYLOAD = 200


def _set_tail(data: bytes, owner: int, **uuids: bytes) -> bytes:
    require_full_walk(data)
    out, hit = [], False
    for record in project_records(data):
        raw = record.raw
        if (record.tag == CHANNEL_TAG and record.key == NO_KEY and record.owner == owner
                and len(raw) - HEADER > _MIN_PAYLOAD):
            raw = stamp_uuids(raw, **uuids)
            hit = True
        out.append(raw)
    if not hit:
        raise ValueError(f"no channel record for owner {owner}")
    result = with_words(data[:24] + b"".join(out), [owner])
    require_valid(result)
    return result


def set_output(data: bytes, owner: int, dest_owner: int) -> bytes:
    """Route ``owner`` to the channel ``dest_owner`` (a `Bus N`, `Output N-M` or aux)."""
    chans = channels(data)
    if dest_owner not in chans:
        raise ValueError(f"no destination channel {dest_owner}")
    return _set_tail(data, owner, destination=chans[dest_owner].uuid)


def set_input(data: bytes, owner: int, input_owner: int | None) -> bytes:
    """Feed ``owner`` from ``input_owner``: an `Input N` for a track, a `Bus N` for an aux —
    the same tail field in both cases (the template's auxes carry their bus there). An audio
    track takes a pair only when stereo and one input only when mono, as on every Logic save on
    hand: the format byte (`+86`) is the width's (`channel_width.set_channel_format`). ``None``
    is no input: the all-zero field every unfed channel carries, and on an aux the No Input
    source bytes as well (`instout.NO_SOURCE`) — Logic reads a zeroed source as Input 1-2."""
    if input_owner is None:
        out = _set_tail(data, owner, source=bytes(UUID_LEN))
        if channels(out)[owner].label.startswith("Aux "):
            from .instout import unbind_instrument_output
            out = unbind_instrument_output(out, owner)
        return out
    chans = channels(data)
    if input_owner not in chans or not chans[input_owner].label.startswith(("Input", "Bus ")):
        raise ValueError(f"{input_owner} is not an Input or Bus channel")
    source, chan = chans[input_owner].label, chans.get(owner)
    if chan is not None and chan.label.startswith("Audio ") and source.startswith("Input "):
        pair = "-" in source
        if pair != chan.stereo_input:
            raise ValueError(f"{chan.label} records {'stereo' if chan.stereo_input else 'mono'} and "
                             f"{source} is {'a pair' if pair else 'one input'}: set the channel's width first")
    return _set_tail(data, owner, source=chans[input_owner].uuid)
