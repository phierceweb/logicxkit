"""The .logicx bundle container: alternatives, ProjectData, and the OCuA channel blocks.

Channel model: each mixer channel is an ``OCuA <ver> 00 0e 00`` block (version word 06 or
07 depending on the Logic build that saved it) labelled `` Audio N``. Blocks run from one
header to the next, so a byte offset inside the file maps to exactly one channel.

This is container structure only — what a state *is* belongs to the package decoding it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

_CHANNEL_HDR = re.compile(rb"OCuA[\x02-\x08]\x00\x0e\x00")
# every strip type carries a label (probe 2026-06-12), not just audio channels
_LABEL = re.compile(rb" ((?:Audio|Input|Aux|Inst|Output|Bus|Master)(?: \d+)?)")


def is_bundle(path: str | Path) -> bool:
    """A .logicx bundle (a directory with Alternatives/), as opposed to a flat file."""
    p = Path(path)
    return p.is_dir() and (p / "Alternatives").is_dir()


def first_alternative(logicx: Path) -> str:
    alt_dir = logicx / "Alternatives"
    alts = sorted(p.name for p in alt_dir.iterdir() if p.is_dir()) if alt_dir.is_dir() else []
    if not alts:
        raise FileNotFoundError(f"no Alternatives/ in {logicx}")
    return alts[0]


def project_data(logicx: str | Path) -> bytes:
    p = Path(logicx)
    return (p / "Alternatives" / first_alternative(p) / "ProjectData").read_bytes()


def channel_blocks(data: bytes) -> list[tuple[int, int]]:
    """(start, end) for every OCuA channel block; end = next header or EOF."""
    heads = [m.start() for m in _CHANNEL_HDR.finditer(data)]
    heads.append(len(data))
    return [(heads[i], heads[i + 1]) for i in range(len(heads) - 1)]


def channel_label(seg: bytes) -> str:
    """Strip-type label from the block head: ``Audio 4`` / ``Bus 5`` / ``Master`` / …"""
    m = _LABEL.search(seg[:160])
    return m.group(1).decode() if m else "?"


def read_states(path: str | Path,
                decode: Callable[[bytes], list[dict]]) -> list[dict]:
    """Run `decode` over a flat file or a bundle's ProjectData.

    `decode` returns states carrying an ``offset``; for a bundle each gains a ``channel``
    (None when the state sits outside any recognized block).
    """
    p = Path(path)
    if not is_bundle(p):
        return decode(p.read_bytes())
    data = project_data(p)
    states = decode(data)
    blocks = channel_blocks(data)
    for s in states:
        s["channel"] = next(
            (channel_label(data[a:b]) for a, b in blocks if a <= s["offset"] < b),
            None)
    return states
