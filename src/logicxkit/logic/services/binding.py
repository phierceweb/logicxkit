"""Which Environment object each mixer channel is bound to, and where it routes.

Both live at the END of the `OCuA` channel payload, because its length varies per session
(257, 265 and 269 bytes at the same class version). At class 7 (Logic 12):

    [len-48 : len-32]   the bound Environment object's instance UUID (`ivnE` payload[-16:])
    [len-32 : len-16]   the destination channel's own UUID; all-zero on Sub/Master/Output strips
    [len-16 : len]      the INPUT channel's own UUID (`Input N`) on audio channels; zero elsewhere

A class-6 record from Logic 11.2 ends after the first: the bound object's UUID is its last 16
bytes (every in-use channel on two Logic 11.2 saves, payloads of 205 to 233 bytes; Logic
12's re-save of the same song grew every channel record by 32). Before 11.2 no object carries
a channel's UUID. A class-6 channel routes by index words, which class 7 keeps beside its UUIDs:

    +92   u16   output: 0xFFFF none; below half the device's inputs the pair `Output 2w+1-2w+2`,
                from there `Bus w - half + 1`
    +94   u16   input: 0xFFFF none; on an audio channel `Input w+1`, or the pair from it when
                +86 is 1; on an aux `Bus w - base + 1`, the base half the device's inputs when
                +86 is 1 and all of them when 0, and past the 256 buses another kind of source
    +86   u8    input format: 0 mono, 1 stereo

On every Logic 12 save on hand the words name what the UUIDs name, but for backups that each
caught one aux a save after its input turned stereo, the word still counted from the mono base. On two Logic 11.2 saves they name what Logic 12.4's conversion of each bound by UUID, on
every routed channel.

    +110                the Sub number of the stack this channel sits in (0 = none)
    +24, +25            01 01 once Logic has bound the channel to a track
    +60                 NUL-padded label with a leading space: ' Audio 1', ' Sub 1', ' Bus 15'

Holds on every in-use channel of the sessions measured and the Recording template. Folder stacks
bind to the `Sub N` strips, and every member channel carries N at +110.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .environment import channel_objects
from .mixer import CHANNEL_TAG, device_inputs
from .stream import HEADER, NO_KEY, VER_OFF, ProjRecord, project_records
from .validate import file_format

TRAILER = {6: (16, None, None), 7: (48, 32, 16)}   # class -> own, destination, input, from the end
UUID_LEN = 16
STACK_INDEX_AT = 110
IN_USE_AT = 24
LABEL_AT = 60
_LABEL_MAX = 32
_MIN_PAYLOAD = 200   # the 201-byte stubs are the shortest real channel records
_ZERO = bytes(UUID_LEN)
OUTPUT_WORD_AT, INPUT_WORD_AT, INPUT_FORMAT_AT = 92, 94, 86
NO_ROUTE = 0xFFFF
BUSES = 256
WORD_ROUTED = (2511,)               # formats whose class-6 channels are measured routing by word
_FIELDS = ("own", "destination", "input")


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
    ver: int
    words: tuple[int, int] = (NO_ROUTE, NO_ROUTE)     # output and input, as indexes
    stereo_input: bool = False


def channel_label(payload: bytes) -> str:
    return payload[LABEL_AT:LABEL_AT + _LABEL_MAX].split(b"\x00")[0].decode("latin-1").strip()


def record_class(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, VER_OFF)[0]


def trailer(ver: int) -> tuple[int | None, int | None, int | None]:
    """Where a class-``ver`` channel record keeps its own, destination and input uuid, from the
    end; ``None`` for one that class does not carry, and for a class not measured."""
    return TRAILER.get(ver, (None, None, None))


def uuids_of(raw: bytes) -> tuple[bytes, bytes, bytes]:
    """The own, destination and input uuid of the channel record ``raw``; zero where its class
    carries none."""
    p = raw[HEADER:]
    return tuple(_ZERO if at is None else p[len(p) - at:len(p) - at + UUID_LEN]
                 for at in trailer(record_class(raw)))


def stamp_uuids(raw: bytes, *, own: bytes | None = None, destination: bytes | None = None,
                source: bytes | None = None, clone: bool = False) -> bytes:
    """The channel record ``raw`` with these uuids where its class keeps them; ``None`` leaves
    one as it is. A destination or input the class does not carry is refused, or skipped on a
    ``clone``, which keeps its pattern's routing; the own uuid is never skipped."""
    ver = record_class(raw)
    buf = bytearray(raw)
    for name, at, value in zip(_FIELDS, trailer(ver), (own, destination, source), strict=True):
        if value is None or (at is None and clone and name != "own"):
            continue
        if at is None:
            raise ValueError(f"a class-{ver} channel record keeps no {name} uuid (Logic 12 writes "
                             "class 7) — where that class keeps it is not decoded")
        buf[len(buf) - at:len(buf) - at + UUID_LEN] = value
    return bytes(buf)


def channels(data: bytes) -> dict[int, Channel]:
    """owner -> its mixer channel, from the longest ``OCuA`` record each owner has."""
    best: dict[int, ProjRecord] = {}
    for record in project_records(data):
        if (record.tag != CHANNEL_TAG or record.key != NO_KEY
                or len(record.raw) - HEADER <= _MIN_PAYLOAD):
            continue
        if record.owner not in best or len(record.raw) > len(best[record.owner].raw):
            best[record.owner] = record
    out = {}
    for owner, record in best.items():
        p = record.raw[HEADER:]
        own, dest, source = uuids_of(record.raw)
        out[owner] = Channel(
            owner=owner, label=channel_label(p),
            in_use=p[IN_USE_AT] == 1 and p[IN_USE_AT + 1] == 1,
            uuid=own, dest_uuid=dest, input_uuid=source,
            stack_index=p[STACK_INDEX_AT], size=len(p), ver=record.ver,
            words=struct.unpack_from("<HH", p, OUTPUT_WORD_AT),
            stereo_input=p[INPUT_FORMAT_AT] == 1)
    return out


def bound_objects(data: bytes) -> dict[int, int]:
    """owner -> Environment object id, for every channel whose UUID names an object."""
    by_uuid = {o.uuid: i for i, o in channel_objects(data).items() if o.uuid != _ZERO}
    return {owner: by_uuid[c.uuid] for owner, c in channels(data).items() if c.uuid in by_uuid}


def bound_channels(data: bytes) -> dict[int, int]:
    """Environment object id -> owner of the mixer channel bound to it."""
    return {obj: owner for owner, obj in bound_objects(data).items()}


def output_routing(data: bytes) -> dict[int, int | None]:
    """owner -> owner of the channel it outputs to; ``None`` for a zero or unknown destination.
    A channel whose record class carries no routing uuid is left out (`output_labels`)."""
    chans = channels(data)
    by_uuid = {c.uuid: owner for owner, c in chans.items() if c.uuid != _ZERO}
    return {owner: (None if c.dest_uuid == _ZERO else by_uuid.get(c.dest_uuid))
            for owner, c in chans.items() if trailer(c.ver)[1] is not None}


def input_routing(data: bytes) -> dict[int, int | None]:
    """owner -> owner of the ``Input N`` channel it records from; ``None`` when unset. A channel
    whose record class carries no routing uuid is left out (`input_labels`)."""
    chans = channels(data)
    by_uuid = {c.uuid: owner for owner, c in chans.items() if c.uuid != _ZERO}
    return {owner: (None if c.input_uuid == _ZERO else by_uuid.get(c.input_uuid))
            for owner, c in chans.items() if trailer(c.ver)[2] is not None}


def _output_by_word(c: Channel, inputs: int) -> str | None:
    word, half = c.words[0], inputs // 2
    if word == NO_ROUTE or not c.label.startswith(("Audio ", "Inst ", "Aux ")):
        return None
    return f"Output {2 * word + 1}-{2 * word + 2}" if word < half else f"Bus {word - half + 1}"


def output_word(label: str, inputs: int) -> int:
    """The `+92` word naming the output ``label`` (`Output 3-4`, `Bus 5`): `_output_by_word` inverted."""
    kind, _, number = label.partition(" ")
    if kind == "Output" and "-" in number:
        return (int(number.split("-")[0]) - 1) // 2
    if kind == "Bus" and number.isdigit():
        return int(number) - 1 + inputs // 2
    raise ValueError(f"{label!r} is not an output pair or a bus")


def _input_by_word(c: Channel, inputs: int) -> tuple[bool, str | None]:
    """(readable, label): an aux source past the buses is another kind, and is not read."""
    word = c.words[1]
    if word == NO_ROUTE or not c.label.startswith(("Audio ", "Aux ")):
        return True, None
    base = inputs // 2 if c.stereo_input else inputs
    if c.label.startswith("Aux ") and word >= base:
        return (True, f"Bus {word - base + 1}") if word - base < BUSES else (False, None)
    return True, f"Input {word + 1}-{word + 2}" if c.stereo_input else f"Input {word + 1}"


def _labels(data: bytes, field: int) -> dict[int, str | None]:
    """owner -> the label its output (``field`` 1) or input (2) names: by the uuid where the
    record's class carries one, else by the index word on a format measured routing by it."""
    chans = channels(data)
    by_uuid = {c.uuid: c.label for c in chans.values() if c.uuid != _ZERO}
    inputs = device_inputs(data) if file_format(data) in WORD_ROUTED else None
    out: dict[int, str | None] = {}
    for owner, c in chans.items():
        if trailer(c.ver)[field] is not None:
            out[owner] = by_uuid.get((c.dest_uuid, c.input_uuid)[field - 1])
        elif inputs and c.ver in TRAILER:
            readable, label = ((True, _output_by_word(c, inputs)) if field == 1
                               else _input_by_word(c, inputs))
            if readable:
                out[owner] = label
    return out


def output_labels(data: bytes) -> dict[int, str | None]:
    """owner -> the label of the channel it outputs to, ``None`` for none. An owner whose output
    cannot be read is left out: not decoded is not unrouted."""
    return _labels(data, 1)


def input_labels(data: bytes) -> dict[int, str | None]:
    """owner -> the label of the `Input N` or `Bus N` that feeds it, ``None`` for none. An owner
    whose input cannot be read is left out."""
    return _labels(data, 2)


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

