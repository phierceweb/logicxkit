"""JUCE plugin-state decode — what AU plugins put in ``jucePluginState``.

Two container shapes, vendor-independent: an XML document wrapped by ``copyXmlToBinary``,
or a binary ValueTree. Extraction-only; writing state back is out of scope.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

from logicxkit.au.services.embed import fourcc

_MAX_NODES = 4096  # sanity bound so garbage never parses as a huge ValueTree


def decode_juce_xml(state: bytes) -> str | None:
    """Unwrap a JUCE ``copyXmlToBinary`` container; None if it isn't one."""
    if len(state) < 8 or not state.startswith(b"VC2!"):
        return None
    n = struct.unpack_from("<I", state, 4)[0]
    return state[8 : 8 + n].rstrip(b"\x00").decode("utf-8", "replace")


# ---- JUCE binary ValueTree ------------------------------------------------------------

def _read_string(data: bytes, pos: int) -> tuple[str, int]:
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("utf-8"), end + 1


def _read_cint(data: bytes, pos: int) -> tuple[int, int]:
    n = data[pos]
    pos += 1
    if n == 0:
        return 0, pos
    if n > 8 or pos + n > len(data):
        raise ValueError("not a JUCE compressed int")
    return int.from_bytes(data[pos : pos + n], "little"), pos + n


def _read_var(data: bytes, pos: int):
    size, pos = _read_cint(data, pos)
    if size == 0:
        return None, pos
    kind, payload = data[pos], data[pos + 1 : pos + size]
    pos += size
    if kind == 1:
        return struct.unpack("<i", payload)[0], pos
    if kind == 2:
        return True, pos
    if kind == 3:
        return False, pos
    if kind == 4:
        return struct.unpack("<d", payload)[0], pos
    if kind == 5:
        return payload.rstrip(b"\x00").decode("utf-8", "replace"), pos
    if kind == 6:
        return struct.unpack("<q", payload)[0], pos
    if kind == 8:
        return payload, pos  # binary blob (e.g. TR5's Chain XML) — caller decodes
    return None, pos  # unknown var kind: skip payload, keep parsing


def _read_tree(data: bytes, pos: int) -> tuple[dict, int]:
    type_, pos = _read_string(data, pos)
    if not type_ or not type_[0].isascii() or not type_.isprintable():
        raise ValueError(f"implausible ValueTree type {type_!r}")
    nprops, pos = _read_cint(data, pos)
    if nprops > _MAX_NODES:
        raise ValueError("implausible prop count")
    props = {}
    for _ in range(nprops):
        name, pos = _read_string(data, pos)
        props[name], pos = _read_var(data, pos)
    nkids, pos = _read_cint(data, pos)
    if nkids > _MAX_NODES:
        raise ValueError("implausible child count")
    children = []
    for _ in range(nkids):
        child, pos = _read_tree(data, pos)
        children.append(child)
    return {"type": type_, "props": props, "children": children}, pos


def parse_value_tree(state: bytes) -> dict | None:
    """Parse a JUCE binary ValueTree to ``{type, props, children}``; None on garbage."""
    try:
        tree, _ = _read_tree(state, 0)
        return tree
    except (ValueError, IndexError, struct.error, UnicodeDecodeError):
        return None


# ---- state -> meta/sections -----------------------------------------------------------

def _convert(v: str):
    if v == "true":
        return True
    if v == "false":
        return False
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _xml_sections(xml_text: str) -> tuple[dict, dict]:
    """Root attrs -> meta; every attributed descendant element -> a section by tag."""
    root = ET.fromstring(xml_text)
    meta = {k: _convert(v) for k, v in root.attrib.items()}
    sections: dict[str, dict] = {}
    for el in root.iter():
        if el is root or not el.attrib:
            continue
        sections.setdefault(el.tag, {}).update(
            {k: _convert(v) for k, v in el.attrib.items()})
    return meta, sections


def _tree_sections(root: dict) -> tuple[dict, dict]:
    """Root + descendant metadata props -> meta; PARAM id/value children -> params."""
    meta = dict(root["props"])
    params: dict = {}

    def walk(node: dict) -> None:
        if node["type"] == "PARAM":
            pid = node["props"].get("id")
            if pid is not None:
                params[pid] = node["props"].get("value")
            return
        for k, v in node["props"].items():
            meta.setdefault(k, v)
        for child in node["children"]:
            walk(child)

    for child in root["children"]:
        walk(child)
    return meta, {"params": params}


def state_from_plist(pl: dict) -> dict | None:
    """Decode one AU ClassInfo plist's ``jucePluginState``; None if undecodable."""
    state = pl.get("jucePluginState")
    if not isinstance(state, bytes):
        return None
    xml_text = decode_juce_xml(state)
    if xml_text is not None:
        try:
            meta, sections = _xml_sections(xml_text)
        except ET.ParseError:
            return None
        fmt = "xml"
    else:
        tree = parse_value_tree(state)
        if tree is None:
            return None
        meta, sections = _tree_sections(tree)
        fmt = "tree"
    return {"subtype": fourcc(pl.get("subtype", 0)),
            "format": fmt, "meta": meta, "sections": sections}
