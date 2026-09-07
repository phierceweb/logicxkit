"""The selected track — Logic keeps it in four places and moves them together.

    karT row   +40 bit 0x20 set, +43 = 0x40; +0 bit 0x10000 on an instrument row
    ivnE       +80 = 1 on the object, 0 on every other channel object
    gnoS       +94 the object id; +210 and +214 the row's 1-based position

Measured on Logic's adds (02 -> 03, 08 -> 09) and its drag (06 -> 07): the previous holder
is cleared each time. Every writer that adds or moves a row ends by selecting it.
"""

from __future__ import annotations

from .environment import object_id_of, set_selected_object
from .insert import HEADER, project_records, reassemble
from .recbuild import rec
from .registry import GNOS_TAG, set_selection
from .tracklist import arrange_run, row_position, select_rows


def select_track(data: bytes, object_id: int, track_count: int | None = None) -> bytes:
    """``data`` with track object ``object_id`` selected everywhere Logic records it."""
    records = project_records(data)
    run = arrange_run(records, track_count)
    pos = row_position(records, run, object_id)
    if pos is None:
        raise ValueError(f"track object {object_id} is not in the arrange list")
    rows = select_rows([records[i].raw for i in run], object_id)
    replace = dict(zip(run, rows, strict=True))
    out = []
    for i, r in enumerate(records):
        raw = replace.get(i, r.raw)
        if object_id_of(r) is not None:
            raw = set_selected_object(raw, object_id_of(r) == object_id)
        elif r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, set_selection(raw[HEADER:], object_id=object_id,
                                                   track_number=pos + 1))
        out.append(raw)
    return reassemble(data, out)
