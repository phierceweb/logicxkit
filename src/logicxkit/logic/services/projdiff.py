"""Project↔project diff and project↔strip-library drift for ``.logicx`` reports.

Pure functions over :func:`~logicxkit.logic.services.project.read_project` report dicts —
file IO stays in the callers/CLI. Channels align by their strip label (``Audio 4``,
``Bus 5``); the library drift check compares **plugin sequences only** (preset names
ignored): the canonical drift case — ``Snare Down.cst`` saved as Gain→Channel EQ while
songs print InPhase→Pro-Q→Neutron→Pro-C — is plugin-level, and preset strings add noise,
not signal, to that question.
"""

from __future__ import annotations

from pathlib import Path

from .project import strip_chain


def _key(chain) -> list[tuple]:
    return [tuple(slot) for slot in chain]


def _plugins(chain) -> list[str]:
    return [plugin for plugin, _preset in chain]


def diff_projects(a: dict, b: dict) -> dict:
    """Changes turning report ``a`` into report ``b``: metadata fields + channel chains."""
    meta = {}
    ma, mb = a.get("metadata", {}), b.get("metadata", {})
    for k in sorted(set(ma) | set(mb)):
        if ma.get(k) != mb.get(k):
            meta[k] = (ma.get(k), mb.get(k))
    ca = {c["label"]: c["chain"] for c in a.get("channels", [])}
    cb = {c["label"]: c["chain"] for c in b.get("channels", [])}
    channels = []
    for label in sorted(set(ca) | set(cb)):
        if label not in cb:
            channels.append({"label": label, "status": "removed", "a": ca[label], "b": None})
        elif label not in ca:
            channels.append({"label": label, "status": "added", "a": None, "b": cb[label]})
        elif _key(ca[label]) != _key(cb[label]):
            channels.append(
                {"label": label, "status": "changed", "a": ca[label], "b": cb[label]})
    return {"metadata": meta, "channels": channels}


def index_strip_library(root: str | Path) -> dict[str, list[Path]]:
    """``{filename: [paths…]}`` for every ``.cst`` under ``root`` (sorted, recursive)."""
    idx: dict[str, list[Path]] = {}
    for p in sorted(Path(root).rglob("*.cst")):
        idx.setdefault(p.name, []).append(p)
    return idx


def diff_against_library(report: dict, library_root: str | Path) -> list[dict]:
    """Per referenced strip: does the in-project chain still match the saved ``.cst``?

    Statuses: ``match`` (plugin sequences equal), ``drift`` (they differ — either the
    channel was edited after loading or the saved strip moved on), ``missing`` (no file
    of that name under the library). Name collisions resolve to the first sorted path.
    """
    idx = index_strip_library(library_root)
    rows: list[dict] = []
    for c in report.get("channels", []):
        if not c["chain"]:
            continue  # nothing embedded to compare (clean-save template channels)
        for name in c.get("cst", []):
            paths = idx.get(name)
            project = _plugins(c["chain"])
            if not paths:
                rows.append({"label": c["label"], "cst": name, "status": "missing",
                             "project": project, "strip": None, "path": None})
                continue
            strip = _plugins(strip_chain(paths[0].read_bytes()))
            rows.append({"label": c["label"], "cst": name,
                         "status": "match" if strip == project else "drift",
                         "project": project, "strip": strip, "path": str(paths[0])})
    return rows
