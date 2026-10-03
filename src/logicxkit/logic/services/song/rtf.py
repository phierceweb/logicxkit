"""The text of an RTF name as Logic's own rename writes one (Cocoa's writer): the document's
runs with the font, colour and other destination groups left out, `\\'hh` as a cp1252 byte,
`\\uN` as a UTF-16 unit (a pair for a character past the BMP), `\\` before a line end as the
line break."""

from __future__ import annotations

import re
import struct

_WORD = re.compile(rb"\\([A-Za-z]+)(-?\d+)? ?")
_DESTINATION = re.compile(rb"\\(\*|(fonttbl|colortbl|stylesheet|info)\b)")
_BREAKS = {b"par": "\n", b"line": "\n", b"tab": "\t"}


def rtf_text(raw: bytes) -> str:
    out: list[str] = []
    units: list[int] = []            # UTF-16 units waiting for their pair
    depth, skipped, fallback, pending, i = 0, None, 1, 0, 0

    def put(text: str) -> None:
        if units:
            out.append(struct.pack(f"<{len(units)}H", *units).decode("utf-16-le", "replace"))
            units.clear()
        out.append(text)

    while i < len(raw):
        ch = raw[i:i + 1]
        if ch == b"{":
            depth, i = depth + 1, i + 1
            if skipped is None and _DESTINATION.match(raw, i):
                skipped = depth
        elif ch == b"}":
            if skipped == depth:
                skipped = None
            depth, i = depth - 1, i + 1
            if depth == 0:                       # the document's end; a record can carry bytes past it
                break
        elif ch in b"\r\n":
            i += 1
        elif ch != b"\\":
            if skipped is None and not pending:
                put(ch.decode("cp1252", "replace"))
            pending, i = max(0, pending - 1), i + 1
        elif raw[i + 1:i + 2] == b"'":
            if skipped is None and not pending:
                put(bytes([int(raw[i + 2:i + 4], 16)]).decode("cp1252", "replace"))
            pending, i = max(0, pending - 1), i + 4
        elif (word := _WORD.match(raw, i)) is not None:
            name, number = word.group(1), word.group(2)
            if name == b"uc" and number:
                fallback = int(number)
            elif name == b"u" and number and skipped is None:
                units.append(int(number) & 0xFFFF)
                pending = fallback
            elif name in _BREAKS and skipped is None:
                put(_BREAKS[name])
            i = word.end()
        else:                                    # a control symbol: an escaped character or a break
            symbol = raw[i + 1:i + 2]
            if skipped is None:
                put("\n" if symbol in b"\r\n" else symbol.decode("cp1252") if symbol in b"\\{}" else "")
            i += 2
    put("")
    return "".join(out).strip()
