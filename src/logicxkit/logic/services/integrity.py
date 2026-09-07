"""Structural invariants over a whole project, checked at the write boundary.

`validate.py` is the record-level gate: the walk, the header total, plugin slot keys and
widths. It has no view of the structures a row-adding writer touches — sequence links, the
bound-object index, send flags — so `apply-template` raised link errors 0 -> 5 on a real
session and nothing noticed.

Logic's own files carry a few pre-existing link errors, so nothing here demands zero. The unit
is the **regression**: a writer's output is held against the input it was given.
"""

from __future__ import annotations

import struct

from .binding import bound_channels
from .channel_alloc import is_mixer_record
from .environment import channel_objects, name_end, object_record
from .insert import HEADER, project_records
from .sends import SEND_FLAG_AT, SEND_TAG
from .sequence import link_errors
from .validate import validate_project
from .groups import group_errors
from .keyflags import flag_errors
from .regions import region_errors, row_count_errors
from .registry import slot_errors


def _bad_object_index(records, data: bytes) -> list[int]:
    """Objects whose stored mixer index disagrees with the channel they are bound to."""
    owners, out = bound_channels(data), []
    for oid in channel_objects(data):
        if oid not in owners:
            continue
        payload = object_record(records, oid)[HEADER:]
        if struct.unpack_from("<H", payload, name_end(payload))[0] != owners[oid] + 1:
            out.append(oid)
    return out


def _bad_send_flags(records, data: bytes) -> list[int]:
    """Channels whose three send flags disagree with the records under keys 0-2 they own —
    sends, or the plugin slots an old project keeps there."""
    satellites: dict[int, set[int]] = {}
    for record in records:
        if record.tag == SEND_TAG:
            satellites.setdefault(record.owner, set()).add(record.key)
    out = []
    for record in records:
        if not is_mixer_record(record) or len(record.raw) - HEADER <= SEND_FLAG_AT + 12:
            continue
        keys = satellites.get(record.owner, set())
        flags = [struct.unpack_from("<I", record.raw, HEADER + SEND_FLAG_AT + 4 * k)[0] == 1
                 for k in range(3)]
        if any(flags[k] != (k in keys) for k in range(3)):
            out.append(record.owner)
    return out


def structural_report(data: bytes) -> dict:
    """Every invariant this module knows, as counts and id lists. Never raises on a project it
    can walk; a project it cannot walk reports the failure under ``unreadable``."""
    try:
        records = project_records(data)
        return {
            "validate": validate_project(data),
            "link_errors": len(link_errors(records)),
            "bad_object_index": _bad_object_index(records, data),
            "bad_send_flags": _bad_send_flags(records, data),
            "bad_key_flags": flag_errors(data),
            "bad_region_tracks": region_errors(data),
            "bad_row_count": row_count_errors(data),
            "bad_slot_entries": slot_errors(data),
            "bad_groups": group_errors(data),
            "unreadable": None,
        }
    except Exception as e:                      # a writer can leave bytes nothing can parse
        return {"validate": [], "link_errors": 0, "bad_object_index": [], "bad_send_flags": [],
                "bad_key_flags": [], "bad_region_tracks": [], "bad_row_count": [], "bad_slot_entries": [],
                "bad_groups": [], "unreadable": f"{type(e).__name__}: {e}"}


def regressions(before: bytes, after: bytes) -> list[str]:
    """What ``after`` broke that ``before`` had right. Empty means the write is safe to keep."""
    was, now = structural_report(before), structural_report(after)
    if now["unreadable"]:
        return [f"the result cannot be read back — {now['unreadable']}"]

    out = [f"new record-level problem: {p}" for p in now["validate"] if p not in was["validate"]]
    if now["link_errors"] > was["link_errors"]:
        out.append(f"sequence link errors {was['link_errors']} -> {now['link_errors']}")
    for field, label in (("bad_object_index", "object(s) whose mixer index no longer matches "
                          "their channel"),
                         ("bad_send_flags", "channel(s) whose send flags no longer match their "
                          "send records"),
                         ("bad_key_flags", "channel(s) whose key flags no longer match their "
                          "records — Logic refuses such a file"),
                         ("bad_region_tracks", "region placement(s) whose track number no longer "
                          "matches the row — the region shows on the wrong track"),
                         ("bad_slot_entries", "track(s) whose sequence slot has no registry entry"),
                         ("bad_groups", "group problem(s) — a member numbered for a group that is "
                          "not there, events that do not match the members, a slot without its "
                          "registry pair"),
                         ("bad_row_count", "song container row count off — Logic reads that many "
                          "rows and drops the rest")):
        fresh = sorted(set(now[field]) - set(was[field]))
        if fresh:
            out.append(f"{len(fresh)} {label}: {fresh}")
    return out


def require_no_regression(before: bytes, after: bytes) -> None:
    """Raise rather than let a writer's output reach disk in a worse state than its input."""
    found = regressions(before, after)
    if found:
        raise ValueError("refusing to write — the edit broke structure the input had right:\n  "
                         + "\n  ".join(found))
