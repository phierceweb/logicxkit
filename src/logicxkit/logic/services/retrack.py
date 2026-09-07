"""Retrack a project — repoint each channel's channel-strip reference at its tracking version.

⚠️ **This changes a LABEL, not a chain.** The `.cst` reference is what Logic shows on a
channel's *Setting* button; it is **not** a loader. Logic renders the plugin-slot records
embedded in the project, and a channel with a reference but no slot records has an empty
Audio FX column — confirmed in Logic's own save-time `WindowImage.jpg` for one legacy song, where
every channel shows its Setting name and no plugins. So repointing alone cannot put a chain on
a channel, and on a *mixed* project it mislabels channels that keep their original plugins.

Use it to correct provenance labels. To actually change a chain, the plugin-slot records
themselves must be replaced — the mechanism verified by the Surgery Test, where transplanted
slot records did change what Logic rendered.

The reference lives in a UCuA record as a **64-byte null-padded name at tag+52**, followed by a
64-byte category (its folder). Both are fixed width, so repointing never changes the file's
length — no record sizes, no header total, no offsets — and `retrack` asserts that.
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
from .validate import require_valid
from dataclasses import dataclass
from pathlib import Path

NAME_AT = 52          # bytes from the UCuA tag to the name field
FIELD = 64            # both the name and the category field
MAX_NAME = FIELD - 1  # the last byte must stay NUL or the name runs into the category
_CST = re.compile(rb"[\x20-\x7e]{1,60}\.cst")


@dataclass(frozen=True)
class Reference:
    offset: int   # start of the name field
    name: str
    category: str


def cst_references(data: bytes) -> list[Reference]:
    """Every channel-strip reference, in file order."""
    out = []
    for m in _CST.finditer(data):
        start = m.start()
        while start > 0 and 0x20 <= data[start - 1] <= 0x7E:
            start -= 1
        if data.rfind(b"UCuA", 0, start) != start - NAME_AT:
            continue
        fields = [data[start + i * FIELD: start + (i + 1) * FIELD].split(b"\x00")[0]
                  for i in (0, 1)]
        out.append(Reference(start, fields[0].decode("latin-1"), fields[1].decode("latin-1")))
    return out


def retrack(data: bytes, mapping: dict[str, str], category: str) -> tuple[bytes, dict]:
    """Repoint references named in ``mapping``; returns (new bytes, report).

    Raises rather than truncating if a replacement name cannot fit the fixed field.
    """
    def target(entry) -> tuple[str, str]:
        """A mapping value is either a name, or {"name", "category"} when the strip's folder
        differs from the default (Logic resolves a reference by name **and** its parent folder)."""
        if isinstance(entry, dict):
            return entry["name"], entry.get("category", category)
        return entry, category

    for entry in list(mapping.values()) + [category]:
        for field in target(entry) if entry is not category else (category,):
            if len(field.encode("latin-1")) > MAX_NAME:
                raise ValueError(f"'{field}' exceeds the {MAX_NAME}-byte field")

    buf = bytearray(data)
    repointed, untouched = [], []
    for ref in cst_references(data):
        entry = mapping.get(ref.name)
        if entry is None:
            untouched.append(ref.name)
            continue
        new, cat = target(entry)
        buf[ref.offset:ref.offset + FIELD] = new.encode("latin-1").ljust(FIELD, b"\x00")
        buf[ref.offset + FIELD:ref.offset + 2 * FIELD] = cat.encode("latin-1").ljust(
            FIELD, b"\x00")
        repointed.append((ref.name, new))

    if len(buf) != len(data):  # unreachable by construction; the guarantee is worth asserting
        raise AssertionError("retrack changed the file length")
    require_valid(bytes(buf))
    return bytes(buf), {
        "repointed": len(repointed),
        "changes": repointed,
        "untouched": sorted(set(untouched)),
    }


OWNER_AT = 14         # the record header's owner, from the UCuA tag


def reference_owner(data: bytes, ref: Reference) -> int:
    return struct.unpack_from("<H", data, ref.offset - NAME_AT + OWNER_AT)[0]


def retrack_channels(data: bytes, targets: dict[int, str | dict]) -> tuple[bytes, dict]:
    """Repoint the references of the channels in ``targets`` (owner -> a name, or
    ``{"name", "category"}``; the category stays unless given) -> ``(project, report)``.
    Several channels may share one old name and part ways here, which ``retrack`` refuses."""
    def target(entry, current: str) -> tuple[str, str]:
        if isinstance(entry, dict):
            return entry["name"], entry.get("category", current)
        return entry, current

    for entry in targets.values():
        fields = (entry["name"], entry.get("category", "")) if isinstance(entry, dict) else (entry,)
        for field in fields:
            if len(field.encode("latin-1")) > MAX_NAME:
                raise ValueError(f"'{field}' exceeds the {MAX_NAME}-byte field")
    buf = bytearray(data)
    changes, seen = [], set()
    for ref in cst_references(data):
        owner = reference_owner(data, ref)
        if owner not in targets:
            continue
        new, cat = target(targets[owner], ref.category)
        buf[ref.offset:ref.offset + FIELD] = new.encode("latin-1").ljust(FIELD, b"\x00")
        buf[ref.offset + FIELD:ref.offset + 2 * FIELD] = cat.encode("latin-1").ljust(FIELD, b"\x00")
        changes.append((owner, ref.name, new))
        seen.add(owner)
    missing = sorted(set(targets) - seen)
    if missing:
        raise ValueError(f"no strip reference on channel(s) {missing}")
    require_valid(bytes(buf))
    return bytes(buf), {"repointed": len(changes), "changes": changes}


def find_project(path: Path) -> Path:
    """Accept a .logicx, or a project folder containing one."""
    if path.suffix == ".logicx":
        return path
    found = sorted(path.glob("*.logicx")) or sorted(path.glob("*/*.logicx"))
    if not found:
        raise ValueError(f"no .logicx found under {path}")
    return found[0]


def missing_strips(mapping: dict[str, str], library: Path) -> list[str]:
    """Mapped targets that do not exist in the strip library — they would fail to load."""
    present = {p.name for p in library.rglob("*.cst")}
    wanted = {(v["name"] if isinstance(v, dict) else v) for v in mapping.values()}
    return sorted(wanted - present)


def _clone_tree(src: Path, dest: Path) -> None:
    """Copy a tree, preferring APFS clonefile — a song folder is often gigabytes of audio.

    ``cp -c`` makes copy-on-write clones: effectively instant and no extra disk, while still
    producing fully independent files. On failure it can leave a partial destination, so that
    is cleared before falling back rather than letting copytree trip over it.
    """
    done = subprocess.run(["cp", "-c", "-R", str(src), str(dest)], capture_output=True)
    if done.returncode == 0:
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


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

    dest_dir.mkdir(parents=True, exist_ok=True)
    staging = dest_dir / f".{root.name}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    _clone_tree(root, staging)
    if dest_root.exists():
        shutil.rmtree(dest_root)
    staging.rename(dest_root)
    dest = dest_root if root == project else dest_root / project.relative_to(root)
    return {"source": project, "root": root, "dest_root": dest_root, "dest": dest}


def retrack_bundle(src: Path, dest_dir: Path, mapping: dict[str, str], category: str) -> dict:
    """Copy a project and repoint every alternative's references. Input is never written.

    Copies exactly what ``src`` points at: a project FOLDER comes across whole, keeping the
    sibling ``Audio Files`` directory that Logic stores takes in (the bundle's own ``Media``
    folder is empty in that layout, so copying only the .logicx would lose the audio).

    The copy is staged beside the destination and moved into place only once it is complete,
    so an interrupted or failing run never destroys a previous output.
    """
    project = find_project(src)
    root = src if src.is_dir() and src.suffix != ".logicx" else project_folder(project)
    dest_root = dest_dir / root.name
    _refuse_destructive_output(project, root, dest_root)

    dest_dir.mkdir(parents=True, exist_ok=True)
    staging = dest_dir / f".{root.name}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    _clone_tree(root, staging)
    staged_project = staging if root == project else staging / project.relative_to(root)

    alts, total = [], {"repointed": 0, "changes": [], "untouched": []}
    for data_file in sorted(staged_project.glob("Alternatives/*/ProjectData")):
        before = data_file.read_bytes()
        after, report = retrack(before, mapping, category)
        if len(after) != len(before):
            raise AssertionError(f"{data_file} changed length")
        data_file.write_bytes(after)
        alts.append((data_file.parent.name, report))
        total["repointed"] += report["repointed"]
        total["changes"] += report["changes"]
        total["untouched"] = sorted(set(total["untouched"]) | set(report["untouched"]))

    if not alts:
        shutil.rmtree(staging)
        raise ValueError(f"no Alternatives/*/ProjectData under {project} — nothing was changed")

    if dest_root.exists():
        shutil.rmtree(dest_root)
    staging.rename(dest_root)
    dest = dest_root if root == project else dest_root / project.relative_to(root)
    return {"source": project, "dest": dest, "alternatives": alts, **total}
