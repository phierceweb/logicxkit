"""`logic automation` — each track's automation lanes and points; `--set`, `--copy` and `--clear`
write a lane onto a copy, applied in command-line order."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from ..au.services.tables import load_table
from ._automation_list import list_lanes
from ._edit import CommandError, edit_copy, object_by_name
from .services.regions.automation_write import clear_lane, copy_lane, set_lane, set_param_lane
from .services.arrange.groups import FADER_IDS
from .services.arrange.retrack import find_project
from .services.song.signature import meter


LANES = {**{k.lower(): (v, False) for k, v in FADER_IDS.items()},
         "±volume": (FADER_IDS["Volume"], True), "volume±": (FADER_IDS["Volume"], True),
         "relative volume": (FADER_IDS["Volume"], True), "volume (relative)": (FADER_IDS["Volume"], True)}


class _Edit(argparse.Action):
    """Every write flag lands in one list, in the order typed."""

    def __call__(self, parser, namespace, values, option_string=None):
        edits = getattr(namespace, "edits", None) or []
        edits.append((option_string.lstrip("-"), values))
        namespace.edits = edits


def _lane(text: str) -> tuple[int, bool]:
    lane = LANES.get(text.strip().lower())
    if lane is None:
        raise CommandError(f"no lane {text.strip()!r}; one of Volume, Pan, Mute, Solo or ±Volume")
    return lane


PARAM_LANE = re.compile(r"slot\s+(\d+)\s+(.+)", re.I)     # "slot 1 Threshold": a plug-in parameter lane


def _param_lane(text: str) -> tuple[int, str] | None:
    hit = PARAM_LANE.fullmatch(text.strip())
    return (int(hit.group(1)), hit.group(2).strip()) if hit else None


def _param_points(text: str, bars) -> list[tuple[int, float | bool]]:
    """``-24@1,on@5`` -> [(tick, value)]: the parameter's own unit, or on/off for a switch."""
    out = []
    for item in text.split(","):
        value, _, bar = item.strip().partition("@")
        if not bar:
            raise CommandError(f"a point is VALUE@BAR, not {item.strip()!r}")
        try:
            v = {"on": True, "off": False}.get(value.strip().lower(), None)
            number, at = (float(value) if v is None else 0.0), float(bar)
        except ValueError:
            raise CommandError(f"a point is VALUE@BAR with a number (or on/off) and a bar, not {item.strip()!r}") from None
        if not (math.isfinite(number) and math.isfinite(at)):
            raise CommandError(f"a point is VALUE@BAR with finite numbers, not {item.strip()!r}")
        out.append((bars.tick(at), number if v is None else v))
    return out


def _param_target(data: bytes, obj: int, track: str, slot: int, name: str):
    """The lane index of parameter ``name`` on insert ``slot`` of the channel track object
    ``obj`` is bound to, and a converter from its own value to a 0..1 point -> (plug-in, index,
    convert(value) -> (point, note)). The slot is the mixer's, empty slots counted — the insert
    number the lane carries."""
    from .services.mixer.binding import bound_channels
    from .services.stream.stream import HEADER
    from .services.mixer.plugin_params import load_tables, table_for
    from .services.mixer.plugins import plugin_identity
    from .services.mixer.slot_width import plugin_variant
    from .services.mixer.transplant import channel_slots, slot_at, slot_position
    from .services.translate.translate import load_maps, map_for
    owner = bound_channels(data).get(obj)
    if owner is None:
        raise CommandError(f"{track}: the track is bound to no mixer channel")
    record = slot_at(data, owner, slot)
    if record is None:
        held = ", ".join(str(slot_position(data, r)) for r in channel_slots(data, owner)) or "none"
        raise CommandError(f"{track}: slot {slot} holds no plug-in (plug-ins in slot(s) {held})")
    payload = record.raw[HEADER:]
    identity = plugin_identity(payload)
    if identity and identity[0] == "native":
        from .services.mixer.slider import point_for, slider_by_name
        table = table_for(load_tables(), identity[1], plugin_variant(payload))
        m = map_for(payload, load_maps())
        param = next((p for p in (table.params if table else []) if p.name.lower() == name.lower()), None)
        if table is None or param is None:
            raise CommandError(f"{track} slot {slot}: no measured parameter {name!r}" + (f" on {table.name}" if table else ""))
        if m is None:
            raise CommandError(f"{track} slot {slot}: {table.name} has no map, so its sliders are unmeasured for automation")

        switch = tuple(param.choices) == ("Off", "On") or any(i.switch and i.param == param.name for i in m.items.values())

        def native(value):
            if isinstance(value, bool) and not switch:
                raise CommandError(f"{name} takes a number, not on/off; {table.name}'s {param.name} is not a switch")
            point, units, landed, sampled = point_for(m, param.name, value)
            held = ""
            if not isinstance(value, bool):
                ends = [v for _u, v in slider_by_name(m, param.name)[2]]
                if not min(ends) <= value <= max(ends):
                    held = f"; the slider runs {min(ends):g}..{max(ends):g}"
            return point, f"{landed:g} (unit {units:g}{'' if sampled else ', between sampled positions'}{held})"
        return table.name, param.index - 1, native
    if identity and identity[0] == "au":
        from .services.translate.automation_remap import item_raw
        _t, subtype, manu = identity[1:]
        entries = (load_table(manu, subtype) or {}).get("params", [])
        entry = next((e for e in entries if str(e.get("name", "")).lower() == name.lower() or str(e.get("id")) == name), None)
        m = map_for(payload, load_maps())
        item = next((i for n, i in (m.items.items() if m else []) if n.lower() == name.lower() and i.id is not None), None)
        if entry is not None:                                   # the AU table's own name, unit and range
            index, (lo, hi), to_stored = int(entry["id"]), (float(entry.get("min", 0)), float(entry.get("max", 1))), float
        elif item is not None:                                  # a vocabulary name through the translation map
            index, (lo, hi), to_stored = item.id, item_raw(m, item), item.to_stored
        elif name.isdigit():
            index, (lo, hi), to_stored = int(name), (0.0, 1.0), float
        else:
            raise CommandError(f"{track} slot {slot}: {manu}/{subtype} has no parameter {name!r} in its AU table or its map; "
                               "a bare id takes 0..1")

        def third(value):
            stored = float(to_stored(value))
            if not lo <= stored <= hi:
                raise CommandError(f"{name}: {float(value):g} is outside {lo:g}..{hi:g}")
            return ((stored - lo) / (hi - lo) if hi != lo else 0.0), f"{float(value):g}"
        return f"{manu}/{subtype}", index, third
    raise CommandError(f"{track} slot {slot}: not a plug-in this can address")


def _apply_param(data: bytes, count, kind: str, track: str, slot: int, name: str, points: str, bars) -> tuple[bytes, str]:
    obj = object_by_name(data, track, count)
    plugin, index, convert = _param_target(data, obj, track, slot, name)
    if kind == "clear":
        return set_param_lane(data, obj, index, [], slot=slot), f"{track}: slot {slot} {plugin} {name} cleared"
    landed = [(tick, *convert(value)) for tick, value in _param_points(points, bars)]
    try:
        data = set_param_lane(data, obj, index, [(t, p) for t, p, _n in landed], slot=slot)
    except ValueError as e:
        raise CommandError(str(e)) from None
    return data, f"{track}: slot {slot} {plugin} {name} = {points.strip()} -> " + ", ".join(n for _t, _p, n in landed)


def _points(text: str, bars) -> list[tuple[int, int]]:
    """``90@1,60@5`` -> [(tick, value)] through the song's meter."""
    out = []
    for item in text.split(","):
        value, _, bar = item.strip().partition("@")
        if not bar:
            raise CommandError(f"a point is VALUE@BAR, not {item.strip()!r}")
        try:
            at, whole = float(bar), int(value)
        except ValueError:
            raise CommandError(f"a point is VALUE@BAR with a whole value and a bar number, not {item.strip()!r}") from None
        if not math.isfinite(at):
            raise CommandError(f"a point is VALUE@BAR with a finite bar, not {item.strip()!r}")
        out.append((bars.tick(at), whole))
    return out


def _apply(data: bytes, count, kind: str, spec: str, bars) -> tuple[bytes, str]:
    if kind in ("set", "clear"):
        target, _, points = spec.partition("=")
        track, _, lane = target.partition(":")
        if (param := _param_lane(lane)) is not None:
            return _apply_param(data, count, kind, track.strip(), param[0], param[1], points, bars)
    if kind == "set":
        target, _, points = spec.partition("=")
        track, _, lane = target.partition(":")
        fader, relative = _lane(lane)
        data = set_lane(data, object_by_name(data, track.strip(), count), fader, _points(points, bars), relative=relative)
        return data, f"{track.strip()}: {lane.strip()} = {points.strip()}"
    if kind == "copy":
        src, _, dst = spec.partition("->")
        track, _, lane = src.partition(":")
        fader, relative = _lane(lane)
        data = copy_lane(data, object_by_name(data, track.strip(), count), object_by_name(data, dst.strip(), count), fader, relative=relative)
        return data, f"{track.strip()}: {lane.strip()} -> {dst.strip()}"
    track, _, lane = spec.partition(":")
    fader, relative = _lane(lane)
    data = clear_lane(data, object_by_name(data, track.strip(), count), fader, relative=relative)
    return data, f"{track.strip()}: {lane.strip()} cleared"


def _write(args, project) -> int:
    lines: list[str] = []

    def step(data, count, data_file):
        """Runs once per alternative, so each line says which one it belongs to — otherwise one
        edit reads as several on a project carrying more than one."""
        bars = meter(data)
        for kind, spec in args.edits:
            data, line = _apply(data, count, kind, spec, bars)
            lines.append(f"  {data_file.parent.name}: {line}")
        return data

    print(f"in  : {project}")
    try:
        edit_copy(project, Path(args.out), step)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    print("\n".join(lines))
    print("\nUnverified until opened in Logic.")
    return 0


def cmd_automation(args) -> int:
    project = find_project(Path(args.project))
    if getattr(args, "edits", None):
        if not args.out:
            print("  --out is needed to write")
            return 2
        return _write(args, project)
    return list_lanes(args, project)


def register(sub) -> None:
    ap = sub.add_parser("automation", help="track automation lanes and points; --set, --copy and --clear write a copy")
    ap.add_argument("project")
    ap.add_argument("--all", action="store_true", help="list tracks whose folder holds no lane too")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--set", action=_Edit, metavar="TRACK:LANE=V@BAR,...",
                    help="replace a lane's points: values 0-127 (Volume 90 and Pan 64 are unity), bars as the display shows them; "
                         "lanes Volume, Pan, Mute, Solo, ±Volume — or `slot N NAME` for a plug-in parameter lane, its values in the "
                         "parameter's own unit (a table name for one of Logic's own, an AU parameter name or id for a third-party)")
    ap.add_argument("--copy", action=_Edit, metavar="TRACK:LANE->TRACK", help="the lane onto another track, replacing the target's")
    ap.add_argument("--clear", action=_Edit, metavar="TRACK:LANE", help="remove the lane's points (a `slot N NAME` lane too)")
    ap.add_argument("--out", help="directory holding the copy to write")
    ap.set_defaults(func=cmd_automation)
