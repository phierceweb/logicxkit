"""The channel record's key flags: from `+132`, one u32 per satellite key (sends at keys
0-2, plugin slots from 4, the reference and the rest after), 1 when a `UCuA` record with
that key exists under the owner, 0 otherwise — 78,666 words on nineteen Logic files, no
exception. `+26` is the flag-word count and sizes the record: 201 + 4 x words on all
21,772 version-7 channel records on hand (169 + 4 x words on the version-6 records old
backups carry; older versions are left alone); the 20 zero bytes, one byte and three
UUIDs after the flags never move. A set flag without its record, or a record shorter than its
`+26` says, is a file Logic refuses to open; a record without its flag it tolerates. Every
writer that adds or drops a satellite ends by syncing them.
"""

from __future__ import annotations

import struct

from .insert import CHANNEL_TAG, HEADER, NO_KEY, project_records, reassemble

FLAGS_AT = 132
KEY_COUNT_AT = 26                 # u16: flag words, never lowered here
TAIL = 20 + 1 + 48
BASE_SIZE = FLAGS_AT + TAIL       # the 201-byte stub: no flag words (record version 7)
BASE_BY_VERSION = {7: BASE_SIZE, 6: 169}   # v6 (backups only): same flags, a 37-byte tail
_MIXER_MIN = 160


def flag_words(payload: bytes) -> int:
    return struct.unpack_from("<H", payload, KEY_COUNT_AT)[0]


def well_sized(payload: bytes, version: int = 7) -> bool:
    base = BASE_BY_VERSION.get(version)
    return base is not None and len(payload) == base + 4 * flag_words(payload)


def _version(raw: bytes) -> int:
    return struct.unpack_from("<H", raw, 4)[0]


def key_flags(payload: bytes) -> list[bool]:
    return [struct.unpack_from("<I", payload, FLAGS_AT + 4 * k)[0] == 1 for k in range(flag_words(payload))]


def with_key_flags(raw: bytes, keys: set[int]) -> bytes:
    """The channel record with exactly ``keys`` flagged. A record too short for a key grows
    by whole flag words in front of the tail, `+26` moved with it."""
    p = bytearray(raw[HEADER:])
    if not well_sized(p, _version(raw)):
        raise ValueError(f"channel record is {len(p)} bytes for {flag_words(p)} flag words")
    n = flag_words(p)
    need = max(keys) + 1 if keys else 0
    if need > n:
        at = FLAGS_AT + 4 * n
        p[at:at] = bytes(4 * (need - n))
        n = need
        struct.pack_into("<H", p, KEY_COUNT_AT, n)
    for k in range(n):
        struct.pack_into("<I", p, FLAGS_AT + 4 * k, 1 if k in keys else 0)
    out = bytearray(raw[:HEADER]) + p
    struct.pack_into("<I", out, 28, len(p))
    return bytes(out)


def _satellite_keys(records) -> dict[int, set[int]]:
    keys: dict[int, set[int]] = {}
    for r in records:
        if r.tag == b"UCuA":
            keys.setdefault(r.owner, set()).add(r.key)
    return keys


def _is_channel(r) -> bool:
    """A mixer channel record of a version whose layout is known."""
    return (r.tag == CHANNEL_TAG and r.key == NO_KEY and len(r.raw) - HEADER > _MIXER_MIN
            and _version(r.raw) in BASE_BY_VERSION)


def sync_key_flags(data: bytes) -> bytes:
    """Every mixer channel's flags recomputed from the records its owner carries; a record
    whose size disagrees with its `+26` is left alone (`flag_errors` reports it)."""
    records = project_records(data)
    keys = _satellite_keys(records)
    out = []
    for r in records:
        raw = r.raw
        if _is_channel(r) and well_sized(raw[HEADER:], _version(raw)):
            raw = with_key_flags(raw, keys.get(r.owner, set()))
        out.append(raw)
    return reassemble(data, out)


def flag_errors(data: bytes) -> list[str]:
    """Channels whose flags disagree with their records, or whose size disagrees with `+26`."""
    records = project_records(data)
    keys = _satellite_keys(records)
    out = []
    for r in records:
        if not _is_channel(r):
            continue
        p = r.raw[HEADER:]
        if not well_sized(p, _version(r.raw)):
            out.append(f"owner {r.owner}: {len(p)} bytes for {flag_words(p)} flag words")
            continue
        have = {k for k, f in enumerate(key_flags(p)) if f}
        want = {k for k in keys.get(r.owner, set()) if k < flag_words(p)}
        if have != want:
            out.append(f"owner {r.owner}: flags {sorted(have)} but records {sorted(want)}")
    return out
