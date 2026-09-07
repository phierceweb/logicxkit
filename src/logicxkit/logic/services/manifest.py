"""One document describing a project's template-level shape: tracks, stacks, channels.

Everything here is read from a decoded field; anything not decoded (send level, input, colour)
is simply absent. It is the artefact the user checks against the mixer, and the input every
apply step diffs against.
"""

from __future__ import annotations

from pathlib import Path

from logicxkit.logicx import project_data

from .binding import bound_objects, channels, input_routing, output_routing
from .chains import channel_references
from .environment import channel_objects
from .insert import channel_formats
from .levels import read_levels
from .project import analyze, project_metadata
from .sends import read_sends
from .stacks import read_stacks, read_tracks


def manifest_from_bytes(data: bytes, *, track_count: int | None = None) -> dict:
    chans = channels(data)
    objs = channel_objects(data)
    objects_of = bound_objects(data)
    routing = output_routing(data)
    inputs = input_routing(data)
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
        dest = routing.get(owner)
        channel_rows.append({
            "owner": owner, "label": c.label,
            "object": objs[objects_of[owner]].name if owner in objects_of else None,
            "ref": refs.get(owner), "width": widths.get(owner),
            "fader": levels.get(owner, {}).get("fader"), "pan": levels.get(owner, {}).get("pan"),
            "stack_index": c.stack_index,
            "output": chans[dest].label if dest is not None else None,
            "input": chans[inputs[owner]].label if inputs.get(owner) is not None else None,
            "sends": [{"slot": s.slot, "bus": s.bus, "to": bus_labels.get(f"Bus {s.bus}")}
                      for s in sends.get(owner, [])],
            "chain": chains.get(c.label, [])})

    return {
        "tracks": tracks,
        "stacks": [{"name": s.name, "index": s.index, "owner": s.owner,
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
