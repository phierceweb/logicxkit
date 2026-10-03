"""The channel object's flex fields (measured on a drum take, 2026-09-13).

`ivnE +154`, the kind byte: bit 4 set = **Q-Reference off**, bit 5 set = a flex mode other
than Slicing. Three bytes at the padded name's end + 242 hold the **flex mode**: `02 03 02`
Slicing, `05 00 05` Monophonic; the other modes are unmeasured.
"""

from __future__ import annotations

from ..arrange.environment import KIND_AT, name_end
from ..stream.stream import HEADER

Q_OFF_BIT, OTHER_MODE_BIT = 0x10, 0x20
FLEX_MODE_AFTER_NAME = 242
MODES = {"Slicing": (2, 3, 2), "Monophonic": (5, 0, 5)}
_BY_BYTES = {v: k for k, v in MODES.items()}


def q_reference(raw: bytes) -> bool:
    return not raw[HEADER + KIND_AT] & Q_OFF_BIT


def set_q_reference(raw: bytes, on: bool) -> bytes:
    buf = bytearray(raw)
    buf[HEADER + KIND_AT] = (buf[HEADER + KIND_AT] & ~Q_OFF_BIT) | (0 if on else Q_OFF_BIT)
    return bytes(buf)


def _mode_at(raw: bytes) -> int:
    return HEADER + name_end(raw[HEADER:]) + FLEX_MODE_AFTER_NAME


def flex_mode(raw: bytes) -> str | None:
    """"Slicing", "Monophonic", or None when the bytes are neither (unset, or a mode not
    measured)."""
    at = _mode_at(raw)
    return _BY_BYTES.get(tuple(raw[at:at + 3]))


def set_flex_mode(raw: bytes, mode: str) -> bytes:
    if mode not in MODES:
        raise ValueError(f"flex mode {mode!r}: this writes {' or '.join(MODES)}")
    buf = bytearray(raw)
    at = _mode_at(raw)
    buf[at:at + 3] = bytes(MODES[mode])
    kind = buf[HEADER + KIND_AT] & ~OTHER_MODE_BIT
    buf[HEADER + KIND_AT] = kind | (0 if mode == "Slicing" else OTHER_MODE_BIT)
    return bytes(buf)
