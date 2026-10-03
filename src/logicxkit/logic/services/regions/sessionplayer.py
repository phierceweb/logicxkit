"""Session Player (Drummer) regions, read from Logic's New Session Player SI Track and three
editor moves on a blank-born project (2026-09-13, the public `sessionplayer-*` goldens).

The settings live in a `MneG` record as JSON: `+0` u32 the payload size, `+28` u32 the JSON's
length, the document at `+36`. Its top-level scalars are the editor's settings — `rComp` is the
Complexity slider, `fillsAmount` the Fill Amount knob, `swing` the Swing knob (each moved one
per save), `CharacterIdentifier` the drummer, `Preset.Name` the preset — and `GeneratorMemento`
is the generator's bookkeeping (seeds, the last generate's start and length, parameter
snapshots). The performance itself is the notes in the region's sequence, whose `qeSM` names
the region ("Drummer - Pop Rock"). One region so far: a record is paired with the drummer
sequence in record order.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

from ..song.events import events
from ..stream.stream import HEADER, project_records
from ..stream.sequence import sequences

MEMO_TAG = b"MneG"
JSON_LEN_AT, JSON_AT = 28, 36
NAME_AT = 16
SETTINGS_ROLES = {"rComp": "complexity", "fillsAmount": "fills", "swing": "swing", "fillsComp": "fill_complexity",
                  "humanize": "humanize", "dynamics": "dynamics", "ghostNotes": "ghost_notes", "pushPull": "push_pull"}


@dataclass(frozen=True)
class SessionPlayer:
    region: str                      # the sequence's name
    character: str
    preset: str
    settings: dict                   # the JSON's top-level scalars, Logic's own keys
    memento: dict                    # GeneratorMemento
    notes: int
    generated_bars: int
    events: list = field(default_factory=list, repr=False)

    @property
    def complexity(self) -> float:
        return self.settings.get("rComp")

    @property
    def fills(self) -> float:
        return self.settings.get("fillsAmount")

    @property
    def swing(self) -> float:
        return self.settings.get("swing")


def _documents(records) -> list[dict]:
    out = []
    for r in records:
        if r.tag != MEMO_TAG or len(r.raw) < HEADER + JSON_AT + 2:
            continue
        p = r.raw[HEADER:]
        n = struct.unpack_from("<I", p, JSON_LEN_AT)[0]
        blob = p[JSON_AT:JSON_AT + n]
        if not blob.startswith(b"{"):
            continue
        try:
            doc = json.loads(blob.rstrip(b"\0"))
        except ValueError:
            continue
        if isinstance(doc, dict) and "RegionType" in doc:
            out.append(doc)
    return out


def _drummer_sequences(records) -> list[tuple[str, list]]:
    out = []
    for t in sequences(records):
        q = records[t.start].raw
        n = struct.unpack_from("<H", q, HEADER + NAME_AT)[0]
        name = q[HEADER + NAME_AT + 2:HEADER + NAME_AT + 2 + n].decode("latin-1")
        if name.startswith("Drummer"):
            out.append((name, [e for e in events(records[t.end].raw[HEADER:]) if (e.type & 0xF0) == 0x90]))
    return out


def read_session_players(data: bytes) -> list[SessionPlayer]:
    records = project_records(data)
    docs, seqs = _documents(records), _drummer_sequences(records)
    out = []
    for k, doc in enumerate(docs):
        name, notes = seqs[k] if k < len(seqs) else ("", [])
        memento = doc.get("GeneratorMemento") or {}
        settings = {key: v for key, v in doc.items() if not isinstance(v, (dict, list))}
        out.append(SessionPlayer(name, doc.get("CharacterIdentifier", ""), (doc.get("Preset") or {}).get("Name", ""),
                                 settings, memento, len(notes), int(memento.get("LastGenerateLength", 0)), notes))
    return out
