"""An EQ's bands across EQs: each band's shape, frequency, gain, Q, slope and on/off, and the
master gain. A source map lists its bands' parameters (`bands`, one stride per band, with the
shapes and slopes its indexes mean); a target map lists its slots per shape (`slots`). Bands
land in the target's slots by shape — bells by rising frequency — and what finds no slot is
reported, never dropped in silence.
"""

from __future__ import annotations

import math
import re

from .slider import interp, snap
from .translate_izotope import izotope_values
from dataclasses import dataclass

from ...au.services.aupreset import parse_au_state
from ...au.services.embed import find_au_plists
from ...au.services.ffp import parse_ffp
from .._binary import find_blocks, read_block_floats
from .plugin_params import decode, table_for
from .slot_width import plugin_variant

BRICKWALL = math.inf                 # a cut's slope with no finite dB/oct; Pro-Q 4 lists it as None
SHAPES = ("bell", "low_shelf", "low_cut", "high_shelf", "high_cut", "notch", "band_pass", "tilt_shelf", "flat_tilt", "all_pass")


@dataclass(frozen=True)
class Band:
    shape: str
    frequency: float                 # Hz
    gain: float                      # dB
    q: float
    on: bool
    slope: float | None = None       # dB/oct, `BRICKWALL` for a brickwall cut; None when the source has none
    dynamic: bool = False
    number: int = 0                  # the source's band number, for the report

    def label(self) -> str:
        f = f"{self.frequency / 1000:.2f} kHz" if self.frequency >= 999.95 else f"{self.frequency:.0f} Hz"   # 2**log2 noise
        gain = f" {self.gain:+.1f} dB" if self.shape not in ("low_cut", "high_cut", "notch", "band_pass", "all_pass") else ""
        slope = "" if self.slope is None or self.shape not in ("low_cut", "high_cut") else \
            " brickwall" if self.slope == BRICKWALL else f" {self.slope:.0f} dB/oct"
        return f"{self.shape.replace('_', ' ')} {f}{gain} Q {self.q:.2f}{slope}{'' if self.on else ' (off)'}{' dynamic' if self.dynamic else ''}"


def _izotope_bands(payload: bytes, m) -> list[Band]:
    """Neutron's Dynamic EQ: a band per `Band n <field>` of the map's module, its Enable the
    band's existence; a band with dynamics on is flagged and its static curve crosses."""
    values = izotope_values(payload, m)
    lay, shapes = m.raw["bands"], m.raw.get("shapes", [])
    module, fields = lay["module"], lay["fields"]
    out = []
    for n in range(1, lay["count"] + 1):
        at = {f: values.get(f"{module}/Band {n} {name}") for f, name in fields.items()}
        if not at["on"]:
            continue
        if at["frequency"] is None:
            raise ValueError(f"{m.plugin}: band {n} is on but its state has no frequency")
        si = int(at.get("shape") or 0)
        shape = shapes[si] if si < len(shapes) else f"shape {si}"
        dynamic = "static" in fields and not at["static"]
        out.append(Band(shape, float(at["frequency"]), float(at.get("gain") or 0.0), float(at.get("q") or 1.0),
                        True, None, dynamic, n))
    return out


def read_bands(payload: bytes, m, tables: dict) -> tuple[list[Band], float | None]:
    """A slot's bands and master gain through its map: a third-party's from its state by the
    map's band layout, Logic's Channel EQ from its table, slot by slot."""
    raw = m.raw
    if m.decoder == "izotope":
        return _izotope_bands(payload, m), None
    if m.component:
        state = next((parse_au_state(p) for _o, p in find_au_plists(payload) if "manufacturer" in p), None)
        if state is None or m.decoder != "ffbs" or not state.blobs.get("FabFilterPluginState"):
            raise ValueError(f"{m.plugin}: no state this map can read")
        values = parse_ffp(state.blobs["FabFilterPluginState"]).values
        lay, shapes, slopes = raw["bands"], raw["shapes"], raw["slopes"]
        out = []
        for n in range(lay["count"]):
            row = values[n * lay["stride"]:(n + 1) * lay["stride"]]
            if not row[lay["used"]]:
                continue
            freq = 2 ** row[lay["frequency"]] if raw.get("frequency") == "log2" else row[lay["frequency"]]
            q = interp([tuple(p) for p in raw["q_curve"]], row[lay["q"]]) if raw.get("q_curve") else row[lay["q"]]
            si, ki = int(round(row[lay["shape"]])), int(round(row[lay["slope"]])) if "slope" in lay else -1
            shape = shapes[si] if si < len(shapes) else f"shape {si}"
            slope = (BRICKWALL if slopes[ki] is None else slopes[ki]) if 0 <= ki < len(slopes) else None
            dynamic = "dynamic_range" in lay and row[lay["dynamic_range"]] != 0 and bool(row[lay["dynamics_enabled"]])
            out.append(Band(shape, freq, row[lay["gain"]], q, bool(row[lay["enabled"]]), slope, dynamic, n + 1))
        return out, None
    blocks = find_blocks(payload)
    table = table_for(tables, m.type, plugin_variant(payload))
    if not blocks or table is None:
        raise ValueError(f"{m.plugin}: no parameter table to read the block by")
    idx, _t, n = blocks[0]
    d = decode(table, read_block_floats(payload, idx, n))
    out, k = [], 0
    for shape, slots in raw["slots"].items():
        for slot in slots:
            k += 1
            on = d.get(slot["on"])
            on = on == "On" if isinstance(on, str) else bool(on)
            out.append(Band(shape, float(d.get(slot["frequency"], 0)), float(d.get(slot.get("gain", ""), 0) or 0),
                            float(d.get(slot["q"], 0)), on, None, False, k))
    master = d.get(raw["master"]) if raw.get("master") else None
    return out, float(master) if master is not None else None


def plan_bands(bands: list[Band], master: float | None, source, target) -> tuple[dict, list[str], dict]:
    """The target's parameters for the source's bands, the report, and which slot (its field
    names) each source band landed in."""
    raw = target.raw
    slots = {shape: list(entries) for shape, entries in raw["slots"].items()}
    values, notes, placed = {}, [], {}
    step = raw.get("steps", {}).get("gain")
    for entries in slots.values():
        for slot in entries:
            values[slot["on"]] = "Off"
    for band in sorted(bands, key=lambda b: b.frequency):
        free = slots.get(band.shape)
        if not free:
            why = "no slot of that shape in" if band.shape in raw["slots"] else "no analogue in"
            notes.append(f"band {band.number} {band.label()}: {why} {target.plugin}")
            continue
        slot = free.pop(0)
        placed[band.number] = slot
        values[slot["on"]] = "On" if band.on else "Off"
        values[slot["frequency"]] = snap(target, slot["frequency"], round(band.frequency, 2))
        if "gain" in slot:
            gain = band.gain if not step else round(math.floor(band.gain / step + 0.5 + 1e-9) * step, 6)
            values[slot["gain"]] = snap(target, slot["gain"], gain)
        values[slot["q"]] = snap(target, slot["q"], round(band.q, 3))
        if band.shape in ("low_cut", "high_cut") and band.slope is not None:
            notes.append(f"band {band.number} {band.label()}: the slope stays {target.plugin}'s own")
        if band.shape not in ("bell",):
            notes.append(f"band {band.number} {band.label()}: Q carried as is; {target.plugin}'s {band.shape.replace('_', ' ')} is another design (approximate)")
        if band.dynamic:
            notes.append(f"band {band.number} {band.label()}: its dynamics are not carried")
    if master is not None and raw.get("master"):
        values[raw["master"]] = snap(target, raw["master"], master)
    for what, why in source.not_carried.items():
        notes.append(f"{source.plugin} {what}: {why}")
    for what, why in target.not_carried.items():
        notes.append(f"{target.plugin} {what}: {why}")
    return values, notes, placed


def plan_bands_into(bands: list[Band], master: float | None, source, target) -> tuple[list[Band], list[str], dict]:
    """The bands as a third-party target takes them — its layout holds any shape, so each band
    crosses in order, cut slopes snapped to the target's list — the report, and which band
    number each source band became."""
    lay, shapes, slopes = target.raw["bands"], target.raw["shapes"], target.raw["slopes"]
    steps = [s for s in slopes if s is not None] + ([BRICKWALL] if None in slopes else [])
    out, notes, placed = [], [], {}
    for band in bands:
        if not band.on and source.component is None:          # one of Logic's own: an off slot is an empty one
            continue
        if band.shape not in shapes:
            notes.append(f"band {band.number} {band.label()}: no analogue in {target.plugin}")
            continue
        if len(out) >= lay["count"]:
            notes.append(f"band {band.number} {band.label()}: {target.plugin} has no band left")
            continue
        slope = band.slope
        if band.shape in ("low_cut", "high_cut"):
            if slope is None:
                slope = 12
                notes.append(f"band {band.number} {band.label()}: {source.plugin} carries no slope for it; "
                             f"{target.plugin} gets 12 dB/oct")
            elif slope not in steps:
                near = max(steps) if slope == BRICKWALL else min(steps, key=lambda s: abs(s - slope))
                shown = "brickwall" if slope == BRICKWALL else f"{slope:.0f} dB/oct"
                notes.append(f"band {band.number} {band.label()}: slope {shown} becomes {near} dB/oct")
                slope = near
        if band.shape != "bell":
            notes.append(f"band {band.number} {band.label()}: Q carried as is; {target.plugin}'s "
                         f"{band.shape.replace('_', ' ')} is another design (approximate)")
        if band.dynamic:
            notes.append(f"band {band.number} {band.label()}: its dynamics are not carried")
        out.append(Band(band.shape, band.frequency, band.gain, band.q, band.on, slope, False, len(out) + 1))
        placed[band.number] = len(out)
    if master:
        notes.append(f"master {master:+.1f} dB: no analogue in {target.plugin}")
    for what, why in source.not_carried.items():
        notes.append(f"{source.plugin} {what}: {why}")
    for what, why in target.not_carried.items():
        notes.append(f"{target.plugin} {what}: {why}")
    return out, notes, placed


SHAPE_WORDS = ("low cut", "low shelf", "high shelf", "high cut", "band pass", "tilt shelf", "flat tilt", "all pass",
               "bell", "notch")


def parse_band(spec: str) -> Band:
    """A band from its label: ``bell 250 Hz -4 dB Q 2.4``, ``low cut 80 Hz 24 dB/oct``, ``… off``."""
    text = " ".join(re.sub(r"[()]", " ", spec.lower()).split())
    shape = next((w for w in SHAPE_WORDS if text == w or text.startswith(w + " ")), None)
    if shape is None:
        raise ValueError(f"{spec!r}: a band starts with its shape ({', '.join(SHAPE_WORDS)})")
    rest = text[len(shape):]
    freq = re.search(r"(\d+(?:\.\d+)?)\s*(k?)hz\b", rest)
    if freq is None:
        raise ValueError(f"{spec!r}: a band names its frequency, in Hz or kHz")
    gain = re.search(r"([-+]?\d+(?:\.\d+)?)\s*db(?!/)", rest)
    q = re.search(r"\bq\s*(\d+(?:\.\d+)?)", rest)
    slope = re.search(r"(\d+(?:\.\d+)?)\s*db/oct", rest)
    wall = re.search(r"\bbrickwall\b", rest)
    return Band(shape.replace(" ", "_"), float(freq.group(1)) * (1000 if freq.group(2) else 1),
                float(gain.group(1)) if gain else 0.0, float(q.group(1)) if q else 1.0,
                "off" not in rest.split(), BRICKWALL if wall else float(slope.group(1)) if slope else None)
