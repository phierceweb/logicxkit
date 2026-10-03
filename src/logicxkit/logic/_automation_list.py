"""`logic automation`'s listing: each track's lanes and points, a plug-in parameter lane by the
name `--set` takes and its points in the parameter's own unit."""

from __future__ import annotations

import json

from ._edit import first_project_data
from .services.regions.automation import FRACTION_UNIT, read_automation
from .services.regions.automation_names import lane_target
from .services.mixer.binding import bound_channels
from .services.mixer.plugin_params import load_tables
from .services.song.signature import meter
from .services.translate.translate import load_maps


def _targets(data: bytes, folders) -> dict:
    """(track object, insert, index) -> what each parameter lane addresses, where it can be named."""
    owners, tables, maps, out = bound_channels(data), None, None, {}
    for a in folders:
        for ln in a.lanes:
            if ln.slot is None or a.track_object not in owners:
                continue
            tables, maps = tables or load_tables(), maps or load_maps()
            target = lane_target(data, owners[a.track_object], ln.slot, ln.param_index, tables=tables, maps=maps)
            if target is not None:
                out[a.track_object, ln.slot, ln.param_index] = target
    return out


def _label(lane, target) -> str:
    """A named lane as `--set` takes it, `slot N NAME`, with its plug-in and index."""
    if target is None:
        return lane.parameter
    if target.name is None:
        return f"{lane.parameter} ({target.plugin})"
    return f"slot {lane.slot} {target.name} ({target.plugin}, parameter {lane.param_index})"


def _text(value) -> str:
    return ("on" if value else "off") if isinstance(value, bool) else f"{value:g}"


def _shown(target, point: float) -> str:
    value = target.value(point) if target else None
    if value is None:
        return ""
    return f"  = {_text(value)}{'' if not target.unit or target.unit.startswith(':') else ' '}{target.unit}"


def _named(target) -> dict:
    return {} if target is None else {"plugin": target.plugin, "name": target.name, "unit": target.unit}


def _in_unit(target, point: float) -> dict:
    value = target.value(point) if target else None
    return {} if value is None else {"in_unit": value}


def list_lanes(args, project) -> int:
    data = first_project_data(project)
    folders = [a for a in read_automation(data) if a.lanes or args.all]
    targets = _targets(data, folders)
    if args.json:
        print(json.dumps([{"sequence": a.sequence, "track": a.track, "track_object": a.track_object,
                           "lanes": [{"parameter": ln.parameter, "fader": ln.fader, "param_index": ln.param_index,
                                      "slot": ln.slot, "region": ln.region, **_named(targets.get((a.track_object, ln.slot, ln.param_index))),
                                      "points": [{"tick": p.tick, "fraction": p.fraction, "value": p.value, "flagged": p.flagged,
                                                  **_in_unit(targets.get((a.track_object, ln.slot, ln.param_index)), p.value)}
                                                 for p in ln.points]}
                                     for ln in a.lanes]} for a in folders], indent=1))
        return 0
    bars = meter(data)
    print(f"{project.name}: {sum(len(a.lanes) for a in folders)} lane(s) on {len(folders)} track(s)")
    for a in folders:
        print(f"  {a.track or f'(no track, sequence {a.sequence})'}")
        for ln in a.lanes:
            where = " (region)" if ln.region else ""
            target = targets.get((a.track_object, ln.slot, ln.param_index))
            print(f"    {_label(ln, target)}{where}: {len(ln.points)} point(s)")
            for p in ln.points:
                value = f"{p.value:.4f}" if ln.param_index is not None else f"{p.value:.0f}"
                print(f"      bar {bars.bar(p.tick + p.fraction / FRACTION_UNIT):9.5f}  {value}{_shown(target, p.value)}{'  ?' if p.flagged else ''}")
    return 0
