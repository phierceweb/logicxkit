"""What every apply command shares: copy the project, edit each ProjectData, never the input."""

from __future__ import annotations

import plistlib
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

from pf_core.utils.io import atomic_write_bytes

from .services.stream.integrity import require_no_regression
from .services.project.project import project_metadata
from .services.arrange.retrack import copy_project, find_project, left_line, stale_alternatives
from .services.mixer.routing_loops import new_loops
from .services.mixer.transplant import owner_of
from .services.stream.validate import tolerating


class CommandError(Exception):
    """A user-facing failure: printed, exit 1."""


Step = Callable[[bytes, "int | None", Path], bytes]
Moved = Callable[[bytes, "int | None", Path], Iterable[tuple[int, int, int]]]


def edit_copy(project: Path, out: Path, step: Step, moved: Moved | None = None) -> Path:
    """Copy ``project`` into ``out`` and run ``step(data, track_count, data_file)`` over every
    ProjectData in the copy. Each result is held against its input before it is written and read
    back after; any failure discards the whole copy. ``moved(data, track_count, data_file)`` names
    the region keys the step moves or removes on purpose in that alternative
    (`integrity_regions.region_keys`)."""
    copied = copy_project(project, out)
    dest, root, left = copied["dest"], copied["dest_root"], copied["left"]
    print(f"into : {dest}\n")
    for name, word in left.items():
        print(f"  {left_line(name, word)}")
    try:
        for data_file in sorted(dest.rglob("Alternatives/*/ProjectData")):
            if data_file.parent.name in left:
                continue
            count = project_metadata(data_file.parents[2], data_file.parent.name).get("tracks")
            before = data_file.read_bytes()
            with tolerating(before):                 # a step answers for what it changes; the gate below for the rest
                after = step(before, count, data_file)
            now = project_metadata(data_file.parents[2], data_file.parent.name).get("tracks")     # a step may move it
            try:
                require_no_regression(before, after, removed=moved(before, count, data_file) if moved else (),
                                      track_counts=(count, now))
            except ValueError as e:
                raise CommandError(f"{data_file.parent.name}: {e}") from None
            atomic_write_bytes(data_file, after)
            if data_file.read_bytes() != after:
                raise CommandError(f"{data_file.parent.name}: the bytes on disk are not the bytes "
                                   "that passed the gate — the write did not land intact")
            for loop in new_loops(before, after):
                print(f"  {data_file.parent.name}: warning: this leaves a routing loop: {' -> '.join(loop)}")
    except BaseException:
        _discard(root)
        raise
    return dest


def edit_display(project: Path, out: Path, step: Callable[[Path], None]) -> Path:
    """Copy ``project`` into ``out`` and run ``step(alternative)`` over every alternative of the
    copy — the DisplayState writers, which have no byte gate. A failure discards the copy, so no
    half-edited bundle is left under ``out``."""
    from .services.song.controlbar import alternative_dirs
    copied = copy_project(project, out)
    dest, root, left = copied["dest"], copied["dest_root"], copied["left"]
    print(f"into : {dest}\n")
    for name, word in left.items():
        print(f"  {left_line(name, word)}")
    try:
        for alternative in alternative_dirs(dest):
            if alternative.name in left:
                continue
            step(alternative)
    except BaseException:
        _discard(root)
        raise
    return dest


def _discard(root: Path) -> None:
    """Remove the copy: earlier alternatives or ``NumberOfTracks`` may already be written."""
    if root.exists():
        shutil.rmtree(root)
        print(f"discarded: {root}")


def written_alternatives(bundle: Path) -> list[Path]:
    """The ProjectData files a write edits, in name order: an earlier Logic's are left
    (`stale_alternatives`). All of them when the bundle would be refused."""
    found = sorted(bundle.glob("Alternatives/*/ProjectData"))
    try:
        left = stale_alternatives(bundle)
    except ValueError:
        left = {}
    return [f for f in found if f.parent.name not in left] or found


def plan_alternatives(bundle: Path) -> list[Path]:
    """`written_alternatives`, after printing the run's line for each alternative it leaves."""
    try:
        left = stale_alternatives(bundle)
    except ValueError:
        left = {}
    for name, word in left.items():
        print(f"  {left_line(name, word)}")
    return written_alternatives(bundle)


def display_source(bundle: Path) -> Path | None:
    """The first alternative a write would edit that carries a DisplayState.plist."""
    from .services.song.controlbar import alternative_dirs
    names = {f.parent.name for f in written_alternatives(bundle)}
    dirs = alternative_dirs(bundle)
    return next((d for d in dirs if d.name in names), dirs[0] if dirs else None)


def first_project_data(project: Path) -> bytes:
    """The first alternative a write edits."""
    bundle = find_project(project)
    found = written_alternatives(bundle)
    if not found:
        raise CommandError(f"no project at {bundle}")
    return found[0].read_bytes()


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
    from .services.arrange.stacks import read_tracks
    from .services.arrange.trackname import one_object
    try:
        return one_object(read_tracks(data, count), name)
    except ValueError as e:
        raise CommandError(str(e)) from None


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
