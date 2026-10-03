"""Structural invariants over a whole project, checked at the write boundary.

`validate.py` is the record-level gate: the walk, the header total, plugin slot keys and
widths. It has no view of the structures a row-adding writer touches — sequence links, the
bound-object index, send flags — so `apply-template` raised link errors 0 -> 5 on a real
session and nothing noticed.

Logic's own files carry a few pre-existing link errors, so nothing here demands zero. The unit
is the **regression**: a writer's output is held against the input it was given.

The region checks, over the song container, are `integrity_regions.py`.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable

from ..mixer.binding import bound_channels, bound_objects, channels
from ..mixer.channel_alloc import is_mixer_record
from ..arrange.environment import channel_objects, name_end, object_record
from ..arrange.groups import group_errors
from ..mixer.mixer import CHANNEL_TAG
from .stream import HEADER, project_records
from .integrity_regions import (
    RegionKey, dangling_files, marker_block_errors, placed, region_regressions, unregistered_slots,
)
from .keyflags import flag_errors
from ..regions.regions import region_errors, row_count_errors
from .registry import slot_errors
from ..mixer.sends import SEND_FLAG_AT, SEND_TAG
from .sequence import link_errors
from ..mixer.slots import property_key_base
from .validate import validate_project

_SHELL_MAX = 14                     # payload of the OCuA shells before Audio 1 and past the last channel


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


def _misplaced_references(records, data: bytes) -> list[int]:
    """Owners whose strip reference sits outside their channel's record run — after another
    channel's records, or past the shells that close the mixer. Not `is_mixer_record`: a 2020
    save's channel records are 196 bytes, under its floor."""
    base = property_key_base(data)
    current, out = None, []
    for record in records:
        if record.tag == CHANNEL_TAG and len(record.raw) - HEADER > _SHELL_MAX:
            current = record.owner
        elif (record.tag == b"UCuA" and record.key == base and len(record.raw) - HEADER < 400
              and b".cst" in record.raw and record.owner != current):
            out.append(record.owner)
    return out


def _binding(data: bytes) -> dict:
    """``unbound_channels``: owners of in-use channels no object is bound to; ``binds_by_uuid``:
    whether any channel is bound at all (an older save binds none)."""
    bound = bound_objects(data)
    return {"unbound_channels": sorted(o for o, c in channels(data).items()
                                       if c.in_use and o not in bound),
            "binds_by_uuid": bool(bound)}


def _lost_bindings(was: dict, now: dict) -> list[str]:
    """The refusal when the result has more unbound in-use channels than the input — counted, as
    a channel insert renumbers owners; an input that binds none by uuid is not judged."""
    if not was["binds_by_uuid"]:
        return []
    was, now = was["unbound_channels"], now["unbound_channels"]
    if len(now) <= len(was):
        return []
    return [f"{len(now) - len(was)} more channel(s) in use that no track object is bound to — "
            f"the track has no strip in the mixer: {now}"]


def _empty() -> dict:
    return {"validate": [], "link_errors": 0, "bad_object_index": [], "bad_send_flags": [],
            "bad_key_flags": [], "bad_region_tracks": [], "bad_row_count": [], "bad_slot_entries": [],
            "bad_groups": [], "misplaced_references": [], "unbound_channels": [],
            "binds_by_uuid": False, "regions": [],
            "dangling_files": {"entries": [], "records": [], "unfiled": [], "files": [], "doubled": [], "rba": []},
            "unregistered_slots": [], "marker_blocks": [], "unreadable": None}


def structural_report(data: bytes) -> dict:
    """Every invariant this module knows, as counts and id lists. Never raises on a project it
    can walk; a project it cannot walk reports the failure under ``unreadable``.
    ``regions`` is an inventory, not a problem list: `regressions` names what it loses."""
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
            "misplaced_references": _misplaced_references(records, data),
            **_binding(data),
            "regions": placed(records),
            "dangling_files": dangling_files(records),
            "unregistered_slots": unregistered_slots(records),
            "marker_blocks": marker_block_errors(records),
            "unreadable": None,
        }
    except Exception as e:                      # a writer can leave bytes nothing can parse
        return {**_empty(), "unreadable": f"{type(e).__name__}: {e}"}


def regressions(before: bytes, after: bytes, *, removed: Iterable[RegionKey] = ()) -> list[str]:
    """What ``after`` broke that ``before`` had right. Empty means the write is safe to keep.
    ``removed``: the region keys (`integrity_regions.region_keys`) a writer deletes on purpose."""
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
                          "rows and drops the rest"),
                         ("misplaced_references", "strip reference(s) placed outside their channel's "
                          "records")):
        fresh = sorted(set(now[field]) - set(was[field]))
        if fresh:
            out.append(f"{len(fresh)} {label}: {fresh}")
    return out + _lost_bindings(was, now) + region_regressions(was, now, removed)


def require_no_regression(before: bytes, after: bytes, *, removed: Iterable[RegionKey] = ()) -> None:
    """Raise rather than let a writer's output reach disk in a worse state than its input."""
    found = regressions(before, after, removed=removed)
    if found:
        raise ValueError("refusing to write — the edit broke structure the input had right:\n  "
                         + "\n  ".join(found))
