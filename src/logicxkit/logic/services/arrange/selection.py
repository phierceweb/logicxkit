"""The selected track — Logic keeps it in four places and moves them together.

    karT row   +40 bit 0x20 set, +43 bit 0x40 (0x0c beside it on a row holding a region); +0 bit 0x10000 on an instrument, aux or Sub track's row,
               never an audio track's (every selected row in Logic's saves; other kinds unmeasured)
    ivnE       +80 = 1 on the object, 0 on every other channel object
    gnoS       +94 the object id; +210 and +214 the row's 1-based position

Measured on Logic's adds (02 -> 03, 08 -> 09) and its drag (06 -> 07): the previous holder
is cleared each time. Every writer that adds or moves a row ends by selecting it. Logic 13.0's add
writes the same four (`undo-a02-create-track-13-0-logic`, `regions-d03-add-track-13-0-logic`) and
leaves the previous row's +43 0x40 where an edit set it; `select_rows` clears that bit alone. A 13.0 re-save with
no edit clears every +43 mark and keeps +40's bit (`regions-d04-split-ours-resave-13-0-logic`).
"""

from __future__ import annotations

from ..mixer.binding import bound_channels, channels
from .environment import object_id_of, set_selected_object
from ..stream.stream import HEADER, project_records, reassemble
from ..stream.recbuild import rec
from ..stream.registry import GNOS_TAG, set_selection
from .tracklist import arrange_run, row_position, select_rows

FLAGGED = ("Inst ", "Aux ", "Sub ")       # the channel kinds whose selected row takes SELECTED_FLAG


def select_track(data: bytes, object_id: int, track_count: int | None = None) -> bytes:
    """``data`` with track object ``object_id`` selected everywhere Logic records it."""
    records = project_records(data)
    run = arrange_run(records, track_count)
    pos = row_position(records, run, object_id)
    if pos is None:
        raise ValueError(f"track object {object_id} is not in the arrange list")
    chan = channels(data).get(bound_channels(data).get(object_id))
    rows = select_rows([records[i].raw for i in run], object_id, None if chan is None else chan.label.startswith(FLAGGED))
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
