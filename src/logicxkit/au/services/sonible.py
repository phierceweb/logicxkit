"""sonible ``jucePluginState`` — a protobuf message with no published schema.

A schema-less wire-format walk exposes the field VALUES (message 3 is the
parameter block on smart:gate) without names; the huge trailing field is the
learned/NN state and is summarized, not walked. Naming the fields needs a
calibration pass against the UI (change one knob, re-save, diff) — until
then the output is honest raw fields, keyed by protobuf field number.
"""

from __future__ import annotations

import struct

_MAX_FIELDS = 64
_MAX_INLINE = 4096  # length-delimited payloads beyond this are summarized
_MAX_DEPTH = 3


class _WalkError(ValueError):
    pass


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    v, shift = 0, 0
    while True:
        if pos >= len(buf) or shift > 63:
            raise _WalkError("truncated varint")
        b = buf[pos]
        pos += 1
        v |= (b & 0x7F) << shift
        if not b & 0x80:
            return v, pos
        shift += 7


def _store(fields: dict, key: str, value) -> None:
    if key in fields:  # repeated field -> list
        prev = fields[key]
        fields[key] = prev + [value] if isinstance(prev, list) else [prev, value]
    else:
        fields[key] = value


def _walk(buf: bytes, depth: int) -> dict:
    fields: dict = {}
    pos, count = 0, 0
    while pos < len(buf) and count < _MAX_FIELDS:
        tag, pos = _read_varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0:
            raise _WalkError("field 0 is invalid")
        key = str(field)
        if wire == 0:
            v, pos = _read_varint(buf, pos)
            _store(fields, key, v)
        elif wire == 5:
            if pos + 4 > len(buf):
                raise _WalkError("truncated fixed32")
            _store(fields, key, round(struct.unpack_from("<f", buf, pos)[0], 6))
            pos += 4
        elif wire == 1:
            if pos + 8 > len(buf):
                raise _WalkError("truncated fixed64")
            _store(fields, key, struct.unpack_from("<d", buf, pos)[0])
            pos += 8
        elif wire == 2:
            ln, pos = _read_varint(buf, pos)
            if pos + ln > len(buf):
                raise _WalkError("truncated payload")
            payload = buf[pos:pos + ln]
            pos += ln
            if ln and payload[:1].isalpha() and all(32 <= b < 127 for b in payload):
                _store(fields, key, payload.decode("ascii"))
            elif ln <= _MAX_INLINE and depth < _MAX_DEPTH:
                try:
                    _store(fields, key, _walk(payload, depth + 1))
                except _WalkError:
                    _store(fields, key, f"bytes[{ln}]")
            else:
                _store(fields, key, f"bytes[{ln}]")
        else:
            raise _WalkError(f"unsupported wire type {wire}")
        count += 1
    return fields


def decode_sonible(state: bytes) -> dict | None:
    try:
        fields = _walk(state, 0)
    except _WalkError:
        return None
    if not fields:
        return None
    name = fields.get("1")
    return {"format": "protobuf", "plugin": name if isinstance(name, str) else None,
            "fields": fields}
