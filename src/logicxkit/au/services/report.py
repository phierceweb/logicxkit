"""Decode orchestration for preset files and embedded strip states.

Per-state decode ladder: Neural DSP -> the JUCE decoders in
``logicxkit.au.services.juce``; Waves -> static XPst; everything else ->
the AU host when available and headless-safe, else the static ``data``-pairs
+ checked-in table join. Every path returns the same row shape
(id/name/unit/value/default/changed, plus ``display`` from the AU host).
"""

from __future__ import annotations

import plistlib
import tempfile
from pathlib import Path

from logicxkit.au.services.aupreset import parse_au_state
from logicxkit.au.services.embed import find_au_plists
from logicxkit.au.services.ffp import parse_ffp
from logicxkit.au.services.host import AuHost, AuHostError, is_headless_safe
from logicxkit.au.services.juce import state_from_plist
from logicxkit.logicx import read_states
from logicxkit.au.services.sonible import decode_sonible
from logicxkit.au.services.tables import ffp_identity, join_values, load_table
from logicxkit.au.services.tr5 import decode_tr5
from logicxkit.au.services.waves import extract_xpst

_NDSP = "NDSP"
_WAVES = "ksWV"
_SONIBLE = "Soni"
_IK = "Ikmm"


def decode_preset_bytes(data: bytes, suffix: str, host: AuHost | None,
                        name_hint: str | None = None) -> dict:
    if suffix == ".ffp":
        p = parse_ffp(data)
        manu, sub = ffp_identity(p.magic)
        table = load_table(manu, sub)
        return {"format": "ffp", "decode_path": "static",
                "plugin": {"manufacturer": manu, "subtype": sub,
                           "component": (table or {}).get("component")},
                "preset_name": name_hint,
                "params": join_values(table, list(enumerate(p.values)))}
    if suffix in (".aupreset", ".plist", ".pst"):
        pl = plistlib.loads(data)
        out = decode_state_plist(pl, host)
        out["format"] = "aupreset"
        return out
    raise ValueError(f"unsupported preset suffix {suffix!r}")


def decode_state_plist(pl: dict, host: AuHost | None) -> dict:
    st = parse_au_state(pl)
    out: dict = {
        "format": "embedded",
        "plugin": {"manufacturer": st.manufacturer, "subtype": st.subtype,
                   "component": None},
        "preset_name": st.name,
        "blobs": {k: len(v) for k, v in st.blobs.items()},
    }
    if st.manufacturer == _NDSP:
        decoded = state_from_plist(pl)
        if decoded is not None:
            out.update(decode_path="neural", neural=decoded, params=[])
            return out
    if st.manufacturer == _WAVES and "Waves_XPst" in st.blobs:
        x = extract_xpst(st.blobs["Waves_XPst"])
        if x is not None:
            active = x["setups"].get(x["active_setup"] or "", [])
            out["plugin"]["component"] = f"Waves: {x['plugin']}"
            out.update(decode_path="waves-xpst", waves=x,
                       params=[{"id": i, "name": f"param{i}", "unit": None,
                                "value": v, "default": None, "changed": None}
                               for i, v in enumerate(active) if v is not None])
            return out
    if st.manufacturer == _SONIBLE and "jucePluginState" in st.blobs:
        s = decode_sonible(st.blobs["jucePluginState"])
        if s is not None:
            out.update(decode_path="sonible-protobuf", sonible=s, params=[])
            return out
    if st.manufacturer == _IK and "jucePluginState" in st.blobs:
        t = decode_tr5(st.blobs["jucePluginState"])
        if t is not None:
            out.update(decode_path="tr5-chain", tr5=t, params=[])
            return out
    if host is not None and is_headless_safe(st.manufacturer):
        try:
            out.update(_host_decode(pl, host))
            return out
        except AuHostError as e:
            out["host_error"] = str(e)
    table = load_table(st.manufacturer, st.subtype)
    if table:
        out["plugin"]["component"] = table.get("component")
    out.update(decode_path="static",
               params=join_values(table, st.param_pairs or []))
    return out


def _host_decode(pl: dict, host: AuHost) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as fh:
        plistlib.dump(pl, fh)
        tmp = Path(fh.name)
    try:
        dump = host.dump_preset(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return {"decode_path": "au-host",
            "plugin": {"manufacturer": dump.manufacturer, "subtype": dump.subtype,
                       "component": dump.component},
            "params": [{"id": p.id, "name": p.name, "unit": p.unit,
                        "value": p.value, "default": p.default,
                        "display": p.display,
                        "changed": (None if p.value is None
                                    else abs(p.value - p.default) > 1e-6)}
                       for p in dump.params]}


def decode_strip_bytes(data: bytes, host: AuHost | None) -> list[dict]:
    out = []
    for off, pl in find_au_plists(data):
        if "manufacturer" not in pl:
            continue
        state = decode_state_plist(pl, host)
        state["offset"] = off
        out.append(state)
    return out


def decode_strip_path(path: str | Path, host: AuHost | None) -> list[dict]:
    """Flat file (.cst/.pst) or .logicx bundle; bundle states gain a channel label."""
    return read_states(path, lambda data: decode_strip_bytes(data, host))
