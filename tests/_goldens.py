"""The goldens by key, not by filename.

`resources/experiments/manifest.json` (untracked, beside the goldens) maps neutral keys to
files and to the facts a test may assert about them — song titles and channel names never
enter the tracked tree. A test asks for a key; a missing key or file skips with its name,
and every key asked for is counted so the run can say which goldens it had.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _paths import RESOURCES

MANIFEST = RESOURCES / "experiments" / "manifest.json"
REQUIRE = "LOGICXKIT_REQUIRE_GOLDENS"
MISSING_SHOWN = 8

asked: dict[str, bool] = {}          # key -> found, for the end-of-run line
_cache: dict | None = None


def manifest() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    return _cache


def entry(key: str) -> dict | None:
    return manifest().get(key)


def path(key: str) -> Path | None:
    """The golden's path, or None (recorded) when the manifest or the file is missing."""
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
    if missing and os.environ.get(REQUIRE):
        raise AssertionError(full + f" ({REQUIRE} is set)")
    if not missing:
        return line
    # A checkout without the corpus misses every key; naming all of them buries the count.
    if len(missing) == len(asked):
        return line + "; none on this machine"
    if len(missing) > MISSING_SHOWN:
        shown = ", ".join(missing[:MISSING_SHOWN])
        return f"{line}; missing: {shown} (+{len(missing) - MISSING_SHOWN} more)"
    return full
