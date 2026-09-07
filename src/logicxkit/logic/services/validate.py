"""Structural invariants for a written project.

The violations a writer can produce and nothing else catches:

* two slots claiming the same index — Logic renders one and silently drops the other
* a mono plugin instance on a stereo channel — audibly wrong on a bus
* a corrupted record — the project refuses to open

`validate_project` runs on the bytes about to be written and returns every problem rather than
the first, because one root cause usually shows up on many channels at once.

**It only sees native slots.** The scan below skips any record without a `GAMETSPP` chunk, so a
third-party slot — the kind `transplant` exists to move — is invisible to it. A clean result is
not a statement about those.
"""

from __future__ import annotations

import struct
from contextlib import contextmanager
from contextvars import ContextVar

from .._binary import find_blocks
from .insert import (
    BODY_START,
    CHANNEL_FMT_AT,
    CHANNEL_TAG,
    HEADER,
    NO_KEY,
    SLOT_INDEX_AT,
    TOTAL_AT,
    channel_formats,
    project_records,
    slot_format,
    slot_index_base,
)


def validate_project(data: bytes) -> list[str]:
    """Everything structurally wrong with ``data``; empty means it is safe to write."""
    problems: list[str] = []

    records = project_records(data)
    consumed = BODY_START + sum(len(r.raw) for r in records)
    if consumed != len(data):
        problems.append(f"record walk stopped at {consumed} of {len(data)} bytes")

    if len(data) > TOTAL_AT + 4:
        declared = struct.unpack_from("<I", data, TOTAL_AT)[0]
        if declared != len(data) - BODY_START:
            problems.append(
                f"file header total is {declared}, expected {len(data) - BODY_START}")

    formats = channel_formats(data)
    base = slot_index_base(data)
    slots: dict[int, list] = {}
    for record in records:
        if record.tag != b"UCuA" or b"GAMETSPP" not in record.raw:
            continue
        if find_blocks(record.raw[HEADER:]):
            slots.setdefault(record.owner, []).append(record)

    for owner, found in sorted(slots.items()):
        keys = [r.key for r in found]
        if len(set(keys)) != len(keys):
            problems.append(f"channel {owner}: duplicate slot key(s) {sorted(keys)}")

        indices = [r.raw[HEADER + SLOT_INDEX_AT] for r in found]
        if len(set(indices)) != len(indices):
            problems.append(
                f"channel {owner}: colliding slot index {sorted(indices)} — Logic will hide a plugin")
        for record, index in zip(found, indices, strict=True):
            if index != record.key - base:
                problems.append(
                    f"channel {owner} key {record.key}: slot index {index}, expected "
                    f"{record.key - base} for this project's numbering")

        want = formats.get(owner)
        for record in found:
            got = slot_format(record.raw)
            if want and got and got != want:
                problems.append(
                    f"channel {owner} key {record.key}: plugin width {got} on a "
                    f"{'stereo' if want == 2 else 'mono'} channel")

    for record in records:
        if record.tag == CHANNEL_TAG and record.key == NO_KEY:
            payload = record.raw[HEADER:]
            if len(payload) > CHANNEL_FMT_AT and payload[CHANNEL_FMT_AT] not in (0, 1, 2, 5):
                problems.append(
                    f"channel {record.owner}: implausible width byte {payload[CHANNEL_FMT_AT]}")
    return problems


def require_full_walk(data: bytes) -> None:
    """Refuse an input the record walk cannot consume whole — a writer would drop the tail."""
    consumed = BODY_START + sum(len(r.raw) for r in project_records(data))
    if consumed != len(data):
        raise ValueError(f"record walk stopped at {consumed} of {len(data)} bytes; "
                         "refusing to rewrite a stream that is not fully understood")


_TOLERATED: ContextVar[frozenset] = ContextVar("tolerated_problems", default=frozenset())


@contextmanager
def tolerating(data: bytes):
    """Inside, `require_valid` ignores the problems ``data`` already has — a writer answers
    for what it changes, not for a stereo plugin some old session parked on a mono channel.
    The command boundary still refuses any regression (`integrity.require_no_regression`)."""
    token = _TOLERATED.set(_TOLERATED.get() | frozenset(validate_project(data)))
    try:
        yield
    finally:
        _TOLERATED.reset(token)


def require_valid(data: bytes) -> None:
    """Raise on the first write-blocking problem set, listing every one (less any a
    `tolerating` block says the input had already)."""
    problems = [p for p in validate_project(data) if p not in _TOLERATED.get()]
    if problems:
        raise ValueError("refusing to write an invalid project:\n  " + "\n  ".join(problems))
