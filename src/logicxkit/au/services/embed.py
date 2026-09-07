"""Embedded AU state scanning — Logic stores 3rd-party plugin state as raw XML
plists inside its binaries (identically in ``.cst`` files and ``.logicx``
``ProjectData``). Each plist is a full AU ClassInfo dict: identity fourccs
(``type``/``subtype``/``manufacturer``), preset ``name``, and the state itself
(``data`` pairs and/or vendor blob keys)."""

from __future__ import annotations

import plistlib
import struct


def find_au_plists(data: bytes) -> list[tuple[int, dict]]:
    """Every embedded XML plist that parses to a dict, as ``(offset, plist)``."""
    out: list[tuple[int, dict]] = []
    pos = 0
    while True:
        i = data.find(b"<?xml", pos)
        if i < 0:
            break
        end = data.find(b"</plist>", i)
        if end < 0:
            break
        try:
            pl = plistlib.loads(data[i : end + len(b"</plist>")])
        except Exception:
            pos = i + len(b"<?xml")
            continue
        if isinstance(pl, dict):
            out.append((i, pl))
        pos = end + len(b"</plist>")
    return out


def fourcc(n: int) -> str:
    s = struct.pack(">I", n & 0xFFFFFFFF).decode("latin-1")
    return s if s.isascii() and s.isprintable() else f"0x{n:08X}"
