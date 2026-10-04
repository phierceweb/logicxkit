"""The goldens by key. `tests/goldens/manifest.json` names the public corpus, tracked under
`tests/corpus/`, and the untracked `resources/experiments/manifest.json` the owner's sessions, so
their titles stay out of the tracked tree. Each key asked for is tallied for the end-of-run line;
`LOGICXKIT_REQUIRE_GOLDENS=1` fails on any missing key, `=public` only on one the public manifest
names."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _paths import RESOURCES

TESTS = Path(__file__).resolve().parent
CORPUS = TESTS / "corpus"                                   # the public corpus, tracked
PUBLIC = TESTS / "goldens" / "manifest.json"                # its manifest, paths under CORPUS
MANIFEST = RESOURCES / "experiments" / "manifest.json"      # the owner's, paths under RESOURCES
# the owner's sessions, by where their manifest paths sit; `resave` is Logic 12.4's re-save of each
SESSION_DIRS = {"legacy": "legacy/", "mix": "mixes/", "resave": "experiments/logic-12-4/"}
REQUIRE = "LOGICXKIT_REQUIRE_GOLDENS"
MISSING_SHOWN = 8

asked: dict[str, bool] = {}          # key -> found, for the end-of-run line
_loaded: dict[str, dict] = {}        # manifest file -> its entries
_resolved: dict[str, tuple[dict | None, Path | None]] = {}   # key -> (entry, its corpus root)


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


def _lookup(key: str) -> tuple[dict | None, Path | None]:
    """The entry whose file is present, public first (owner first with ``LOGICXKIT_GOLDENS=owner``),
    with the root its path is relative to; else whichever names the key, so a missing file
    reports as missing, not unknown."""
    if key not in _resolved:
        public, owner = (PUBLIC, CORPUS), (MANIFEST, RESOURCES)
        order = (owner, public) if os.environ.get("LOGICXKIT_GOLDENS") == "owner" else (public, owner)
        candidates = [(e, root) for m, root in order if (e := _read(m).get(key))]
        present = [(e, root) for e, root in candidates
                   if "path" in e and (root / _relative(key, e["path"])).exists()]
        _resolved[key] = present[0] if present else (candidates[0] if candidates else (None, None))
    return _resolved[key]


def entry(key: str) -> dict | None:
    return _lookup(key)[0]


def path(key: str) -> Path | None:
    """The golden's path, or None (recorded) when no manifest names it or the file is missing."""
    e, root = _lookup(key)
    p = root / _relative(key, e["path"]) if e and "path" in e else None
    found = p is not None and p.exists()
    asked[key] = found
    return p if found else None


def _relative(key: str, raw: str) -> str:
    """A manifest path has to stay inside its corpus root; `Path(root) / "/abs"` is silently the
    absolute path, so an entry could point a golden anywhere."""
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"golden {key!r} names {raw!r} — a manifest path must be relative to "
                         "its corpus root with no '..'")
    return raw


def session_keys(kind: str | None = None) -> tuple[str, ...]:
    """The owner's session keys, in manifest order: the owner's entries whose file sits under
    `legacy/` (older-template projects), `mixes/` (finished mixes) or `experiments/logic-12-4/`
    (the current Logic's re-saves of both), or ``kind``'s alone."""
    prefixes = tuple(SESSION_DIRS.values()) if kind is None else (SESSION_DIRS[kind],)
    return tuple(k for k, e in _read(MANIFEST).items()
                 if isinstance(e, dict) and str(e.get("path", "")).startswith(prefixes)
                 and str(e["path"]).endswith(".logicx"))             # not a file inside a session's bundle


def sessions(*keys: str) -> list[Path]:
    """The owner's sessions on this machine (every key asked, so the run's line counts it)."""
    return [p for k in (keys or session_keys()) if (p := path(k)) is not None]


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
                             + f" ({REQUIRE}=public — the checkout lacks part of {CORPUS})")
    if not missing:
        return line
    # A checkout without the corpus misses every key; naming all of them buries the count.
    if len(missing) == len(asked):
        return line + "; none on this machine"
    if len(missing) > MISSING_SHOWN:
        shown = ", ".join(missing[:MISSING_SHOWN])
        return f"{line}; missing: {shown} (+{len(missing) - MISSING_SHOWN} more)"
    return full
