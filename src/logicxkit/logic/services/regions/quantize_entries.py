"""The song container's side of a drum quantize (`quantize_drums`): free table slots and sequence
ids for the RBA triples, the reference region that lends its hit blocks, and the container with each
planned entry's marker blocks replaced."""

from __future__ import annotations

from .audio_regions import AudioRegion
from .quantize_range import has_hits
from .regions import TAIL, blocks_of, entry_offsets
from ..midi.midi import REGION_BAR_ONE
from ..song.events import BAR_ONE
from ..stream.sequence import SLOT_STEP, TABLE_FIRST_SLOT, index_table, sequences, table_entries
from ..stream.stream import HEADER

_MAX_ID = 512


def _free(records, n: int) -> tuple[list[int], list[int]]:
    """``n`` free table slots and ``n`` free sequence ids."""
    seqs = sequences(records)
    table = records[index_table(records)].raw[HEADER:]
    used_slots = {slot for _at, _oid, _index, slot in table_entries(table)} | {t.slot for t in seqs}
    used_ids = {t.seq_id for t in seqs}
    slots, ids, slot = [], [], TABLE_FIRST_SLOT
    while len(slots) < n:
        if slot not in used_slots:
            slots.append(slot)
        slot += SLOT_STEP
    for i in range(1, _MAX_ID):
        if i not in used_ids:
            ids.append(i)
            if len(ids) == n:
                break
    return slots, ids


def _aligned(a: AudioRegion, b: AudioRegion) -> bool:
    """Two regions whose marker sources mean the same samples: the same start, first frame and length."""
    return (a.start, a.offset, a.frames) == (b.start, b.offset, b.frames)


def _lender(regions: list[AudioRegion], ref_ids: list[int], entries: dict, payload: bytes) -> tuple[AudioRegion, list[bytes]] | None:
    """The first reference region carrying hit blocks, with them: what a member listing only
    anchors takes as its own (Logic's first quantize writes the hits there alone)."""
    for region in regions:
        at = entries.get((region.object_id, region.start - BAR_ONE + REGION_BAR_ONE))
        if region.object_id in ref_ids and at is not None:
            blocks = blocks_of(payload, at[0])
            if has_hits(blocks):
                return region, blocks
    return None


def _with_markers(payload: bytes, plans: dict[int, bytes]) -> bytes:
    """The container with each planned entry (by offset) and its marker blocks replaced by the
    plan's bytes; other entries keep theirs."""
    body, tail = payload[:len(payload) - TAIL], payload[len(payload) - TAIL:]
    offsets = entry_offsets(payload)
    out = bytearray()
    for k, off in enumerate(offsets):
        end = offsets[k + 1] if k + 1 < len(offsets) else len(body)
        out += plans.get(off, body[off:end])
    return bytes(out) + tail
