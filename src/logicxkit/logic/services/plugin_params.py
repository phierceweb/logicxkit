"""Parameter tables for Logic's own plug-ins: name -> index in the `GAMETSPP` float block, one
JSON per plug-in type (`params-<type>.json` under a `logic/` data directory), each index
measured from Logic's own saves. `decode` reads a float block by name; `set_by_name` patches
one, refusing a value outside the measured range.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .._binary import find_blocks, patch_block_floats, read_block_floats
from ...utils.data import data_dirs


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass(frozen=True)
class Param:
    index: int
    name: str
    unit: str = ""
    min: float | None = None
    max: float | None = None
    default: float | str | None = None
    choices: tuple[str, ...] = ()
    evidence: str = "value"          # "value": the float matched the display; "order": by row order only


@dataclass(frozen=True)
class Table:
    type: int
    name: str
    floats: int
    params: tuple[Param, ...]
    opaque: tuple[int, ...] = ()
    evidence: str = ""
    variant: int | None = None       # the plug-in's variant base (`slot_width.plugin_variant`)
    _by_key: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> Table:
        params = tuple(Param(p["index"], p["name"], p.get("unit", ""), p.get("min"), p.get("max"),
                             p.get("default"), tuple(p.get("choices", ())), p.get("evidence", "value"))
                       for p in d["params"])
        table = cls(d["type"], d["name"], d["floats"], params, tuple(d.get("opaque", ())), d.get("evidence", ""),
                    d.get("variant"))
        table._by_key.update({_key(p.name): p for p in params})
        return table

    def param(self, name: str) -> Param:
        try:
            return self._by_key[_key(name)]
        except KeyError:
            raise KeyError(f"{self.name} has no parameter {name!r}; it has: "
                           + ", ".join(p.name for p in self.params)) from None

    def index(self, name: str) -> int:
        return self.param(name).index


def load_tables(dirs: list[Path] | None = None) -> dict[int | tuple[int, int], Table]:
    """Every table under ``dirs`` (the `logic/` data directories by default) by block type
    and, when it names its variant base, by ``(type, variant)`` too; the first directory
    holding a key wins. A type shared by several plug-ins (Tape Delay and Echo are both 147)
    keeps the plain key for `params-<type>.json`; the others are `params-<type>v<variant>.json`."""
    out: dict[int | tuple[int, int], Table] = {}
    for d in (dirs if dirs is not None else data_dirs("logic")):
        for path in sorted(Path(d).glob("params-*.json")):
            table = Table.from_dict(json.loads(path.read_text()))
            if table.variant is not None:
                out.setdefault((table.type, table.variant), table)
            if path.stem == f"params-{table.type}":
                out.setdefault(table.type, table)
    return out


def table_for(tables: dict, type_id: int, variant: int | None = None) -> Table | None:
    """The table for a block of ``type_id`` in a record of ``variant`` (`slot_width.plugin_variant`):
    the variant's own, else the type's — unless the type's tables name variants and this is
    none of them."""
    if variant is not None:
        if (type_id, variant) in tables:
            return tables[(type_id, variant)]
        if any(isinstance(k, tuple) and k[0] == type_id for k in tables):
            return None
    return tables.get(type_id)


def load_table(type_id: int, dirs: list[Path] | None = None) -> Table:
    tables = load_tables(dirs)
    if type_id not in tables:
        raise KeyError(f"no parameter table for plug-in type {type_id}")
    return tables[type_id]


def decode(table: Table, floats: list[float]) -> dict[str, float | str]:
    """The block's values by parameter name; a choice reads as its name."""
    out: dict[str, float | str] = {}
    for p in table.params:
        if p.index >= len(floats):
            continue
        value = floats[p.index]
        if p.choices and float(value).is_integer() and 0 <= int(value) < len(p.choices):
            out[p.name] = p.choices[int(value)]
        else:
            out[p.name] = value
    return out


def set_by_name(table: Table, payload: bytes, values: dict[str, float | str]) -> bytes:
    """The slot payload with each named parameter's float set; a choice by name or number."""
    blocks = find_blocks(payload)
    if not blocks:
        raise ValueError("the payload carries no parameter block")
    idx, type_id, n = blocks[0]
    if type_id != table.type:
        raise ValueError(f"the block is plug-in type {type_id}, not {table.type} ({table.name})")
    floats = list(read_block_floats(payload, idx, n))
    for name, value in values.items():
        p = table.param(name)
        if p.index >= n:
            raise ValueError(f"{table.name} {p.name}: index {p.index} is past the block's {n} floats")
        floats[p.index] = _coerce(table, p, value)
    body = bytearray(payload)
    patch_block_floats(body, idx, 0, floats)
    return bytes(body)


def _coerce(table: Table, p: Param, value: float | str) -> float:
    if p.choices and isinstance(value, str) and not _number(value):
        keys = [_key(c) for c in p.choices]
        if _key(value) not in keys:
            raise ValueError(f"{table.name} {p.name}: {value!r} is not one of {', '.join(p.choices)}")
        return float(keys.index(_key(value)))
    number = float(value)
    if p.min is not None and number < p.min or p.max is not None and number > p.max:
        raise ValueError(f"{table.name} {p.name}: {number} is outside {p.min}..{p.max} {p.unit}".rstrip())
    return number


def _number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
