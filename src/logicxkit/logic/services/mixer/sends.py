"""Send records — `UCuA` keys 0-2 under a channel's owner, 76-byte payload.

    +0    u32   class word: 72 at `UCuA` v5, the only version on hand
    +4    u32   send slot: 0, 0x10000, 0x20000
    +8    u16   0 or 4 — not decoded
    +16   u8    1 in Post Pan mode (Logic's default), 0 in the other two
    +17   u8    the level's whole 0-127 position (the fixed-point word's own high byte)
    +18   u8    1 in Pre Fader mode; Post Fader is +16 and +18 both 0
    +19   u8    1 when the send is bypassed
    +20   u16   destination: bus number + the project's device input count - 1 (32 inputs:
                46 -> Bus 15, 41 -> Bus 10; a 20-input project writes Bus 10 as 29 — Logic
                rewrote 41 to 29 on re-save, 2026-09-05, and had dropped the channel's plugin
                while the send pointed past its buses). The device count is the channel-count
                record's +36 word; adding `Input` records leaves it, and the words, alone
    +22   u16   4 with Independent Pan on
    +24   u32   the level, 8.24 fixed point on the fader's scale: dB = 40 * log10(v / 90)
                (`levels.position_db`); Logic's send knob reports this word as its value
    +44   16    the send's own instance UUID (v1), distinct on every send
    +60   16    the destination `Bus N` channel's own UUID (`binding.py`)

The channel's own `OCuA` mirrors them: u32 flags at +132, +136, +140 read 1 when send
slot 0, 1, 2 exists (every Logic-written channel on hand).

The mode, bypass and pan bytes are one Logic 12.4 save each on one send (`send-mode-*`,
2026-10-02); the level law is the knob walked over 265 stops.

Measured on 78 sends across three Logic 12.3.1 saves: every bus resolves to a `Bus N`
channel record whose UUID the send repeats at +60. Two Logic re-saves left every send
byte-identical, so nothing here is a per-save nonce. They sit right after the channel's
`OCuA` in key order, before the plugin slots. `sends_write.py` writes them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .binding import channels
from .levels import position_db
from ..stream.stream import HEADER, ProjRecord, project_records
from .mixer import device_inputs

SEND_TAG = b"UCuA"
SEND_KEYS = range(0, 3)
CLASS_AT = 0
SLOT_AT = 4
BUS_AT = 20
BUS_OFFSET = 31                 # for a 32-input project, and for fixtures without inputs
INSTANCE_UUID_AT = 44
DEST_UUID_AT = 60
SEND_FLAG_AT = 132              # in the channel's OCuA, one u32 per send slot
_PAYLOAD = 76


@dataclass(frozen=True)
class Send:
    owner: int
    key: int
    slot: int
    bus: int
    raw: bytes
    level: int = 0                  # the 0-127 position, +17 (a new send is 0)
    level_exact: float = 0.0        # +24 u32, 8.24 fixed point, as the fader's own word
    mode: str = "post pan"
    bypassed: bool = False
    independent_pan: bool = False

    @property
    def level_db(self) -> float | None:
        """The level as Logic shows it; ``None`` is -∞."""
        return position_db(self.level_exact)


POST_PAN_AT, LEVEL_AT, PRE_FADER_AT, BYPASS_AT = 16, 17, 18, 19
OPTIONS_AT, INDEPENDENT_PAN = 22, 4
LEVEL_FIXED_AT = 24
MODES = {"post pan": (1, 0), "post fader": (0, 0), "pre fader": (0, 1)}     # +16, +18


_SEND_MAX = 128                 # every send on hand is 76 bytes; a project whose
                                # plugin slots start at key 2 carries kilobyte slots under those keys


def is_send(record: ProjRecord) -> bool:
    return (record.tag == SEND_TAG and record.key in SEND_KEYS
            and _PAYLOAD <= len(record.raw) - HEADER < _SEND_MAX)


def send_base(data: bytes) -> int:
    """What `+20` holds for Bus 0: the project's device input count less one (a project
    without `Input` channels, a fixture, counts as the 32-input case)."""
    inputs = device_inputs(data)
    if inputs is None:
        inputs = sum(1 for c in channels(data).values() if c.label.startswith("Input ") and "-" not in c.label)
    return inputs - 1 if inputs else BUS_OFFSET


def read_sends(data: bytes) -> dict[int, list[Send]]:
    """owner -> its sends in key order."""
    base = send_base(data)
    out: dict[int, list[Send]] = {}
    for record in project_records(data):
        if not is_send(record):
            continue
        payload = record.raw[HEADER:]
        out.setdefault(record.owner, []).append(Send(
            owner=record.owner, key=record.key,
            slot=struct.unpack_from("<I", payload, SLOT_AT)[0] >> 16,
            bus=struct.unpack_from("<H", payload, BUS_AT)[0] - base,
            raw=record.raw,
            level=payload[LEVEL_AT],
            level_exact=struct.unpack_from("<I", payload, LEVEL_FIXED_AT)[0] / (1 << 24),
            mode=next((m for m, at in MODES.items()
                       if at == (payload[POST_PAN_AT], payload[PRE_FADER_AT])), "post pan"),
            bypassed=payload[BYPASS_AT] == 1,
            independent_pan=bool(
                struct.unpack_from("<H", payload, OPTIONS_AT)[0] & INDEPENDENT_PAN)))
    return out


def bus_owner(data: bytes, bus: int) -> int | None:
    """Owner of the ``Bus N`` channel record, or ``None`` when the project has no such bus."""
    return next((o for o, c in channels(data).items() if c.label == f"Bus {bus}"), None)
