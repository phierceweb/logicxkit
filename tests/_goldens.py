"""The goldens by key. `tests/goldens/manifest.json` names the public corpus and the untracked
`resources/experiments/manifest.json` the owner's sessions, so their titles stay out of the
tracked tree. Each key asked for is tallied for the end-of-run line; `LOGICXKIT_REQUIRE_GOLDENS=1`
fails on any missing key, `=public` only on one the public manifest names."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _paths import RESOURCES

MANIFEST = RESOURCES / "experiments" / "manifest.json"                 # the owner's
PUBLIC = Path(__file__).resolve().parent / "goldens" / "manifest.json"  # the public corpus
REQUIRE = "LOGICXKIT_REQUIRE_GOLDENS"
MISSING_SHOWN = 8

asked: dict[str, bool] = {}          # key -> found, for the end-of-run line
_loaded: dict[str, dict] = {}        # manifest file -> its entries
_resolved: dict[str, dict | None] = {}


def reset() -> None:
    """Forget every cached manifest and resolution (the tests repoint the paths). Not the
    tally: that is the run's accounting, and a test wanting its own patches `asked`."""
    _loaded.clear()
    _resolved.clear()


def _read(manifest_file: Path) -> dict:
    key = str(manifest_file)
    if key not in _loaded:
        _loaded[key] = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    return _loaded[key]


def manifest() -> dict:
    """Every key either manifest knows; the public entry shadows the owner's."""
    return {**_read(MANIFEST), **_read(PUBLIC)}


def entry(key: str) -> dict | None:
    """The entry whose file is present, public first (owner first with ``LOGICXKIT_GOLDENS=owner``);
    else whichever names the key, so a missing file reports as missing, not unknown."""
    if key not in _resolved:
        order = (MANIFEST, PUBLIC) if os.environ.get("LOGICXKIT_GOLDENS") == "owner" else (PUBLIC, MANIFEST)
        candidates = [_read(m).get(key) for m in order]
        present = [e for e in candidates if e and "path" in e
                   and (RESOURCES / _under_resources(key, e["path"])).exists()]
        _resolved[key] = present[0] if present else next((e for e in candidates if e), None)
    return _resolved[key]


def path(key: str) -> Path | None:
    """The golden's path, or None (recorded) when no manifest names it or the file is missing."""
    e = entry(key)
    p = RESOURCES / _under_resources(key, e["path"]) if e and "path" in e else None
    found = p is not None and p.exists()
    asked[key] = found
    return p if found else None


def _under_resources(key: str, raw: str) -> str:
    """A manifest path has to stay inside `resources/`; `Path("resources") / "/abs"` is
    silently the absolute path, so an entry could point a golden anywhere."""
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"golden {key!r} names {raw!r} — a manifest path must be relative to "
                         f"{RESOURCES} with no '..'")
    return raw


def fact(key: str, name: str, default=None):
    """A fact the manifest records about a golden (a count, a label, a tempo)."""
    e = entry(key) or {}
    return e.get("facts", {}).get(name, default)


def needs(*keys: str):
    """Class decorator: skip unless every key resolves to a file."""
    missing = [k for k in keys if path(k) is None]
    return unittest.skipUnless(not missing, f"golden(s) not on this machine: {', '.join(missing)}")


def require(*keys: str) -> None:
    """Module-level: skip the whole file unless every key resolves."""
    missing = [k for k in keys if path(k) is None]
    if missing:
        raise unittest.SkipTest(f"golden(s) not on this machine: {', '.join(missing)}")


def report() -> str | None:
    if not asked:
        return None
    missing = sorted(k for k, ok in asked.items() if not ok)
    line = f"goldens: {sum(asked.values())} of {len(asked)} keys found"
    full = line + "; missing: " + ", ".join(missing) if missing else line
    mode = os.environ.get(REQUIRE)
    public_missing = [k for k in missing if k in _read(PUBLIC)]
    if missing and mode and mode != "public":
        raise AssertionError(full + f" ({REQUIRE} is set)")
    if public_missing and mode == "public":
        raise AssertionError(f"{line}; public corpus keys missing: " + ", ".join(public_missing)
                             + f" ({REQUIRE}=public — run bin/run fetch-corpus)")
    if not missing:
        return line
    # A checkout without the corpus misses every key; naming all of them buries the count.
    if len(missing) == len(asked):
        return line + "; none on this machine"
    if len(missing) > MISSING_SHOWN:
        shown = ", ".join(missing[:MISSING_SHOWN])
        return f"{line}; missing: {shown} (+{len(missing) - MISSING_SHOWN} more)"
    return full
