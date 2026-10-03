"""One document describing a project's template-level shape: tracks, stacks, channels.

Everything here is read from a decoded field; anything not decoded (send level, input, colour)
is simply absent. It is the artefact the user checks against the mixer, and the input every
apply step diffs against.
"""

from __future__ import annotations

from pathlib import Path

from logicxkit.logicx import project_data

from ..mixer.binding import bound_objects, channels, input_labels, output_labels
from ..mixer.chains import channel_references
from ..arrange.environment import channel_objects
from ..mixer.mixer import channel_formats
from ..mixer.levels import read_levels, shown_db
from .project import analyze, project_metadata
from ..mixer.sends import read_sends
from ..arrange.stacks import read_stacks, read_tracks


def _rounded(db: float | None) -> float | None:
    """A level to the hundredth; ``None`` is -∞."""
    return None if db is None else round(db, 2) + 0.0


def manifest_from_bytes(data: bytes, *, track_count: int | None = None) -> dict:
    chans = channels(data)
    objs = channel_objects(data)
    objects_of = bound_objects(data)
    routing = output_labels(data)
    inputs = input_labels(data)
    refs = channel_references(data)
    widths = channel_formats(data)
    levels = read_levels(data)
    sends = read_sends(data)
    chains = {c["label"]: c["chain"] for c in analyze(data)["channels"]}
    bus_labels = {c.label: c.label for c in chans.values() if c.label.startswith("Bus ")}

    stacks = read_stacks(data, track_count)
    stack_of = {key: s.name for s in stacks for key, _name in s.members}
    tracks = [{"key": r["key"], "name": r["name"], "hidden": r["hidden"], "colour": r["colour"],
               "object_id": r["object_id"], "owner": r["owner"], "label": r["label"],
               "stack": stack_of.get(r["key"]), "stack_index": r["stack_index"]}
              for r in read_tracks(data, track_count)]

    channel_rows = []
    for owner in sorted(chans):
        c = chans[owner]
        if not c.in_use:
            continue
        channel_rows.append({
            "owner": owner, "label": c.label,
            "object": objs[objects_of[owner]].name if owner in objects_of else None,
            "ref": refs.get(owner), "width": widths.get(owner),
            "fader": levels.get(owner, {}).get("fader"), "pan": levels.get(owner, {}).get("pan"),
            "fader_db": _rounded(levels.get(owner, {}).get("fader_db")),
            "stack_index": c.stack_index,
            "output": routing.get(owner), "input": inputs.get(owner),
            "routing_read": owner in routing and owner in inputs,
            "sends": [{"slot": s.slot, "bus": s.bus, "to": bus_labels.get(f"Bus {s.bus}"),
                       "level_db": _rounded(s.level_db), "level_shown": shown_db(s.level_exact),
                       "mode": s.mode, "bypassed": s.bypassed}
                      for s in sends.get(owner, [])],
            "chain": chains.get(c.label, [])})

    return {
        "tracks": tracks,
        "stacks": [{"name": s.name, "index": s.index, "owner": s.owner, "kind": s.kind, "strip": s.strip,
                    "fader": levels.get(s.owner, {}).get("fader"),
                    "members": [n for _k, n in s.members]} for s in stacks],
        "channels": channel_rows,
    }


def read_manifest(logicx: Path) -> dict:
    logicx = Path(logicx)
    metadata = project_metadata(logicx)
    out = manifest_from_bytes(project_data(logicx), track_count=metadata.get("tracks"))
    out["name"] = logicx.stem
    out["metadata"] = metadata
    return out
