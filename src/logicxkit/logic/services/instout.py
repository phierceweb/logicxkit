"""An aux fed by a software instrument's extra output — how the Drums MIDI auxes take the
drum instrument's hi-hat, overhead and room outputs. Measured on two Logic 12.3.1 saves
(2026-09-05) against nine projects of the template's lineage.

The aux's channel record: `+95` = 1 and `+94` = a source id Logic hands out in order, the
first being the project's mono input count (20 inputs -> 20, 21, 22 as auxes were bound);
its input UUID stays zero. Under the aux, one 68-byte `UCuA` at the key just below the
channel's 192-byte state record:

    +0    u32   72 (the class word sends carry too)     +36   the output's name, NUL-padded
    +15   u8    the output's index in the plugin's list      to 16 bytes ("Addictive 13-14")
    +22   u16   the instrument's number - 1 (Inst 9 -> 8)   +52   a fresh v1 UUID
    +24   4CC x3  manufacturer, type, subtype, each reversed ("xlnA" "aumu" "xAD2")

The instrument's own records do not change. A stereo output made Logic widen the aux
(`+78`, `+123`); a mono one did not — the width writer owns that, not this one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .binding import channels
from .channel_alloc import is_mixer_record
from .insert import HEADER, project_records, reassemble
from .keyflags import sync_key_flags
from .recbuild import fresh_uuid, rec
from .validate import require_full_walk, require_valid

CLASS_WORD = 72
SIZE = 68
INDEX_AT, INST_AT, PLUGIN_AT, NAME_AT, UUID_AT = 15, 22, 24, 36, 52
NAME_LEN = 16
SOURCE_ID_AT, SOURCE_KIND_AT = 94, 95
INSTRUMENT_SOURCE = 1
NO_SOURCE = b"\xff\xff"        # +94/+95 on an aux set to No Input (measured 2026-09-05);
                                # 0/0 reads back as Input 1-2, the live input pair
STATE_RECORD_SIZE = 192
_DEFAULT_KEY = 12               # what Logic 12.3.1 writes; a binding at 11 was dropped on load


@dataclass(frozen=True)
class InstrumentOutput:
    aux_owner: int
    key: int
    index: int
    instrument: int             # the Inst number as the mixer shows it
    plugin: str                 # "xlnA/aumu/xAD2"
    name: str
    source_id: int
    raw: bytes                  # the 68-byte payload, for cloning


def _is_binding(record) -> bool:
    return (record.tag == b"UCuA" and len(record.raw) - HEADER == SIZE
            and struct.unpack_from("<I", record.raw, HEADER)[0] == CLASS_WORD)


def _fourcc(payload: bytes, at: int) -> str:
    return payload[at:at + 4][::-1].decode("latin-1")


def _mixer_payloads(records) -> dict[int, bytes]:
    """owner -> its longest mixer channel payload."""
    out: dict[int, bytes] = {}
    for r in records:
        if is_mixer_record(r) and len(r.raw) - HEADER > len(out.get(r.owner, b"")):
            out[r.owner] = r.raw[HEADER:]
    return out


def read_instrument_outputs(data: bytes) -> dict[int, InstrumentOutput]:
    """aux owner -> the instrument output feeding it."""
    records = project_records(data)
    payloads = _mixer_payloads(records)
    out = {}
    for r in records:
        if not _is_binding(r):
            continue
        p = r.raw[HEADER:]
        c = payloads.get(r.owner, b"")
        source = c[SOURCE_ID_AT] if len(c) > SOURCE_KIND_AT else 0
        out[r.owner] = InstrumentOutput(
            aux_owner=r.owner, key=r.key, index=p[INDEX_AT],
            instrument=struct.unpack_from("<H", p, INST_AT)[0] + 1,
            plugin="/".join(_fourcc(p, PLUGIN_AT + 4 * k) for k in range(3)),
            name=p[NAME_AT:NAME_AT + NAME_LEN].split(b"\0")[0].decode("latin-1"),
            source_id=source, raw=bytes(p))
    return out


def binding_key(data: bytes) -> int:
    """The key just below the channels' 192-byte state record, never below 12: Logic's own
    files hold it there, and a binding written at 11 (a project whose state records sit at
    12) did not survive Logic's load."""
    keys = [r.key for r in project_records(data) if r.tag == b"UCuA" and len(r.raw) - HEADER == STATE_RECORD_SIZE]
    return max(_DEFAULT_KEY, min(keys) - 1) if keys else _DEFAULT_KEY


def next_source_id(data: bytes) -> int:
    """What Logic would hand the next instrument-fed aux: past every id in use, and never
    below the mono input count."""
    chans = channels(data)
    payloads = _mixer_payloads(project_records(data))
    used = [p[SOURCE_ID_AT] for p in payloads.values()
            if len(p) > SOURCE_KIND_AT and p[SOURCE_KIND_AT] == INSTRUMENT_SOURCE]
    inputs = sum(1 for c in chans.values() if c.label.startswith("Input ") and "-" not in c.label)
    return max([inputs - 1] + used) + 1


def bind_instrument_output(data: bytes, aux_owner: int, *, pattern: bytes, instrument: int) -> bytes:
    """Feed ``aux_owner`` from the output ``pattern`` (a 68-byte payload from a project that
    has the binding) of instrument ``instrument`` (the Inst number); replaces a binding the
    aux already has."""
    if len(pattern) != SIZE or struct.unpack_from("<I", pattern, 0)[0] != CLASS_WORD:
        raise ValueError("the pattern is not an instrument-output record")
    require_full_walk(data)
    chans = channels(data)
    if aux_owner not in chans:
        raise ValueError(f"no channel {aux_owner}")
    if not any(c.label == f"Inst {instrument}" for c in chans.values()):
        raise ValueError(f"the session has no Inst {instrument}")
    key = binding_key(data)
    body = bytearray(pattern)
    struct.pack_into("<H", body, INST_AT, instrument - 1)
    body[UUID_AT:UUID_AT + 16] = fresh_uuid()
    records = project_records(data)
    template = next(r.raw for r in records if r.tag == b"UCuA")
    new = rec(b"UCuA", template, bytes(body), owner=aux_owner, key=key)
    source_id = next_source_id(data)
    out, placed = [], False
    kept = [r for r in records if not (_is_binding(r) and r.owner == aux_owner)]
    last_before = max((i for i, r in enumerate(kept)
                       if r.owner == aux_owner and (r.tag == b"OCuA" or (r.tag == b"UCuA" and r.key < key))), default=None)
    if last_before is None:
        raise ValueError(f"no channel record for owner {aux_owner}")
    for i, r in enumerate(kept):
        raw = r.raw
        if r.tag == b"OCuA" and r.owner == aux_owner and r.key == 0xFFFF and len(raw) - HEADER > SOURCE_KIND_AT:
            buf = bytearray(raw)
            buf[HEADER + SOURCE_ID_AT] = source_id
            buf[HEADER + SOURCE_KIND_AT] = INSTRUMENT_SOURCE
            raw = bytes(buf)
        out.append(raw)
        if i == last_before:
            out.append(new)
            placed = True
    if not placed:
        raise ValueError(f"no place for the binding under owner {aux_owner}")
    result = sync_key_flags(reassemble(data, out))
    require_valid(result)
    return result


def unbind_instrument_output(data: bytes, aux_owner: int) -> bytes:
    """Take the source away from ``aux_owner``: an instrument-output record out, and the
    source id and kind at `+94`/`+95` set to No Input — a bus-fed aux carries an id there
    too, and Logic restores the bus from it when only the tail UUID is zeroed. The No Input
    bytes are Logic's; taking the record out is composed."""
    require_full_walk(data)
    records = project_records(data)
    out, changed = [], False
    for r in records:
        if _is_binding(r) and r.owner == aux_owner:
            changed = True
            continue
        raw = r.raw
        if r.tag == b"OCuA" and r.owner == aux_owner and r.key == 0xFFFF and len(raw) - HEADER > SOURCE_KIND_AT:
            if raw[HEADER + SOURCE_ID_AT:HEADER + SOURCE_KIND_AT + 1] != NO_SOURCE:
                buf = bytearray(raw)
                buf[HEADER + SOURCE_ID_AT:HEADER + SOURCE_KIND_AT + 1] = NO_SOURCE
                raw = bytes(buf)
                changed = True
        out.append(raw)
    if not changed:
        return data
    result = sync_key_flags(reassemble(data, out))
    require_valid(result)
    return result
