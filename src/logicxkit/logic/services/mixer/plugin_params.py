"""Parameter tables for Logic's own plug-ins: name -> index in the `GAMETSPP` float block, one
JSON per plug-in type (`params-<type>.json` under a `logic/` data directory), each index
measured from Logic's own saves. `decode` reads a float block by name; `set_by_name` patches
one, refusing a value outside the measured range. A word a table marks ``"kind": "int"`` holds
an int32 in the float block (Vintage B3's drawbars) and reads and writes as that integer. A
parameter with an ``offset`` instead of an ``index`` is a word past the block, at that payload
offset (most of Vintage B3's state); `decode_payload` reads both kinds from a slot payload.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..._binary import find_blocks, patch_block_floats, read_block_floats
from ....utils.data import data_dirs


def _key(name: str) -> str:
    """A name's lookup key: letters and digits, with a sharp or flat kept as a word ("Quantize
    C♯" and "Quantize C" are two parameters)."""
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("♯", " sharp").replace("#", " sharp").replace("♭", " flat"))


@dataclass(frozen=True)
class Param:
    index: int
    name: str
    unit: str = ""
    min: float | None = None
    max: float | None = None
    default: float | str | None = None
    choices: tuple[str, ...] = ()
    evidence: str = "value"          # "value": the float matched the display; "order": by row order only, read and never written
    kind: str = "float"              # "int": the word is an int32, not a float
    offset: int | None = None        # a word past the block, at this payload offset; index is -1 then
    key: str | None = None           # a text state's key (`state: "text"`); the first field times `scale`
    scale: float = 1.0
    mirror: int | None = None        # a payload offset holding the same number as a float (Vintage B3's lower manual)
    linked: tuple[int, ...] = ()     # block words that moved with this row's in Logic; written when the one measured shape (the next word) alone
    curve: tuple[tuple[float, float], ...] = ()   # (word, shown) pairs where the display is not linear in the word
    named: tuple[tuple[str, float], ...] = ()     # a word the display names instead of numbering ("Free" at -10)


@dataclass(frozen=True)
class Table:
    type: int
    name: str
    floats: int
    params: tuple[Param, ...]
    opaque: tuple[int, ...] = ()
    evidence: str = ""
    variant: int | None = None       # the plug-in's variant base (`slot_width.plugin_variant`)
    state: str = "floats"            # "text": `Key = value` lines after the marker `46ia` (Alchemy); read-only
    _by_key: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> Table:
        params = tuple(Param(p.get("index", -1), p["name"], p.get("unit", ""), p.get("min"), p.get("max"),
                             p.get("default"), tuple(p.get("choices", ())), p.get("evidence", "value"),
                             p.get("kind", "float"), p.get("offset"), p.get("key"), p.get("scale", 1.0),
                             p.get("mirror"), tuple(p.get("linked", ())),
                             tuple((float(w), float(v)) for w, v in p.get("curve", ())),
                             tuple((str(k), float(v)) for k, v in p.get("named", {}).items()))
                       for p in d["params"])
        table = cls(d["type"], d["name"], d["floats"], params, tuple(d.get("opaque", ())), d.get("evidence", ""),
                    d.get("variant"), d.get("state", "floats"))
        keys = [_key(p.name) for p in params]
        if len(set(keys)) != len(keys):
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            raise ValueError(f"{d['name']}: two parameters share a name key: {', '.join(dupes)}")
        table._by_key.update(dict(zip(keys, params, strict=True)))
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
    """The block's values by parameter name; a choice reads as its name. Words past the block
    (``offset``) need the payload: `decode_payload`."""
    out: dict[str, float | str] = {}
    for p in table.params:
        if p.offset is not None or p.index >= len(floats):
            continue
        out[p.name] = _shown(p, int_word(floats[p.index]) if p.kind == "int" else _scaled(p, floats[p.index]))
    return out


def _scaled(p: Param, word: float) -> float:
    """What Logic shows for a float word: through its ``curve`` where the display is not linear
    in the word, else the word times the table's ``scale`` (Drum Synth's Tone shows 100 per 1)."""
    if p.curve:
        return round(_along(p.curve, word), 6)
    return round(word * p.scale, 6) if p.scale != 1.0 else word


TEXT_MARK = b"46ia"                  # the state is text from 6 bytes past it: Alchemy's `.acp` lines


def text_state(payload: bytes) -> dict[str, str]:
    """A text state's `Key = value…` lines as `section[n].key` -> value text: a `<tag>` line opens
    a section, numbered by how often its tag has appeared (Alchemy's four `<source>`s repeat
    every key). A re-save's appended second copy counts on from there."""
    at = payload.find(TEXT_MARK)
    if at < 0:
        return {}
    out: dict[str, str] = {}
    seen: dict[bytes, int] = {}
    section = ""
    for line in payload[at + 6:].split(b"\r\n"):
        if line.startswith(b"<") and line.endswith(b">"):
            tag = line[1:-1]
            seen[tag] = seen.get(tag, 0) + 1
            section = f"{tag.decode('latin-1')}[{seen[tag]}]."
            continue
        key, sep, value = line.partition(b" = ")
        if sep:
            name = section + key.decode("latin-1")
            while name in out:
                name += "'"
            out[name] = value.decode("latin-1")
    return out


def decode_payload(table: Table, payload: bytes) -> dict[str, float | str]:
    """Every parameter the table names, from a slot payload: the block's by index, the rest by
    payload offset; a text state's by key."""
    if table.state == "text":
        lines = text_state(payload)
        out: dict[str, float | str] = {}
        for p in table.params:
            first = lines.get(p.key or "", "").split()
            if first:
                try:
                    out[p.name] = _shown(p, round(float(first[0]) * p.scale, 6))
                except ValueError:
                    out[p.name] = first[0]
        return out
    blocks = find_blocks(payload)
    out = decode(table, list(read_block_floats(payload, *max(blocks, key=lambda b: b[2])[::2]))) if blocks else {}
    for p in table.params:
        if p.offset is not None and p.offset + 4 <= len(payload):
            word = struct.unpack_from("<i" if p.kind == "int" else "<f", payload, p.offset)[0]
            out[p.name] = _shown(p, word if p.kind == "int" else _scaled(p, word))
    return out


def _shown(p: Param, value: float | int) -> float | int | str:
    for name, word in p.named:
        if value == word:
            return name
    if p.choices and float(value).is_integer() and 0 <= int(value) < len(p.choices):
        return p.choices[int(value)]
    return value


def set_by_name(table: Table, payload: bytes, values: dict[str, float | str]) -> bytes:
    """The slot payload with each named parameter's float set; a choice by name or number."""
    if table.state == "text":
        raise ValueError(f"{table.name} keeps its state as text, which is read here and not written")
    blocks = find_blocks(payload)
    if not blocks:
        raise ValueError("the payload carries no parameter block")
    idx, type_id, n = blocks[0]
    if type_id != table.type:
        raise ValueError(f"the block is plug-in type {type_id}, not {table.type} ({table.name})")
    # a save made after a move carries the block again (the compare copy), its offset words with
    # it: every same-size copy takes the value, so the record does not disagree with itself
    copies = [b[0] for b in blocks if b[1:] == (type_id, n)]
    body = bytearray(payload)
    for start in copies:
        floats = list(read_block_floats(payload, start, n))
        for name, value in values.items():
            p = table.param(name)
            if p.evidence == "order":
                raise ValueError(f"{table.name} {p.name}: its word is named by row order alone, which coded series "
                                 "found wrong for 13 of 411 rows; it is read, not written")
            if p.linked and p.linked != (p.index + 1,):
                raise ValueError(f"{table.name} {p.name}: moving this row in Logic also moves word(s) "
                                 f"{', '.join(map(str, p.linked))}; a write of its own word alone is unmeasured")
            if p.offset is not None:
                at = p.offset + (start - idx)
                if at + 4 > len(body):
                    raise ValueError(f"{table.name} {p.name}: offset {p.offset} is past the record's {len(body)} bytes")
                word = _coerce(table, p, value)
                struct.pack_into("<i" if p.kind == "int" else "<f", body, at, word)
                if p.mirror is not None:
                    if p.mirror + (start - idx) + 4 > len(body):
                        raise ValueError(f"{table.name} {p.name}: mirror offset {p.mirror} is past the record's {len(body)} bytes")
                    struct.pack_into("<f", body, p.mirror + (start - idx), float(word))
                continue
            if p.index >= n:
                raise ValueError(f"{table.name} {p.name}: index {p.index} is past the block's {n} floats")
            floats[p.index] = _coerce(table, p, value)
        patch_block_floats(body, start, 0, floats)
    return bytes(body)


def _along(points: tuple[tuple[float, float], ...], x: float, inverse: bool = False) -> float:
    """Piecewise-linear interpolation through measured (word, shown) points — word to shown, or
    shown to word with ``inverse`` — held at the ends past the first and last point."""
    pairs = sorted((b, a) if inverse else (a, b) for a, b in points)
    if x <= pairs[0][0]:
        return pairs[0][1]
    if x >= pairs[-1][0]:
        return pairs[-1][1]
    for (x0, y0), (x1, y1) in zip(pairs, pairs[1:], strict=False):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pairs[-1][1]


def int_word(value: float) -> int:
    """The int32 whose bits a float list carries as this (denormal) float32."""
    return struct.unpack("<i", struct.pack("<f", value))[0]


def _as_word(n: int) -> float:
    return struct.unpack("<f", struct.pack("<i", n))[0]


def _coerce(table: Table, p: Param, value: float | str) -> float:
    if p.named and isinstance(value, str) and not _number(value):
        for name, word in p.named:
            if _key(name) == _key(value):
                return word
    if p.choices and isinstance(value, str) and not _number(value):
        keys = [_key(c) for c in p.choices]
        if _key(value) not in keys:
            raise ValueError(f"{table.name} {p.name}: {value!r} is not one of {', '.join(p.choices)}")
        return keys.index(_key(value)) / p.scale            # a scaled choice: D-Mode's "On" is word 100 at scale 0.01
    if isinstance(value, str) and not _number(value):
        raise ValueError(f"{table.name} {p.name}: {value!r} is not a number, and the row has no named choices")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{table.name} {p.name}: {value!r} is not a finite number")
    if p.min is not None and number < p.min or p.max is not None and number > p.max:
        raise ValueError(f"{table.name} {p.name}: {number} is outside {p.min}..{p.max} {p.unit}".rstrip())
    if p.kind == "int":
        if not number.is_integer():
            raise ValueError(f"{table.name} {p.name}: {value!r} is not a whole number")
        return int(number) if p.offset is not None else _as_word(int(number))
    if p.curve:
        return round(_along(p.curve, number, inverse=True), 6)
    return number / p.scale if p.scale != 1.0 else number


def _number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
