"""Writing values into an embedded AU state without moving a byte: the ``data`` pairs or a
vendor blob re-encoded into the same base64 span of the record's XML plist, so the record and
every length field around it stay as Logic wrote them."""

from __future__ import annotations

import base64
import struct

from logicxkit.au.services.ffp import parse_ffp

_WS = b" \t\r\n"


def patch_pairs(blob: bytes, values: dict[int, float]) -> bytes:
    """The ``data`` pairs blob with each id's float replaced; an id the blob lacks is refused."""
    count = struct.unpack_from(">I", blob, 8)[0]
    out = bytearray(blob)
    seen = set()
    for i in range(count):
        pid = struct.unpack_from(">I", out, 12 + 8 * i)[0]
        if pid in values:
            struct.pack_into(">f", out, 16 + 8 * i, values[pid])
            seen.add(pid)
    missing = sorted(set(values) - seen)
    if missing:
        raise ValueError(f"the state holds no parameter id {', '.join(map(str, missing))}")
    return bytes(out)


def patch_ffbs(blob: bytes, values: dict[int, float]) -> bytes:
    """A FabFilter binary state (the .ffp layout) with values replaced by id."""
    preset = parse_ffp(blob)
    out = bytearray(blob)
    for pid, value in values.items():
        if not 0 <= pid < len(preset.values):
            raise ValueError(f"the state holds {len(preset.values)} values, no id {pid}")
        struct.pack_into("<f", out, 12 + 4 * pid, value)
    return bytes(out)


def replace_data(payload: bytes, key: str, blob: bytes) -> bytes:
    """``payload`` with the ``<data>`` of plist key ``key`` re-encoded from ``blob``, which must
    be the old blob's length: the base64 characters change in place, the whitespace stays."""
    tag = f"<key>{key}</key>".encode()
    k = payload.find(tag)
    if k < 0:
        raise ValueError(f"the state has no {key!r}")
    a = payload.index(b"<data>", k) + len(b"<data>")
    b = payload.index(b"</data>", a)
    old = payload[a:b]
    new = base64.b64encode(blob)
    if len(new) != sum(1 for c in old if c not in _WS):
        raise ValueError(f"{key}: a {len(blob)}-byte blob does not fit the state's span")
    it = iter(new)
    body = bytes(c if c in _WS else next(it) for c in old)
    return payload[:a] + body + payload[b:]
