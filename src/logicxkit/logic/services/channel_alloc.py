"""A new track's mixer channel.

An audio track binds one of the pre-allocated `Audio N` stubs every project carries; with
none free Logic makes a fresh 201-byte channel at the first bare stub's place (after the
last `Audio` when there is none), numbers it by position, renumbers the `Audio` strips behind
it and moves every later owner up (measured 2026-09-06 on three adds; the record is
`data/audio-channel-12.3.1.json`). An `Input N` past the count is the same insert after the
last mono input, from a copy of one (six made on a 20-input legacy song survived Logic's
re-save byte for byte, 2026-09-06). An instrument track has
no stub: a channel record is inserted after the pattern channel with
Logic's default instrument-slot records, every later channel's owner moves up by one, later
`Inst` strips are relabelled and the channel count record gains one. An aux track is the
same insert after the last `Aux` strip, with Logic's 201-byte default aux record (measured
2026-09-04: `data/aux-track-12.3.1.json`), fed by `Input 1-2` and sent to `Output 1-2`.

The channel-count record `nCuA` is a 132-byte head over one u32 per channel record: +26 the
total, then a u16 per strip class — +28 Audio, +32 Aux, +34 Inst (measured: an instrument add
moved +26 and +34 by one and appended ``01000000``), +38 Bus, +40 Master and Sub together
(counted from the file; unmeasured by a save).

Channel payload fields written here:

    +6              channel number: 0-based on Audio, Inst and Aux, 1-based on Sub
    +24, +25        in-use flags
    +60             label, 16 bytes (its digit at +66 is the only other copy of the number)
    +128            the number again on Inst strips, 0 elsewhere
    +78/+86/+123    width: mono 211/0/1, stereo 215/1/2; a fresh instrument 243/0/1
    len-48..-32     own UUID = the bound object's
    len-32..-16     output destination channel's UUID
    len-16..        input channel's UUID
"""

from __future__ import annotations

import json
import struct

from .binding import Channel, channel_label
from .insert import CHANNEL_TAG, HEADER, NO_KEY, ProjRecord
from .recbuild import fresh_uuid, rec, with_owner
from .sends import SEND_TAG

COUNT_TAG = b"nCuA"
COUNT_TOTAL_AT = 26
COUNT_CLASS_AT = {"Audio": 28, "Aux": 32, "Inst": 34, "Bus": 38, "Sub": 40}
COUNT_INPUT_AT = (30,)            # mono inputs; +36 is the device's input count and stays (Logic reset it, 2026-09-06)
STACK_INDEX_AT = 110
COUNT_HEAD = 132
IN_USE_AT = 24
LABEL_AT = 60
LABEL_LEN = 16
NUMBER_AT, INST_NUMBER2_AT = 6, 128
WIDTH = {78: {1: 211, 2: 215}, 86: {1: 0, 2: 1}, 123: {1: 1, 2: 2}}
INST_FRESH = {78: 243, 81: 0, 86: 0, 92: 0, 123: 1, 188: 0}
UUID_LEN = 16
_MIXER_MIN = 200
_DATA, _AUX_DATA, _AUDIO_DATA = "inst-track-12.3.1.json", "aux-track-12.3.1.json", "audio-channel-12.3.1.json"


def _spec(name: str) -> dict:
    """A record template Logic saved, from the untracked data root (`utils.data`)."""
    from ...utils.data import data_file
    return json.loads(data_file("logic", name).read_text())


def is_mixer_record(record: ProjRecord) -> bool:
    """The channel record proper, not a slot or a stub."""
    return (record.tag == CHANNEL_TAG and record.key == NO_KEY
            and len(record.raw) - HEADER > _MIXER_MIN)


def mixer_record(records: list[ProjRecord], owner: int) -> bytes:
    for r in records:
        if is_mixer_record(r) and r.owner == owner:
            return r.raw
    raise ValueError(f"no mixer channel record for owner {owner}")


SHAPED_STUB_MIN = 240             # a stub Logic pre-shaped for use (245 B here); the 201-byte
                                  # ones are bare and need growing first
BARE_STUB = 201                   # a fresh channel's size too: Logic inserts new ones before the bare stubs


def free_audio_stub(chans: dict[int, Channel]) -> int:
    """The lowest-numbered `Audio N` strip no track is using — the shaped stubs first, then
    the bare 201-byte ones, which is the order Logic itself takes them in (measured on four
    adds, 2026-09-04)."""
    free = [(o, c) for o, c in sorted(chans.items())
            if c.label.startswith("Audio ") and not c.in_use and c.size > _MIXER_MIN]
    shaped = [o for o, c in free if c.size >= SHAPED_STUB_MIN]
    if shaped:
        return shaped[0]
    if free:
        return free[0][0]
    raise ValueError("no free Audio channel stub to bind")


def bind_audio_stub(raw: bytes, *, object_uuid: bytes, input_uuid: bytes,
                    output_uuid: bytes | None, stereo: bool = False, stack_index: int = 0) -> bytes:
    """A stub brought into use: in-use flags, width, the three UUIDs and the stack it sits
    in. The output is only set when the stub has none."""
    p = bytearray(raw[HEADER:])
    p[IN_USE_AT] = p[IN_USE_AT + 1] = 1
    p[STACK_INDEX_AT] = stack_index
    width = 2 if stereo else 1
    for off, by_width in WIDTH.items():
        p[off] = by_width[width]
    n = len(p)
    p[n - 48:n - 32] = object_uuid
    if p[n - 32:n - 16] == bytes(UUID_LEN) and output_uuid is not None:
        p[n - 32:n - 16] = output_uuid
    p[n - 16:] = input_uuid
    return raw[:HEADER] + bytes(p)


def new_inst_channel(template: bytes, *, owner: int, object_uuid: bytes,
                     output_uuid: bytes | None, stack_index: int = 0) -> tuple[bytes, int]:
    """A fresh instrument channel numbered after ``template``'s -> ``(record, number)``."""
    p = bytearray(template[HEADER:])
    for off in (NUMBER_AT, INST_NUMBER2_AT):
        struct.pack_into("<H", p, off, struct.unpack_from("<H", p, off)[0] + 1)
    for off, value in INST_FRESH.items():
        p[off] = value
    p[STACK_INDEX_AT] = stack_index
    number = struct.unpack_from("<H", p, NUMBER_AT)[0] + 1
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Inst {number}".encode().ljust(LABEL_LEN, b"\x00")
    n = len(p)
    p[n - 48:n - 32] = object_uuid
    if output_uuid is not None:
        p[n - 32:n - 16] = output_uuid
    p[n - 16:] = bytes(UUID_LEN)
    return rec(CHANNEL_TAG, template, bytes(p), owner=owner), number


def new_sub_channel(template: bytes, *, number: int, owner: int, uuid: bytes) -> bytes:
    """A `Sub number` strip cloned from another Sub's record, bound to object ``uuid``."""
    p = bytearray(template[HEADER:])
    struct.pack_into("<H", p, NUMBER_AT, number)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Sub {number}".encode().ljust(LABEL_LEN, b"\x00")
    n = len(p)
    p[n - 48:n - 32] = uuid
    return rec(CHANNEL_TAG, template, bytes(p), owner=owner)


def new_aux_channel(*, number: int, owner: int, object_uuid: bytes, output_uuid: bytes | None,
                    input_uuid: bytes | None, stack_index: int = 0) -> bytes:
    """Logic's default aux record as `Aux number+1`, bound to ``object_uuid``."""
    spec = _spec(_AUX_DATA)
    p = bytearray(bytes.fromhex(spec["payload"]))
    struct.pack_into("<H", p, NUMBER_AT, number)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Aux {number + 1}".encode().ljust(LABEL_LEN, b"\x00")
    p[STACK_INDEX_AT] = stack_index
    n = len(p)
    p[n - 48:n - 32] = object_uuid
    p[n - 32:n - 16] = output_uuid if output_uuid is not None else bytes(UUID_LEN)
    p[n - 16:] = input_uuid if input_uuid is not None else bytes(UUID_LEN)
    return rec(CHANNEL_TAG, bytes.fromhex(spec["header"]) + bytes(p), bytes(p), owner=owner)


def new_audio_channel(*, number: int, owner: int, object_uuid: bytes, output_uuid: bytes | None,
                      input_uuid: bytes | None, stereo: bool = False, stack_index: int = 0) -> bytes:
    """Logic's fresh audio channel as `Audio number`, in use and bound to ``object_uuid``."""
    spec = _spec(_AUDIO_DATA)
    p = bytearray(bytes.fromhex(spec["payload"]))
    struct.pack_into("<H", p, NUMBER_AT, number - 1)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Audio {number}".encode().ljust(LABEL_LEN, b"\x00")
    p[IN_USE_AT] = p[IN_USE_AT + 1] = 1
    p[STACK_INDEX_AT] = stack_index
    width = 2 if stereo else 1
    for off, by_width in WIDTH.items():
        p[off] = by_width[width]
    n = len(p)
    p[n - 48:n - 32] = object_uuid
    p[n - 32:n - 16] = output_uuid if output_uuid is not None else bytes(UUID_LEN)
    p[n - 16:] = input_uuid if input_uuid is not None else bytes(UUID_LEN)
    return rec(CHANNEL_TAG, bytes.fromhex(spec["header"]) + bytes(p), bytes(p), owner=owner)


def new_input_channel(template: bytes, *, number: int, owner: int) -> bytes:
    """`Input number`, unused, cloned from another mono input's record with its own UUID."""
    p = bytearray(template[HEADER:])
    struct.pack_into("<H", p, NUMBER_AT, number - 1)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" Input {number}".encode().ljust(LABEL_LEN, b"\x00")
    p[IN_USE_AT] = p[IN_USE_AT + 1] = 0
    n = len(p)
    p[n - 48:n - 32] = fresh_uuid()
    p[n - 32:] = bytes(2 * UUID_LEN)
    return rec(CHANNEL_TAG, template, bytes(p), owner=owner)


def default_inst_records(owner: int) -> list[bytes]:
    """Logic's default instrument-slot records for a new instrument channel."""
    spec = _spec(_DATA)
    out = []
    for raw in (bytes.fromhex(h) for h in spec["records"].values()):
        buf = bytearray(with_owner(raw, owner))
        buf[-UUID_LEN:] = fresh_uuid()
        out.append(bytes(buf))
    return out


def is_channel_record(record: ProjRecord) -> bool:
    """Anything a channel owns: the channel, its slots, its sends."""
    return record.tag in (CHANNEL_TAG, SEND_TAG)


def shifted_channel(raw: bytes, record: ProjRecord, relabel_prefix: str = "Inst ") -> bytes:
    """``raw`` (``record``'s bytes, possibly already edited) moved up one owner; a strip of
    the inserted channel's own class (``relabel_prefix``) is renumbered to match, the rest
    keep their numbers — an aux inserted before the `Inst` block leaves `Inst 1` as it is."""
    raw = with_owner(raw, record.owner + 1)
    if not is_mixer_record(record):
        return raw
    p = bytearray(raw[HEADER:])
    if not channel_label(p).startswith(relabel_prefix):
        return raw
    number = struct.unpack_from("<H", p, NUMBER_AT)[0] + 1
    struct.pack_into("<H", p, NUMBER_AT, number)
    p[LABEL_AT:LABEL_AT + LABEL_LEN] = f" {relabel_prefix.strip()} {number + 1}".encode().ljust(LABEL_LEN, b"\x00")
    return raw[:HEADER] + bytes(p)


def is_channel_count(record: ProjRecord) -> bool:
    """The count record proper: its length is the head plus one word per counted channel."""
    p = record.raw[HEADER:]
    if record.tag != COUNT_TAG or len(p) < COUNT_HEAD:
        return False
    total = struct.unpack_from("<H", p, COUNT_TOTAL_AT)[0]
    return total > 0 and len(p) == COUNT_HEAD + 4 * total


def bump_channel_count(raw: bytes, *, class_at: int | tuple[int, ...]) -> bytes:
    """The channel-count record with one more channel of the class counted at ``class_at``."""
    p = bytearray(raw[HEADER:])
    ats = (class_at,) if isinstance(class_at, int) else tuple(class_at)
    for at in (COUNT_TOTAL_AT, *ats):
        struct.pack_into("<H", p, at, struct.unpack_from("<H", p, at)[0] + 1)
    return rec(COUNT_TAG, raw, bytes(p) + b"\x01\x00\x00\x00")
