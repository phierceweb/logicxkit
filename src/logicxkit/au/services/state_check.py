"""A plug-in state's values as the bytes give them against what the plug-in itself reports when the
headless host restores that state: a second reading of a third-party slot that needs no Logic.

The values come by AU parameter id, from the state's id/value pairs or a FabFilter state's binary
blob (`ffp.parse_ffp`, a value per id). On Pro-C 2's pairs and Pro-Q 4's blob every id the host
reports equals the decoded value (46 of 46, 600 of 600: `write-proc`, `translate-proq`).
"""

from __future__ import annotations

import plistlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .aupreset import parse_au_state
from .ffp import parse_ffp
from .host import AuHost, is_headless_safe

TOLERANCE = 1e-5                # relative: the host prints six significant digits
BLOB_BY_ID = {"FQ4p"}           # the FabFilter states whose blob holds a value per AU id, in id order (Pro-Q 4, 600 of 600)


@dataclass
class StateCheck:
    differ: list[str] = field(default_factory=list)      # "id N (name): bytes X, plug-in Y"
    agreed: int = 0


def decoded_values(plist: dict) -> dict[int, float] | None:
    """The state's values by AU parameter id, or None when it carries neither pairs nor a FabFilter
    blob of a plug-in whose blob order is measured (`BLOB_BY_ID`); another plug-in's blob is not read."""
    state = parse_au_state(plist)
    blob = state.blobs.get("FabFilterPluginState")
    if blob and state.subtype in BLOB_BY_ID:
        return dict(enumerate(parse_ffp(blob).values))
    pairs = dict(state.param_pairs or [])                  # a blob of another plug-in is passed over for its pairs, if any
    return pairs or None


def checkable(plist: dict) -> bool:
    """A state the host may load headless and whose values the bytes give."""
    return is_headless_safe(parse_au_state(plist).manufacturer) and decoded_values(plist) is not None


def check_state(plist: dict, host: AuHost) -> StateCheck:
    """Every id both the bytes and the plug-in give, compared; the rest is not judged."""
    ours = decoded_values(plist)
    if ours is None:
        raise ValueError("the state carries no values by parameter id")
    with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as fh:
        plistlib.dump(plist, fh)
        path = Path(fh.name)
    try:
        dump = host.dump_preset(path)
    finally:
        path.unlink(missing_ok=True)
    out = StateCheck()
    for p in dump.params:
        if p.value is None or p.id not in ours:
            continue
        if abs(ours[p.id] - p.value) <= max(1e-6, abs(p.value) * TOLERANCE):
            out.agreed += 1
        else:
            out.differ.append(f"id {p.id} ({p.name}): bytes {ours[p.id]:g}, plug-in {p.value:g}")
    return out
