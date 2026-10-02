"""Structural invariants for a written project.

The violations a writer can produce and nothing else catches:

* two slots claiming the same index — Logic renders one and silently drops the other
* a mono plugin instance on a stereo channel — audibly wrong on a bus
* a corrupted record — the project refuses to open
* channel records out of owner order — Logic can drop every plug-in on load
* a plug-in or keyed-archive record at a key its payload disagrees with — Logic can refuse to
  open the project, depending on the record's fresh ids

`validate_project` runs on the bytes about to be written and returns every problem rather than
the first, because one root cause usually shows up on many channels at once.

A slot is a native record carrying a `GAMETSPP` chunk, or any record in the slot key range
carrying its own index at +6 (`slots.is_plugin_slot`) — so third-party states are checked for
duplicate keys and index collisions too. Their width bytes are not judged: Logic's own saves
carry third-party records whose +84/+118/+119 disagree with the channel (29 across the golden
corpus), so the width check stays native-only. A plug-in record whose index disagrees with its
key is no slot to those checks; the key check reports it.
"""

from __future__ import annotations

import struct
from contextlib import contextmanager
from contextvars import ContextVar

from .._binary import find_blocks
from .mixer import CHANNEL_FMT_AT, CHANNEL_TAG, channel_formats, is_mixer_record
from .slot_width import slot_format
from .slots import SLOT_INDEX_AT, _PLUGIN_MARKS, slot_index_base
from .stream import BODY_START, HEADER, NO_KEY, TOTAL_AT, project_records
from .slot_width import one_build
from .slots import archive_index, is_plugin_slot, property_key_base


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
    prop = property_key_base(data)
    slots: dict[int, list] = {}
    for record in records:
        if record.tag != b"UCuA":
            continue
        native = b"GAMETSPP" in record.raw and bool(find_blocks(record.raw[HEADER:]))
        if native or is_plugin_slot(record, prop, base):
            slots.setdefault(record.owner, []).append(record)

    for owner, found in sorted(slots.items()):
        keys = [r.key for r in found]
        if len(set(keys)) != len(keys):
            problems.append(f"channel {owner}: duplicate slot key(s) {sorted(keys)}")

        indices = [r.raw[HEADER + SLOT_INDEX_AT] for r in found]
        if len(set(indices)) != len(indices):
            problems.append(
                f"channel {owner}: colliding slot index {sorted(indices)} — Logic will hide a plugin")

        # past a one-build plug-in the chain is stereo, and Logic stores the chain's output width
        want = None if any(one_build(r.raw) for r in found) else formats.get(owner)
        for record in found:
            got = slot_format(record.raw) if b"GAMETSPP" in record.raw else None
            if want and got and got != want:
                problems.append(
                    f"channel {owner} key {record.key}: plugin width {got} on a "
                    f"{'stereo' if want == 2 else 'mono'} channel")

    for record in records:
        if record.tag != b"UCuA":
            continue
        archive, payload = archive_index(record.raw), record.raw[HEADER:]
        if archive is not None and record.key != prop + 1 + archive:
            problems.append(f"channel {record.owner} key {record.key}: keyed archive {archive}, "
                            f"expected at key {prop + 1 + archive}")
        elif archive is None and record.key < prop and len(payload) > SLOT_INDEX_AT \
                and any(m in record.raw for m in _PLUGIN_MARKS) and payload[SLOT_INDEX_AT] != record.key - base:
            problems.append(f"channel {record.owner} key {record.key}: slot index {payload[SLOT_INDEX_AT]}, "
                            f"expected {record.key - base} for this project's numbering")

    owners = [r.owner for r in records if is_mixer_record(r)]
    if any(b < a for a, b in zip(owners, owners[1:], strict=False)):
        problems.append("channel records out of owner order — Logic can drop every plug-in on load")

    for record in records:
        if record.tag == CHANNEL_TAG and record.key == NO_KEY:
            payload = record.raw[HEADER:]
            if len(payload) > CHANNEL_FMT_AT and payload[CHANNEL_FMT_AT] not in (0, 1, 2, 5):
                problems.append(
                    f"channel {record.owner}: implausible width byte {payload[CHANNEL_FMT_AT]}")
    return problems


SIGNATURE = bytes.fromhex("2347c0ab")
FORMAT_AT = 4
MEASURED_FORMAT = 2513                  # Logic 12.3.1's and 12.4's; the format of every golden


def file_format(data: bytes) -> int | None:
    """The file header's format word, or None when ``data`` is no Logic project file."""
    if len(data) < FORMAT_AT + 2 or data[:len(SIGNATURE)] != SIGNATURE:
        return None
    return struct.unpack_from("<H", data, FORMAT_AT)[0]


def require_measured_format(data: bytes) -> None:
    """Refuse a project of a format no writer is measured on: record classes move between
    Logic builds, and a field written where another build keeps something else is damage
    no later check sees."""
    found = file_format(data)
    if found is None:
        raise ValueError("not a Logic project file")
    if found < MEASURED_FORMAT:
        raise ValueError(f"saved by an earlier Logic (file format {found}; the writers are "
                         f"measured on {MEASURED_FORMAT}, Logic 12.3.1's) — open and save it "
                         "in the current Logic first")
    if found > MEASURED_FORMAT:
        raise ValueError(f"saved by a Logic newer than this release (file format {found}; the "
                         f"writers are measured on {MEASURED_FORMAT}, Logic 12.3.1's) — "
                         "nothing is written")


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
