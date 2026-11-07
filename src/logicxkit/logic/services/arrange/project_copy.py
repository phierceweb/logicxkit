"""Copy a project for an edit: find the bundle, refuse an output that overlaps the input, leave
the alternatives an earlier Logic saved, and stage the copy beside its destination so an
interrupted run never leaves a hole where a previous output was. The input is never written."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..stream.validate import FORMAT_AT, MEASURED_FORMAT, file_format, require_measured_format, writes_format


def find_project(path: Path) -> Path:
    """Accept a .logicx, or a project folder containing one."""
    if path.suffix == ".logicx":
        return path
    found = sorted(path.glob("*.logicx")) or sorted(path.glob("*/*.logicx"))
    if not found:
        raise ValueError(f"no .logicx found under {path}")
    return found[0]


def _clone_tree(src: Path, dest: Path) -> None:
    """Copy a tree, preferring APFS clonefile — a song folder is often gigabytes of audio.

    ``cp -c`` makes copy-on-write clones: effectively instant and no extra disk, while still
    producing fully independent files. On failure it can leave a partial destination, so that
    is cleared before falling back rather than letting copytree trip over it.

    A bundle's ``Alternatives/*/Autosave*`` stays behind: Logic offers it on open, and it holds
    the source as it was before any edit to the copy.
    """
    done = subprocess.run(["cp", "-c", "-R", str(src), str(dest)], capture_output=True)
    if done.returncode != 0:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    for autosave in [*dest.glob("Alternatives/*/Autosave*"), *dest.glob("*.logicx/Alternatives/*/Autosave*")]:
        if autosave.is_dir():
            shutil.rmtree(autosave)
        else:
            autosave.unlink()


def _refuse_destructive_output(project: Path, root: Path, dest_root: Path) -> None:
    """Never let the output path alias the input — the copy would delete the source first.

    ``--out in`` is one keystroke from the documented ``--out out``, and the destination is
    removed before the copy, so without this the input project and all its audio are gone.
    Paths are resolved because a symlinked --out defeats a plain equality check.
    """
    src_r, dest_r = root.resolve(), dest_root.resolve()
    if src_r == dest_r or src_r.is_relative_to(dest_r) or dest_r.is_relative_to(src_r):
        raise ValueError(
            f"refusing: output '{dest_root}' overlaps the input '{root}' — "
            "this would delete the source project. Choose an --out outside it.")
    if not project.exists():
        raise ValueError(f"input project does not exist: {project}")


def _refuse_nested_output(root: Path, dest_dir: Path) -> None:
    """``dest_dir`` names the directory the copy goes INTO, not the copy itself.

    Pointing it at a previous output nests a fresh copy inside the stale one, which then sits
    at the path the user opens — the build looks like it did nothing.
    """
    if dest_dir.name == root.name and (dest_dir / f"{root.name}.logicx").exists():
        raise ValueError(
            f"--out '{dest_dir}' is already a copy of '{root.name}'. Pass the containing "
            f"directory ('{dest_dir.parent}'); otherwise the copy nests at "
            f"'{dest_dir / root.name}' and the stale one keeps the path you open.")


def stale_alternatives(project: Path) -> dict[str, int]:
    """The alternatives an earlier Logic saved in a format the running command does not write
    (`validate.writing_formats`), by name -> format word. They are left as they
    are when a current one sits beside them, as Logic keeps such bundles itself; with no current
    alternative (none at all included), or one saved by a later Logic, nothing is copied."""
    stale: dict[str, int] = {}
    stale_head = b""
    current = 0
    for data_file in sorted(project.glob("Alternatives/*/ProjectData")):
        with data_file.open("rb") as f:
            head = f.read(FORMAT_AT + 2)
        found = file_format(head)
        if found is not None and found < MEASURED_FORMAT and not writes_format(found):
            stale[data_file.parent.name] = found
            stale_head = stale_head or head
            continue
        try:
            require_measured_format(head)
        except ValueError as e:
            raise ValueError(f"Alternatives/{data_file.parent.name}: {e}") from None
        current += 1
    if not stale and not current:
        raise ValueError(f"{project.name}: no Alternatives/*/ProjectData — not a project Logic has saved")
    if not current:
        name = next(iter(stale))
        try:
            require_measured_format(stale_head)
        except ValueError as e:
            raise ValueError(f"Alternatives/{name}: {e}") from None
    return stale


def left_line(name: str, word: int) -> str:
    return f"Alternatives/{name} left as it is: saved by an earlier Logic (file format {word})"


def project_folder(project: Path) -> Path:
    """The folder a project lives in when Logic keeps its recordings beside it (an `Audio
    Files` sibling), else the bundle itself. A copy that took only the bundle would open with
    every region missing."""
    parent = project.parent
    return parent if (parent / "Audio Files").is_dir() else project


def copy_project(src: Path, dest_dir: Path) -> dict:
    """Safely copy a project into ``dest_dir`` — the whole project folder when the bundle has
    an `Audio Files` sibling. Input is never written.

    Staged beside the destination and moved into place only when complete, so an interrupted
    run cannot leave a hole where a previous output was.
    """
    project = find_project(src)
    root = src if src.is_dir() and src.suffix != ".logicx" else project_folder(project)
    dest_root = dest_dir / root.name
    _refuse_destructive_output(project, root, dest_root)
    _refuse_nested_output(root, dest_dir)
    left = stale_alternatives(project)

    if dest_dir.exists() and not dest_dir.is_dir():
        raise ValueError(f"--out {dest_dir} is a file, not a directory")
    dest_dir.mkdir(parents=True, exist_ok=True)
    staging = dest_dir / f".{root.name}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    _clone_tree(root, staging)
    if dest_root.exists():
        shutil.rmtree(dest_root)
    staging.rename(dest_root)
    dest = dest_root if root == project else dest_root / project.relative_to(root)
    return {"source": project, "root": root, "dest_root": dest_root, "dest": dest, "left": left}
