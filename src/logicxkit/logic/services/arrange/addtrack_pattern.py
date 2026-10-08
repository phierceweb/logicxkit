"""What a track add clones its structures from: the pattern track of the kind, one with a sound
index-table entry, and the mixer-order row the new row follows."""

from __future__ import annotations

from ..mixer.channel_alloc import (
    channel_run_end, default_inst_records, is_mixer_record, is_unused_stub, mixer_record, new_audio_channel,
    new_aux_channel, new_inst_channel, project_words,
)
from ..mixer.slots import property_key_base, slot_index_base
from ..stream.stream import HEADER
from .tracklist import row_object, row_position


def _pattern(objs: dict, chans: dict, owners_of: dict, prefix: str, by_owner: bool = False) -> tuple[int, int]:
    """The track to clone the structures from -> ``(object id, owner)``: the highest object
    id of the kind, or with ``by_owner`` the one on the highest-numbered strip (an inserted
    channel goes right after that strip)."""
    same_kind = [oid for oid, own in owners_of.items()
                 if chans[own].label.startswith(prefix) and oid in objs]
    if not same_kind:
        raise ValueError(f"no {prefix.strip().lower()} track to clone the structures from")
    like = max(same_kind, key=(lambda oid: owners_of[oid]) if by_owner else (lambda oid: oid))
    return like, owners_of[like]


def _sound_entry(records, table: bytes, seqs, oid: int) -> bool:
    """Whether ``oid``'s index-table entry leads to a track triple that carries ``oid`` —
    Logic's own files keep a few stale entries whose triple is a group's carrying object 0,
    and a track cloned from one of those reads back as a group."""
    import struct
    from ..stream.sequence import QESM_OBJECT_AT, is_group, table_entry, triple_by_slot
    found = table_entry(table, oid)
    if found is None:
        return False
    t = triple_by_slot(seqs, found[1])
    if t is None:
        return False
    q = records[t.start].raw
    if is_group(q) or len(q) < HEADER + QESM_OBJECT_AT + 2:
        return False
    return struct.unpack_from("<H", q, HEADER + QESM_OBJECT_AT)[0] == oid


def _with_table_entry(records, objs: dict, owners_of: dict, chans: dict, prefix: str, like: int) -> int:
    """``like`` if it has a sound index-table entry, else the highest same-kind object that
    has one, else any track object with one — the entry and triple are cloned from it."""
    from ..stream.sequence import index_table, sequences
    table = records[index_table(records)].raw[HEADER:]
    seqs = sequences(records)
    if _sound_entry(records, table, seqs, like):
        return like
    same_kind = sorted((oid for oid, own in owners_of.items()
                        if oid in objs and chans[own].label.startswith(prefix)), reverse=True)
    for oid in same_kind:
        if _sound_entry(records, table, seqs, oid):
            return oid
    for oid in sorted(objs, reverse=True):
        if _sound_entry(records, table, seqs, oid):
            return oid
    raise ValueError("no track object with an index-table entry to clone")


def _by_label(chans: dict, label: str):
    return next((c for c in chans.values() if c.label == label), None)


def fresh_audio_owner(chans: dict, objs: dict, owners_of: dict) -> int:
    """Where Logic's New Audio Track inserts a fresh strip: at the first stub no track has used,
    so later adds follow earlier ones (`tracks-two-audio-logic`, `upgraded-three-audio-logic`,
    `stackid-s1-logic`, `gone-i2-logic`); with none, before the Preview strip, the last `Audio`
    strip of every Logic save on hand; else after the last `Audio`."""
    audio = sorted(o for o, c in chans.items() if c.label.startswith("Audio "))
    unused = [o for o in audio if is_unused_stub(chans[o])]
    if unused:
        return unused[0]
    preview = next((owners_of.get(i) for i, o in objs.items() if o.name == "Preview"), None)
    return audio[-1] if preview == audio[-1] else audio[-1] + 1


def _flat_anchor(records, flat: list[int], *, owner: int, prefix: str, owners_of: dict,
                 chans: dict, like: int | None) -> int:
    """Position in the flat list after which the new row goes: the last row of the same
    strip type with a lower owner, else the pattern's; with no pattern (a session's first aux)
    the last instrument or audio row, where Logic's own first aux went."""
    below, sources = [], []
    for k, i in enumerate(flat):
        own = owners_of.get(row_object(records[i].raw))
        if own is not None and own < owner and chans[own].label.startswith(prefix):
            below.append(k)
        if own is not None and chans[own].label.startswith(("Audio ", "Inst ")):
            sources.append(k)
    if below:
        return max(below)
    return row_position(records, flat, like) if like is not None else max(sources)


def channel_records_for(data: bytes, records, *, kind: str, created_audio: bool, bound_aux: bool, chans: dict,
                        owner: int, prefix: str, obj_uuid: bytes, output_uuid: bytes | None, source, stereo: bool,
                        stack_index: int, like_owner: int | None) -> tuple[list[bytes], int | None, int | None]:
    """The new channel's records when the add makes a channel (a fresh audio strip, an instrument
    channel with its default slots, an unbound aux) -> ``(records, strip number, the record index
    they go after)``; nothing when the add binds an existing strip."""
    inst_records: list[bytes] = []
    number = None
    creating = kind == "instrument" or created_audio or (kind == "aux" and not bound_aux)
    last_like_record = None
    if creating:
        # the fresh record takes `owner` and every channel from it moves up one, so it goes after
        # the highest owner below it, or before the first channel: Logic keeps them in owner order
        below = [r.owner for r in records if is_mixer_record(r) and r.owner < owner]
        last_like_record = (channel_run_end(records, max(below)) if below
                            else next(i for i, r in enumerate(records) if is_mixer_record(r)) - 1)
    if created_audio:
        number = 1 + sum(1 for o, c in chans.items() if c.label.startswith(prefix) and o < owner)
        inst_records = [new_audio_channel(number=number, owner=owner, object_uuid=obj_uuid,
                                          output_uuid=output_uuid, input_uuid=source.uuid,
                                          words=project_words(data), stereo=stereo,
                                          stack_index=stack_index)]
    elif kind == "instrument":
        chan_rec, number = new_inst_channel(mixer_record(records, like_owner), owner=owner,
                                            object_uuid=obj_uuid, output_uuid=output_uuid,
                                            stack_index=stack_index, stereo=stereo)
        inst_records = [chan_rec] + default_inst_records(owner, slot_base=slot_index_base(data),
                                                          property_base=property_key_base(data),
                                                          stereo=stereo)
    elif kind == "aux" and not bound_aux:
        highest = max(int(c.label.split(" ", 1)[1]) for c in chans.values() if c.label.startswith(prefix))
        inst_records = [new_aux_channel(number=highest, owner=owner, object_uuid=obj_uuid,
                                        output_uuid=output_uuid,
                                        input_uuid=source.uuid if source else None,
                                        words=project_words(data), stack_index=stack_index)]
        number = highest + 1
    return inst_records, number, last_like_record
