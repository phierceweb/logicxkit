"""IK T-RackS 5 Suite state — the module chain lives in a JUCE ValueTree
``Chain`` prop (binary var) holding a plain ``<Session>`` XML document:
per-snapshot ``<Slot>`` groups whose ``<SlotN>`` children carry the module
GUID, bypass flag, and every module parameter as named attributes. The AU
itself exposes only 16 shallow params, so this is the real read path.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from logicxkit.au.services.juce import decode_juce_xml, parse_value_tree


def decode_tr5(state: bytes) -> dict | None:
    tree = parse_value_tree(state)
    if tree is None or tree.get("type") != "State":
        return None
    chain = tree["props"].get("Chain")
    if not isinstance(chain, bytes):
        return None
    xml_text = decode_juce_xml(chain) or chain.rstrip(b"\x00").decode("utf-8", "replace")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    if root.tag != "Session":
        return None
    snapshots = []
    for snap in root.findall("Slot"):
        slots = []
        for el in snap:
            if el.tag == "SlotMasterMatch" or not el.tag.startswith("Slot"):
                continue
            module = el.find("Module")
            slots.append({"slot": el.tag, "bypass": el.get("Bypass"),
                          "guid": el.get("ChainNodeModuleGUID"),
                          "params": dict(module.attrib) if module is not None else {}})
        snapshots.append({"snapshot": snap.get("SnapshotID"),
                          "preset": snap.get("PresetPath"), "slots": slots})
    return {"current_preset": root.get("CurrentPreset"), "snapshots": snapshots}
