"""Waves ``Waves_XPst`` chunks — a binary head followed by a
``<PresetChunkXMLTree>`` XML document whose ``Parameters Type="RealWorld"``
text holds positional real-unit values (``*`` = unset). Decodes statically;
WaveShell AUs crash headless, so this is the only Waves read path.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

_OPEN = b"<PresetChunkXMLTree"
_CLOSE = b"</PresetChunkXMLTree>"


def _token(t: str) -> float | None:
    return None if t == "*" else float(t)


def extract_xpst(chunk: bytes) -> dict | None:
    start = chunk.find(_OPEN)
    end = chunk.rfind(_CLOSE)
    if start < 0 or end < 0:
        return None
    try:
        root = ET.fromstring(chunk[start : end + len(_CLOSE)].decode("utf-8", "replace"))
    except ET.ParseError:
        return None
    preset = root.find("Preset")
    if preset is None:
        return None
    setups: dict[str, list[float | None]] = {}
    for pd in preset.findall("PresetData"):
        params = pd.find("Parameters")
        if params is None or params.get("Type") != "RealWorld":
            continue
        try:
            setups[pd.get("Setup", "?")] = [_token(t) for t in (params.text or "").split()]
        except ValueError:
            continue
    return {
        "plugin": preset.findtext("PresetHeader/PluginName"),
        "version": preset.findtext("PresetHeader/PluginVersion"),
        "active_setup": preset.findtext("PresetHeader/ActiveSetup"),
        "setups": setups,
    }
