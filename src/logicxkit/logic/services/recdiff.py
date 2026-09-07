"""Positional diff of two ProjectData record streams.

Records align by position within the sequence of (tag, size) signatures — a `SequenceMatcher`
over that sequence turns an inserted track into one `added` row instead of a cascade of
changed rows, and never keys on (tag, owner, key): every `karT` row carries owner 65535 and
keys repeat per run, which once made a real change read as "nothing moved".

Offsets are relative to the record START (header included): 14/15 are header bytes that churn
on every save of `qSvE`, 36 is payload byte 0.
"""

from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .insert import project_records


@dataclass(frozen=True)
class Entry:
    index: int
    tag: bytes
    owner: int
    key: int
    size: int


@dataclass(frozen=True)
class Change:
    index: int
    tag: bytes
    owner: int
    key: int
    offsets: list[int]
    size_a: int
    size_b: int


@dataclass
class RecDiff:
    added: list[Entry] = field(default_factory=list)
    removed: list[Entry] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)
    same: int = 0


def _entry(i: int, r) -> Entry:
    return Entry(i, r.tag, r.owner, r.key, len(r.raw))


def _byte_diff(x: bytes, y: bytes) -> list[int]:
    n = min(len(x), len(y))
    offs = [i for i in range(n) if x[i] != y[i]]
    offs += list(range(n, max(len(x), len(y))))
    return offs


def diff_records(a: bytes, b: bytes, *, mask: dict[bytes, set[int]] | None = None) -> RecDiff:
    """Align the two streams and report added / removed / changed records."""
    ra, rb = project_records(a), project_records(b)
    sig_a = [(r.tag, len(r.raw)) for r in ra]
    sig_b = [(r.tag, len(r.raw)) for r in rb]
    out = RecDiff()
    mask = mask or {}

    def compare(i: int, j: int) -> None:
        offs = [o for o in _byte_diff(ra[i].raw, rb[j].raw) if o not in mask.get(ra[i].tag, ())]
        if offs:
            out.changed.append(Change(j, rb[j].tag, rb[j].owner, rb[j].key, offs,
                                      len(ra[i].raw), len(rb[j].raw)))
        else:
            out.same += 1

    matcher = difflib.SequenceMatcher(a=sig_a, b=sig_b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                compare(i, j)
        elif op == "replace" and (i2 - i1) == (j2 - j1):
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                if ra[i].tag == rb[j].tag:
                    compare(i, j)
                else:
                    out.removed.append(_entry(i, ra[i]))
                    out.added.append(_entry(j, rb[j]))
        else:
            out.removed += [_entry(i, ra[i]) for i in range(i1, i2)]
            out.added += [_entry(j, rb[j]) for j in range(j1, j2)]
    return out


def noise_mask(a: bytes, b: bytes) -> dict[bytes, set[int]]:
    """Offsets per tag that differ between two saves of one unchanged project.

    Measured on this file, not copied from another: a no-op re-save moved 23 gnoS bytes on
    one session and 415 channel records on another.
    """
    mask: dict[bytes, set[int]] = {}
    for change in diff_records(a, b).changed:
        mask.setdefault(change.tag, set()).update(change.offsets)
    return mask


def load_project_data(path: str | Path) -> bytes:
    """Bytes of a bare ``ProjectData``, a ``Project File Backups/NN`` dir, or a ``.logicx``."""
    p = Path(path)
    if p.is_file():
        return p.read_bytes()
    if (p / "ProjectData").is_file():
        return (p / "ProjectData").read_bytes()
    alts = sorted((p / "Alternatives").glob("*/ProjectData"))
    if not alts:
        raise FileNotFoundError(f"no ProjectData under {p}")
    return alts[0].read_bytes()


def summary(diff: RecDiff) -> dict:
    """Counts per tag for a one-screen report."""
    return {"added": dict(Counter(e.tag.decode("latin-1") for e in diff.added)),
            "removed": dict(Counter(e.tag.decode("latin-1") for e in diff.removed)),
            "changed": dict(Counter(c.tag.decode("latin-1") for c in diff.changed)),
            "same": diff.same}
