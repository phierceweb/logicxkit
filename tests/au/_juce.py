"""JUCE wire-format builders shared by the juce and tr5 decoders' tests."""

import struct


def vc2(xml: str) -> bytes:
    raw = xml.encode()
    return b"VC2!" + struct.pack("<I", len(raw) + 1) + raw + b"\x00"


def cint(n: int) -> bytes:
    """JUCE compressed int: byte-count then that many LE bytes."""
    if n == 0:
        return b"\x00"
    body = n.to_bytes((n.bit_length() + 7) // 8, "little")
    return bytes([len(body)]) + body


def var_str(s: str) -> bytes:
    payload = b"\x05" + s.encode() + b"\x00"
    return cint(len(payload)) + payload


def var_double(v: float) -> bytes:
    return cint(9) + b"\x04" + struct.pack("<d", v)


def var_bin(payload: bytes) -> bytes:
    return cint(len(payload) + 1) + b"\x08" + payload


def tree(type_: str, props: list[tuple[str, bytes]], children: list[bytes] = ()) -> bytes:
    out = type_.encode() + b"\x00" + cint(len(props))
    for name, var in props:
        out += name.encode() + b"\x00" + var
    out += cint(len(children))
    return out + b"".join(children)


def param(pid: str, value: float) -> bytes:
    return tree("PARAM", [("id", var_str(pid)), ("value", var_double(value))])


def tree_state() -> bytes:
    return tree(
        "neural_dsp_test",
        [("tempo", var_double(210.0)), ("presetNameProp", var_str("Default"))],
        [param("ampBass", 0.71), param("gateThreshold", -80.0),
         tree("midi_mappings", [("plugin_name", var_str("Soldano SLO-100"))])],
    )


APP_MODEL = (
    '<?xml version="1.0" encoding="UTF-8"?> '
    '<appModel pluginVersion="1.0.0" presetUid="42"><subModels>'
    '<parameters gateThreshold="-77.5" gateActive="true"><subModels>'
    '<ampParameters sectionActive="true"><subModels>'
    '<amp ampBass="0.71" ampBright="true"/>'
    "</subModels></ampParameters></subModels></parameters>"
    "</subModels></appModel>"
)
