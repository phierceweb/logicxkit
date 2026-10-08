"""What a plug-in slot's header says the plug-in is, whether or not its state is one read here.

A `UCuA` payload's u16 at +4 is its kind: 1 an instrument or audio effect slot, 2 a MIDI
effect's (keyed under the strip reference, outside the audio slots' keys), 0 a send, 3/4/5/7
properties. A slot then carries, in every record class:

    +120  12 bytes   Logic's short name for the plug-in, NUL-padded ("Klopfgeist", "Q-Sampler")
    +132  4 bytes    the maker, stored reversed like every code here: `GAME` and `MELC` are
                     Logic's own, the second for the plug-ins it names by a four-letter code
                     (the sampler instruments, External Instrument, Auto Sampler, I/O); else
                     an Audio Unit's manufacturer
    +136  u32        Logic's own: a variant word (33 on Echo, which shares type 147 with Tape
                     Delay; 4 on Studio Piano); an Audio Unit: the component type (`aufx`)
    +140  u32        `GAME`: the type id, the word after `GAMETSPP`; `MELC`: the four-letter
                     code (`ANML` Drum Kit Designer); an Audio Unit: the subtype
    +151  bit 0x08   the slot is the channel's instrument (bit 0x10: its window has been open;
                     0x02 on every MIDI effect)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

KIND_AT, SLOT_KIND, MIDI_KIND = 4, 1, 2
NAME_AT, NAME_LEN = 120, 12
MAKER_AT, WORD_AT, CODE_AT = 132, 136, 140
FLAGS_AT, INSTRUMENT_BIT = 151, 0x08
NATIVE, CODED = "EMAG", "CLEM"


@dataclass(frozen=True)
class SlotHeader:
    name: str
    maker: str                 # NATIVE, CODED, or an Audio Unit's manufacturer
    word: int | str            # Logic's own: the variant word; an Audio Unit: its type
    code: int | str            # NATIVE: the type id; CODED and an Audio Unit: four letters
    instrument: bool
    midi: bool = False         # a MIDI effect's slot


def _letters(four: bytes) -> str:
    return four[::-1].decode("latin-1")


def slot_header(payload: bytes) -> SlotHeader | None:
    """The header of a plug-in slot's payload, or None for any other record."""
    if len(payload) <= FLAGS_AT:
        return None
    kind = struct.unpack_from("<H", payload, KIND_AT)[0]
    if kind not in (SLOT_KIND, MIDI_KIND):
        return None
    name = payload[NAME_AT:NAME_AT + NAME_LEN].split(b"\0")[0].decode("latin-1")
    maker = _letters(payload[MAKER_AT:MAKER_AT + 4])
    word, code = payload[WORD_AT:WORD_AT + 4], payload[CODE_AT:CODE_AT + 4]
    own = maker in (NATIVE, CODED)
    return SlotHeader(name, maker,
                      struct.unpack("<I", word)[0] if own else _letters(word),
                      struct.unpack("<I", code)[0] if maker == NATIVE else _letters(code),
                      bool(payload[FLAGS_AT] & INSTRUMENT_BIT), kind == MIDI_KIND)
