"""Which Environment object each mixer channel is bound to, and where it routes.

Both live at the END of the `OCuA` channel payload, because its length varies per session
(257, 265 and 269 bytes at the same class version):

    [len-48 : len-32]   the bound Environment object's instance UUID (`ivnE` payload[-16:])
    [len-32 : len-16]   the destination channel's own UUID; all-zero on Sub/Master/Output strips
    [len-16 : len]      the INPUT channel's own UUID (`Input N`) on audio channels; zero elsewhere
    +110                the Sub number of the stack this channel sits in (0 = none)
    +24, +25            01 01 once Logic has bound the channel to a track
    +60                 NUL-padded label with a leading space: ' Audio 1', ' Sub 1', ' Bus 15'

Measured 59/59 in-use channels on seven sessions and the Recording template. Folder stacks
bind to the `Sub N` strips, and every member channel carries N at +110.
"""

from __future__ import annotations

from dataclasses import dataclass

from .environment import channel_objects
from .insert import CHANNEL_TAG, HEADER, NO_KEY, project_records

OWN_UUID_FROM_END = 48
DEST_UUID_FROM_END = 32
INPUT_UUID_FROM_END = 16
UUID_LEN = 16
STACK_INDEX_AT = 110
IN_USE_AT = 24
LABEL_AT = 60
_LABEL_MAX = 32
_MIN_PAYLOAD = 200   # the 201-byte stubs are the shortest real channel records
_ZERO = bytes(UUID_LEN)


@dataclass(frozen=True)
class Channel:
    owner: int
    label: str
    in_use: bool
    uuid: bytes
    dest_uuid: bytes
    input_uuid: bytes
    stack_index: int
    size: int


def channel_label(payload: bytes) -> str:
    return payload[LABEL_AT:LABEL_AT + _LABEL_MAX].split(b"\x00")[0].decode("latin-1").strip()


def channels(data: bytes) -> dict[int, Channel]:
    """owner -> its mixer channel, from the longest ``OCuA`` record each owner has."""
    best: dict[int, bytes] = {}
    for record in project_records(data):
        if record.tag != CHANNEL_TAG or record.key != NO_KEY:
            continue
        payload = record.raw[HEADER:]
        if len(payload) > _MIN_PAYLOAD and len(payload) > len(best.get(record.owner, b"")):
            best[record.owner] = payload
    out = {}
    for owner, p in best.items():
        n = len(p)
        out[owner] = Channel(
            owner=owner, label=channel_label(p),
            in_use=p[IN_USE_AT] == 1 and p[IN_USE_AT + 1] == 1,
            uuid=p[n - OWN_UUID_FROM_END:n - OWN_UUID_FROM_END + UUID_LEN],
            dest_uuid=p[n - DEST_UUID_FROM_END:n - DEST_UUID_FROM_END + UUID_LEN],
            input_uuid=p[n - INPUT_UUID_FROM_END:],
            stack_index=p[STACK_INDEX_AT], size=n)
    return out


def bound_objects(data: bytes) -> dict[int, int]:
    """owner -> Environment object id, for every channel whose UUID names an object."""
    by_uuid = {o.uuid: i for i, o in channel_objects(data).items()}
    return {owner: by_uuid[c.uuid] for owner, c in channels(data).items() if c.uuid in by_uuid}


def bound_channels(data: bytes) -> dict[int, int]:
    """Environment object id -> owner of the mixer channel bound to it."""
    return {obj: owner for owner, obj in bound_objects(data).items()}


def output_routing(data: bytes) -> dict[int, int | None]:
    """owner -> owner of the channel it outputs to; ``None`` for a zero or unknown destination."""
    chans = channels(data)
    by_uuid = {c.uuid: owner for owner, c in chans.items() if c.uuid != _ZERO}
    return {owner: (None if c.dest_uuid == _ZERO else by_uuid.get(c.dest_uuid))
            for owner, c in chans.items()}


def input_routing(data: bytes) -> dict[int, int | None]:
    """owner -> owner of the ``Input N`` channel it records from; ``None`` when unset."""
    chans = channels(data)
    by_uuid = {c.uuid: owner for owner, c in chans.items() if c.uuid != _ZERO}
    return {owner: (None if c.input_uuid == _ZERO else by_uuid.get(c.input_uuid))
            for owner, c in chans.items()}


def stack_channels(data: bytes) -> dict[int, int]:
    """Sub number -> owner of the ``Sub N`` strip, the channel a folder stack's fader lives on."""
    out = {}
    for owner, c in channels(data).items():
        if c.label.startswith("Sub ") and c.label[4:].isdigit():
            out[int(c.label[4:])] = owner
    return out


def set_stack_index(raw: bytes, index: int) -> bytes:
    if len(raw) - HEADER <= STACK_INDEX_AT:
        return raw
    buf = bytearray(raw)
    buf[HEADER + STACK_INDEX_AT] = index
    return bytes(buf)

