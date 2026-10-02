"""Add a track the way Logic does — measured on two clean save pairs, 2026-09-01, and confirmed
in Logic for both kinds.

For one new track placed after a reference row, Logic writes:

* one `ivnE` object cloned in shape from the highest-id track of the same kind, appended
  after the last object — `environment.clone_object`
* one arrange `karT` row after the reference's and one row in the flat mixer-order list,
  keys renumbered — `tracklist`
* one sequence triple in slot order and an index-table entry, every later entry's index
  moved up — `sequence.plan_sequence`
* the channel: an audio track binds a free `Audio N` stub, or with none free (or on request)
  gets a fresh channel after the last `Audio`, as Logic does; an instrument or aux track gets
  a new channel record; every insert shifts every later owner, and every object bound above
  it — `channel_alloc`. A track placed after a row inside a stack joins that stack, and
  inside a summing stack outputs to its bus (`stack_place`).
* the `gnoS` registry entries — `registry.register_object`
* the selection, moved onto the new track — `selection.select_track`

`NumberOfTracks` in MetaData.plist is the caller's job.
"""

from __future__ import annotations

import re

from .binding import bound_channels, channels
from .channel_alloc import (
    BARE_STUB, COUNT_CLASS_AT, bind_audio_stub, new_audio_channel, new_aux_channel,
    bump_channel_count, channel_run_end, default_inst_records, free_audio_stub, is_channel_record,
    is_mixer_record, mixer_record, new_inst_channel, project_words, require_packaged_class,
    shifted_channel,
)
from .mixer import is_channel_count
from .environment import (
    DEFAULT_COLOUR,
    DEFAULT_ICON,
    ENV_TAG,
    UUID_LEN,
    channel_objects,
    clone_object,
    next_object_id,
    object_id_of,
    object_record,
    object_stamp,
    shifted_object,
)
from .add_plugin import show_slots, shown_slots
from .slots import slot_index_base
from .stream import HEADER, project_records, reassemble
from .keyflags import sync_key_flags
from .recbuild import fresh_uuid, rec
from .registry import GNOS_TAG, register_object
from .regions import sync_region_tracks, sync_row_count
from .selection import select_track
from .sequence import QESM_FRESH, plan_sequence
from .slots import property_key_base
from .stack_create import packaged_aux
from .tracklist import (
    MEMBER_AT,
    ROW_TYPE,
    arrange_run,
    clone_flat_row,
    flat_run,
    new_row,
    renumbered,
    row_object,
    row_position,
)
from .validate import require_full_walk, require_valid

_PREFIX = {"audio": "Audio ", "instrument": "Inst ", "aux": "Aux "}
AUX_ICON, AUX_COLOUR = 0x1224, 5
AUX_FRESH_WORD, AUX_KIND_BYTE = 360, 5


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
    from .sequence import QESM_OBJECT_AT, is_group, table_entry, triple_by_slot
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
    from .sequence import index_table, sequences
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


def add_track(data: bytes, *, name: str, after: int, kind: str = "audio", input_number: int = 1,
              stereo: bool = False, track_count: int | None = None,
              colour: int | None = None, member: bool | None = None,
              new_channel: bool = False, pattern_object: bytes | None = None) -> tuple[bytes, dict]:
    """A new ``kind`` track — audio, instrument or aux — named ``name``, its arrange row right
    after track object ``after`` (inside that row's stack when it has one).

    ``colour`` defaults to Logic's: 16 on an audio track, 5 on an aux, the pattern's on an
    instrument. ``member`` puts the row inside the stack ``after`` belongs to or heads (True),
    at the top level (False), or wherever ``after`` sits (None). ``new_channel`` makes an audio
    track a fresh channel even while a stub is free. ``pattern_object`` is cloned in place of
    the session's own track of the kind."""
    if kind not in _PREFIX:
        raise ValueError("kind is 'audio', 'instrument' or 'aux'")
    require_full_walk(data)
    records = project_records(data)
    objs = channel_objects(data)
    if after not in objs:
        raise ValueError(f"no track object {after}")
    chans = channels(data)
    require_packaged_class(chans, kind)
    owners_of = bound_channels(data)
    prefix = _PREFIX[kind]
    packaged = None
    try:
        like, like_owner = _pattern(objs, chans, owners_of, prefix, by_owner=kind == "aux")
    except ValueError:
        if kind != "aux":
            raise
        like, like_owner, packaged = max(objs), None, packaged_aux(records)
    like = _with_table_entry(records, objs, owners_of, chans, prefix, like)
    object_id = next_object_id(records)
    top = max(objs)
    stereo_out = _by_label(chans, "Output 1-2")
    output_uuid = stereo_out.uuid if stereo_out is not None else None
    created_audio = False
    if kind == "audio":
        try:
            owner = None if new_channel else free_audio_stub(chans)
        except ValueError:
            owner = None
        if owner is None:                                 # where Logic puts a fresh one: at the
            audio = sorted(o for o, c in chans.items() if c.label.startswith(prefix))
            bare = [o for o in audio if chans[o].size <= BARE_STUB]   # first bare stub, else the end
            owner = bare[0] if bare else audio[-1] + 1
            created_audio = True
        if stereo:                                        # a stereo track takes the pair channel, Input N-(N+1)
            if input_number % 2 == 0:
                raise ValueError(f"a stereo input pair starts on an odd input, not Input {input_number}")
            label = f"Input {input_number}-{input_number + 1}"
        else:
            label = f"Input {input_number}"
        source = _by_label(chans, label)
        if source is None:
            raise ValueError(f"no {label} channel")
    elif kind == "aux":
        owner = max(o for o, c in chans.items() if c.label.startswith(prefix)) + 1
        source = _by_label(chans, "Input 1-2")
    else:
        owner = like_owner + 1                            # inserted right after the pattern channel
        source = None

    run = arrange_run(records, track_count)
    plan = plan_sequence(records, like=like, object_id=object_id,
                         fresh_word=AUX_FRESH_WORD if kind == "aux" else QESM_FRESH,
                         kind_byte=AUX_KIND_BYTE if kind == "aux" else None)

    pattern_obj = pattern_object or (packaged["object"] if packaged else object_record(records, like))
    pattern_stamp = object_stamp(pattern_obj)
    named = not re.fullmatch(r"(Audio|Inst|Aux) \d+", name)
    if kind == "audio":
        new_obj = clone_object(pattern_obj, object_id=object_id, name=name, owner=owner,
                               colour=DEFAULT_COLOUR if colour is None else colour, icon=DEFAULT_ICON,
                               named=named)
    elif kind == "aux":
        new_obj = clone_object(pattern_obj, object_id=object_id, name=name, owner=owner,
                               colour=AUX_COLOUR if colour is None else colour, icon=AUX_ICON,
                               fresh_step=None, named=named)
    else:
        new_obj = clone_object(pattern_obj, object_id=object_id, name=name, owner=owner,
                               colour=colour, icon=None, named=named)
    obj_uuid = new_obj[-UUID_LEN:]
    last_env = max(i for i, r in enumerate(records) if r.tag == ENV_TAG)
    ref_pos, like_pos = row_position(records, run, after), row_position(records, run, like)
    if like_pos is None:                                  # the pattern strip has no arrange row
        like_pos = next((k for k in range(len(run) - 1, -1, -1)
                         if row_object(records[run[k]].raw) in owners_of
                         and chans[owners_of[row_object(records[run[k]].raw)]].label.startswith(prefix)),
                        ref_pos)                          # no row of the kind at all: the anchor's shape
    ref_row = records[run[ref_pos]].raw
    ref_owner = owners_of.get(after)
    ref_label = chans[ref_owner].label if ref_owner in chans else ""
    ref_depth = ref_row[HEADER + MEMBER_AT]               # the byte is the nesting depth
    if member is None:
        depth = ref_depth                                 # the anchor's sibling
    elif not member:
        depth = 0
    elif ref_label.startswith("Sub "):
        depth = ref_depth + 1                             # under the header itself
    else:
        depth = ref_depth                                 # beside the anchor, inside its stack
    if depth == 0:
        stack_index = 0
    elif depth == ref_depth + 1:
        stack_index = int(ref_label[4:])
    else:
        stack_index = chans[ref_owner].stack_index if ref_owner in chans else 0
    member = depth
    if depth <= ref_depth:                                # beside the anchor: after everything it holds
        from .stacks import span_end
        ref_pos = span_end([records[i].raw[HEADER + MEMBER_AT] for i in run], ref_pos) - 1
    arrange_row = new_row(packaged["row"] if packaged else records[run[like_pos]].raw,
                          object_id=object_id, member=member,
                          row_type=ROW_TYPE.get(kind, ROW_TYPE["audio"]))
    flat = flat_run(records, run)
    flat_pos = _flat_anchor(records, flat, owner=owner, prefix=prefix, owners_of=owners_of,
                            chans=chans, like=None if packaged else like)
    flat_row = clone_flat_row(packaged["flat_row"] if packaged else records[flat[flat_pos]].raw, object_id)

    # the fresh record takes `owner` and every channel from it moves up one, so it goes after
    # the highest owner below it: Logic keeps the channel records in owner order
    anchor_owner = max(r.owner for r in records if is_mixer_record(r) and r.owner < owner)
    last_like_record = channel_run_end(records, anchor_owner)
    inst_records: list[bytes] = []
    number = None
    creating = kind != "audio" or created_audio
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
    elif kind == "aux":
        highest = max(int(c.label.split(" ", 1)[1]) for c in chans.values() if c.label.startswith(prefix))
        inst_records = [new_aux_channel(number=highest, owner=owner, object_uuid=obj_uuid,
                                        output_uuid=output_uuid,
                                        input_uuid=source.uuid if source else None,
                                        words=project_words(data), stack_index=stack_index)]
        number = highest + 1
    gnos_uuid = fresh_uuid()

    out: list[bytes] = []
    for i, r in enumerate(records):
        raw = plan.rewrite(i, r)
        oid = object_id_of(r)
        if kind == "audio" and not created_audio and is_mixer_record(r) and r.owner == owner:
            raw = bind_audio_stub(raw, object_uuid=obj_uuid, input_uuid=source.uuid,
                                  output_uuid=output_uuid, stereo=stereo, stack_index=stack_index)
        elif creating and is_channel_record(r) and r.owner >= owner:
            raw = shifted_channel(raw, r, relabel_prefix=prefix)
        elif creating and is_channel_count(r):
            raw = bump_channel_count(raw, class_at=COUNT_CLASS_AT[{"instrument": "Inst", "aux": "Aux", "audio": "Audio"}[kind]])
        elif creating and oid is not None:
            bound = owners_of.get(oid)
            raw = shifted_object(raw, channel=bound is not None and bound >= owner,
                                 stamp=object_stamp(raw) > pattern_stamp)
        elif r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, register_object(raw[HEADER:], object_id=object_id, top=top,
                                                     uuid=gnos_uuid, slot=plan.slot))
        out.append(raw)
        if i == run[ref_pos]:
            out.append(arrange_row)
        if i == flat[flat_pos]:
            out.append(flat_row)
        if i == plan.insert_after:
            out += plan.new
        if i == last_env:
            out.append(new_obj)
        if i == last_like_record and inst_records:
            out += inst_records

    result = reassemble(data, out)
    result = reassemble(result, renumbered(project_records(result)))
    result = sync_key_flags(result)                  # a cloned channel carries its pattern's flags
    # a fresh channel record carries its template's shown-slot count; one value serves the
    # project, and Logic drops chains past a smaller one on load
    result = show_slots(result, shown_slots(result))
    result = sync_row_count(result, None if track_count is None else track_count + 1)
    result = sync_region_tracks(result, None if track_count is None else track_count + 1)
    from .route_words import with_words
    from .stack_place import to_summing_bus
    from .stacks import read_stacks, read_tracks, summing_around
    count = None if track_count is None else track_count + 1
    result = with_words(select_track(result, object_id, count), [owner])
    key = next(r["key"] for r in read_tracks(result, count) if r["object_id"] == object_id)
    around = summing_around(read_stacks(result, count), key)
    if around is not None:
        result = to_summing_bus(result, {object_id: around})
    require_valid(result)
    label = chans[owner].label if kind == "audio" else f"{prefix}{number}"
    return result, {"object_id": object_id, "owner": owner, "label": label,
                    "sequence": plan.index, "slot": plan.slot,
                    "input": source.label if source else None}


def add_audio_track(data: bytes, **kw) -> tuple[bytes, dict]:
    return add_track(data, kind="audio", **kw)
