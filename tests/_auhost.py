"""A FabFilter plug-in's state plist out of a golden, and a headless host that answers with given values —
shared by the state-check goldens and the `chains --verify` tests."""

import json

import _goldens

from logicxkit.au.services.embed import find_au_plists
from logicxkit.au.services.host import AuHost
from logicxkit.logicx import project_data


def fabfilter(key: str) -> dict:
    return next(pl for _off, pl in find_au_plists(project_data(_goldens.path(key)))
                if pl.get("manufacturer") == int.from_bytes(b"FabF", "big"))


def reporting(values: dict[int, float]):
    """A host that reports ``values`` for whatever state it is handed."""
    params = [{"id": i, "name": f"p{i}", "unit": "", "min": 0, "max": 1, "default": 0, "value": v} for i, v in values.items()]
    dump = {"component": "x", "type": "aumf", "subtype": "FC2p", "manufacturer": "FabF", "params": params}
    return AuHost(runner=lambda args, timeout: (0, json.dumps(dump), ""))
