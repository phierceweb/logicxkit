"""Neural DSP plugin-state decode (read-only).

Logic embeds 3rd-party AU state as XML plists inside the binary, identically in ``.cst``
files and ``.logicx`` ``ProjectData`` — so both file kinds read the same way.
"""

from __future__ import annotations

from pathlib import Path

from logicxkit.au.services.embed import find_au_plists
from logicxkit.au.services.juce import state_from_plist
from logicxkit.logicx import read_states

NDSP = 0x4E445350  # AU manufacturer fourcc 'NDSP'


def neural_states(data: bytes) -> list[dict]:
    """All decodable Neural DSP ('NDSP') plugin states found in raw bytes."""
    out = []
    for off, pl in find_au_plists(data):
        if pl.get("manufacturer") != NDSP:
            continue
        decoded = state_from_plist(pl)
        if decoded is not None:
            out.append({"offset": off, **decoded})
    return out


def read_neural(path: str | Path) -> list[dict]:
    """Neural states from a flat file (.cst/.pst) or a .logicx bundle.

    For bundles, each state is attributed to its mixer channel (``channel`` key,
    None when the state sits outside any recognized OCuA channel block).
    """
    return read_states(path, neural_states)
