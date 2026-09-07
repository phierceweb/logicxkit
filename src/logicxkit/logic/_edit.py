"""What every apply command shares: copy the project, edit each ProjectData, never the input."""

from __future__ import annotations

import plistlib
import shutil
from collections.abc import Callable
from pathlib import Path

from pf_core.utils.io import atomic_write_bytes

from .services.integrity import require_no_regression
from .services.project import project_metadata
from .services.retrack import copy_project, find_project
from .services.transplant import owner_of


class CommandError(Exception):
    """A user-facing failure: printed, exit 1."""


Step = Callable[[bytes, "int | None", Path], bytes]


def edit_copy(project: Path, out: Path, step: Step) -> Path:
    """Copy ``project`` into ``out`` and run ``step(data, track_count, data_file)`` over every
    ProjectData in the copy, writing what it returns.

    Two gates: the result is held against its input before anything is written, and read back
    afterwards to confirm the bytes that landed are the bytes that passed.
    """
    copied = copy_project(project, out)
    dest, root = copied["dest"], copied["dest_root"]
    print(f"into : {dest}\n")
    for data_file in sorted(dest.rglob("Alternatives/*/ProjectData")):
        count = project_metadata(data_file.parents[2]).get("tracks")
        before = data_file.read_bytes()
        after = step(before, count, data_file)
        try:
            require_no_regression(before, after)
        except ValueError as e:
            _discard(root)
            raise CommandError(f"{data_file.parent.name}: {e}") from None
        atomic_write_bytes(data_file, after)
        if data_file.read_bytes() != after:
            _discard(root)
            raise CommandError(f"{data_file.parent.name}: the bytes on disk are not the bytes "
                               "that passed the gate — the write did not land intact")
    return dest


def _discard(root: Path) -> None:
    """Take the whole copy away rather than leave a bundle whose parts disagree.

    A step may already have moved this alternative's ``NumberOfTracks`` — or written an earlier
    alternative — before a later one was refused, and a bundle that opens but half-matches its
    own metadata is worse than no bundle.
    """
    if root.exists():
        shutil.rmtree(root)
        print(f"discarded: {root}")


def first_project_data(project: Path) -> bytes:
    bundle = find_project(project)
    return sorted(bundle.glob("Alternatives/*/ProjectData"))[0].read_bytes()


def bump_track_count(data_file: Path, by: int = 1) -> int:
    """``NumberOfTracks`` in the alternative's MetaData.plist, moved by ``by``."""
    md_path = data_file.parent / "MetaData.plist"
    md = plistlib.loads(md_path.read_bytes())
    md["NumberOfTracks"] = int(md.get("NumberOfTracks", 0)) + by
    atomic_write_bytes(md_path, plistlib.dumps(md))
    return md["NumberOfTracks"]


def object_by_name(data: bytes, name: str, count: int | None) -> int:
    """The track object named ``name`` in the arrange list; exactly one must match. A name a
    stack header shares with a channel — ``Drums``, ``Bass`` — is written ``Drums (Sub 1)``
    or ``Drums (Aux 2)``: the mixer label in parentheses picks the row."""
    from .services.stacks import read_tracks
    rows = read_tracks(data, count)
    wanted, label = name.strip(), None
    if wanted.endswith(")") and " (" in wanted:
        wanted, _, label = wanted[:-1].rpartition(" (")
    hits = [r["object_id"] for r in rows
            if r["name"] == wanted and (label is None or r["label"] == label)]
    if len(hits) != 1:
        if len(hits) > 1:
            labels = ", ".join(f"{wanted} ({r['label']})" for r in rows if r["name"] == wanted)
            raise CommandError(f"{name!r}: more than one track by that name; say which: {labels}")
        raise CommandError(f"{name!r}: no track by that name")
    return hits[0]


def owner_by_label(data: bytes, label: str) -> int:
    """The channel owner carrying mixer label ``label`` (``Audio 5``, ``Bus 15``, ``Sub 3``)."""
    owner = owner_of(data, label.strip())
    if owner is None:
        raise CommandError(f"no channel labelled {label.strip()!r}")
    return owner


def pairs(specs: list[str]) -> list[tuple[str, str]]:
    """``LABEL`` or ``DST_LABEL=SRC_LABEL`` -> (dst, src)."""
    out = []
    for spec in specs:
        dst, _, src = spec.partition("=")
        out.append((dst.strip(), (src or dst).strip()))
    return out
