"""Embedded AU state: Logic stores third-party plugin state as XML plists inside `.cst` files
and ``ProjectData`` alike, each a full AU ClassInfo dict."""

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
        # A document holds one declaration, so only the last one before this </plist> can parse.
        start = data.rfind(b"<?xml", i, end)
        stop = end + len(b"</plist>")
        try:
            pl = plistlib.loads(data[start:stop])
        except Exception:
            pl = None
        if isinstance(pl, dict):
            out.append((start, pl))
        pos = stop
    return out


def fourcc(n: int) -> str:
    s = struct.pack(">I", n & 0xFFFFFFFF).decode("latin-1")
    return s if s.isascii() and s.isprintable() else f"0x{n:08X}"
