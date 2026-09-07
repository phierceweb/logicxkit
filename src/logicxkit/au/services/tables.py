"""AU parameter tables (``<data root>/au/*.json``, `utils.data`) + the value-naming join.

Tables carry factory metadata only (id/name/unit/min/max/default), generated
from the installed AUs via ``auprobe.swift list``; regenerate when a
plugin updates. They are vendor-described data, so they live outside the tracked tree. For FabFilter files the .ffp magic IS the AU subtype, so one
table serves both the .ffp and .aupreset families.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_EPS = 1e-6


def _data() -> Path:
    from ...utils.data import data_dir
    return data_dir("au")


@lru_cache(maxsize=None)
def load_table(manu_cc: str, subtype_cc: str) -> dict | None:
    p = _data() / f"{manu_cc}_{subtype_cc}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def available_tables() -> list[str]:
    d = _data()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def ffp_identity(magic: str) -> tuple[str, str]:
    """FabFilter .ffp files: (manufacturer, subtype) for the table lookup."""
    return ("FabF", magic)


def join_values(table: dict | None, pairs) -> list[dict]:
    """Name (id, value) pairs from a table; unknown ids stay as ``paramN``."""
    by_id = {p["id"]: p for p in (table or {}).get("params", [])}
    rows: list[dict] = []
    for pid, val in pairs:
        info = by_id.get(pid)
        if info is None:
            rows.append({"id": pid, "name": f"param{pid}", "unit": None,
                         "value": val, "default": None, "changed": None})
        else:
            rows.append({"id": pid, "name": info["name"], "unit": info["unit"],
                         "value": val, "default": info["default"],
                         "changed": abs(val - info["default"]) > _EPS})
    return rows
