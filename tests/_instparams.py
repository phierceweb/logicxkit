"""Shared readers for the instrument parameter-table goldens: the measured plug-in's payload,
block and words in a save, and the manifest keys of each kind of save."""

import re

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.slot_width import plugin_variant
from logicxkit.logic.services.stream.stream import HEADER, project_records

PAIRS = tuple((k, k[:-len("-defaults")] + "-spots") for k in sorted(_goldens.manifest())
              if k.startswith("instrument-params-") and k.endswith("-defaults")
              and k[:-len("-defaults")] + "-spots" in _goldens.manifest())
# the float-block plug-ins; a text state (Alchemy) and the chunked states (Sampler) are measured apart
RUNS = tuple(pair for pair in PAIRS if _goldens.fact(pair[0], "type") is not None and _goldens.fact(pair[0], "state") is None)
TEXT = tuple(pair for pair in PAIRS if _goldens.fact(pair[0], "state") == "text")
CHUNKED = tuple(pair for pair in PAIRS if str(_goldens.fact(pair[0], "state", "")).startswith("MELC")
                or _goldens.fact(pair[0], "state") == "words")


def _payload(data: bytes, label: str, name: str) -> bytes:
    """The measured plug-in's slot payload on the channel: the slot whose largest block is of the
    measured type (a Studio instrument's state carries a Channel EQ's beside its engine's)."""
    owner = owner_by_label(data, label)
    for r in project_records(data):
        payload = r.raw[HEADER:]
        if r.tag == b"UCuA" and r.owner == owner and (h := slot_header(payload)) and h.maker in ("EMAG", "CLEM"):
            blocks = find_blocks(payload)
            if blocks and max(blocks, key=lambda b: b[2])[1] == _goldens.fact(name, "type"):
                return payload
            if not blocks and h.code == _goldens.fact(name, "type"):      # a text state: the header alone types it
                return payload
    raise AssertionError(f"no block of type {_goldens.fact(name, 'type')} on {label}")


def _block(data: bytes, label: str, name: str) -> tuple[int, int | None, list[float]]:
    """(type, variant base, floats) of the measured plug-in's block; no floats for a text state."""
    payload = _payload(data, label, name)
    blocks = find_blocks(payload)
    if not blocks:
        return slot_header(payload).code, plugin_variant(payload), []
    idx, type_id, n = max(blocks, key=lambda b: b[2])
    return type_id, plugin_variant(payload), list(read_block_floats(payload, idx, n))


def _word(payload: bytes, p) -> float | int:
    """A parameter's raw word in a payload: the block float by index, or the word at its offset."""
    import struct
    if p.offset is not None:
        return struct.unpack_from("<i" if p.kind == "int" else "<f", payload, p.offset)[0]
    idx, _type, n = max(find_blocks(payload), key=lambda b: b[2])
    return read_block_floats(payload, idx, n)[p.index]


def _close(a, b) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= max(0.011, abs(b) * 0.002)


def _slot_of(data: bytes, label: str, name: str) -> bytes:
    from logicxkit.logic.services.mixer.plugins import project_plugins
    owner = owner_by_label(data, label)
    key = next(r.key for r in project_plugins(data) if r.channel == label and r.name == name)
    return next(r.raw[HEADER:] for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner and r.key == key)


CODED = tuple(k for k in sorted(_goldens.manifest())
              if (k.startswith("instrument-params-") or k.startswith("effectcheck-")) and re.search(r"-code\d*-base$", k))


def _slug_and_prefix(key: str) -> tuple[str, str]:
    prefix = "instrument-params-" if key.startswith("instrument-params-") else "effectcheck-"
    return re.sub(r"-code\d*-base$", "", key[len(prefix):]), prefix


def _series_of(key: str) -> str:
    """`code` for the first coded series of a plug-in, `code2` for the later one over the rows
    the table still listed unmapped."""
    return re.search(r"-(code\d*)-base$", key).group(1)


def _unit_scaled(unit: str, shown: str, want: float, word: float) -> bool:
    """A display in the other unit of the word's: s or kHz shown over a word in ms or Hz (and
    the reverse), a percentage shown over a fraction. The tolerance is relative, so a zero word
    reads as no display but 0."""
    factors = {"ms": (1000.0,), "hz": (1000.0,), "s": (0.001,), "khz": (0.001,), "%": (0.01, 100.0)}.get(unit.lower(), ())
    return any(abs(want * k - word) <= abs(want * k) * 0.002 + (0.011 if k >= 1 else 0.0) * (want != 0)
               for k in factors)


ROWS = tuple(k for k in sorted(_goldens.manifest())
             if k.startswith("instrument-params-") and k.endswith(("-row00", "-again00", "-single00")))


def _series(key: str) -> tuple[str, str]:
    """(plug-in slug, series name) of a one-row base key: `…-<slug>-row00`, `-again00` or `-single00`."""
    slug, _dash, series = key[len("instrument-params-"):].rpartition("-")
    return slug, series[:-2]
