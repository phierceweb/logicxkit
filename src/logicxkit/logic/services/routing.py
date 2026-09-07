"""Set where a channel outputs to, and which input it records from.

Both are 16-byte UUIDs at the tail of the `OCuA` channel record (see `binding.py`): the
destination's own UUID at `[len-32 : len-16]`, the `Input N` channel's own UUID at
`[len-16 :]`. Every record the owner has is rewritten, as `levels` does.
"""

from __future__ import annotations

from .binding import DEST_UUID_FROM_END, INPUT_UUID_FROM_END, UUID_LEN, channels
from .insert import CHANNEL_TAG, HEADER, NO_KEY, project_records
from .validate import require_full_walk, require_valid

_MIN_PAYLOAD = 200


def _set_tail(data: bytes, owner: int, from_end: int, uuid: bytes) -> bytes:
    require_full_walk(data)
    out, hit = [], False
    for record in project_records(data):
        raw = record.raw
        if (record.tag == CHANNEL_TAG and record.key == NO_KEY and record.owner == owner
                and len(raw) - HEADER > _MIN_PAYLOAD):
            buf = bytearray(raw)
            n = len(buf)
            buf[n - from_end:n - from_end + UUID_LEN] = uuid
            raw = bytes(buf)
            hit = True
        out.append(raw)
    if not hit:
        raise ValueError(f"no channel record for owner {owner}")
    result = data[:24] + b"".join(out)
    require_valid(result)
    return result


def set_output(data: bytes, owner: int, dest_owner: int) -> bytes:
    """Route ``owner`` to the channel ``dest_owner`` (a `Bus N`, `Output N-M` or aux)."""
    chans = channels(data)
    if dest_owner not in chans:
        raise ValueError(f"no destination channel {dest_owner}")
    return _set_tail(data, owner, DEST_UUID_FROM_END, chans[dest_owner].uuid)


def set_input(data: bytes, owner: int, input_owner: int | None) -> bytes:
    """Feed ``owner`` from ``input_owner``: an `Input N` for a track, a `Bus N` for an aux —
    the same tail field in both cases (the template's auxes carry their bus there). ``None``
    is no input: the all-zero field every unfed channel carries, and on an aux the No Input
    source bytes as well (`instout.NO_SOURCE`) — Logic reads a zeroed source as Input 1-2."""
    if input_owner is None:
        out = _set_tail(data, owner, INPUT_UUID_FROM_END, bytes(UUID_LEN))
        if channels(out)[owner].label.startswith("Aux "):
            from .instout import unbind_instrument_output
            out = unbind_instrument_output(out, owner)
        return out
    chans = channels(data)
    if input_owner not in chans or not chans[input_owner].label.startswith(("Input", "Bus ")):
        raise ValueError(f"{input_owner} is not an Input or Bus channel")
    return _set_tail(data, owner, INPUT_UUID_FROM_END, chans[input_owner].uuid)
