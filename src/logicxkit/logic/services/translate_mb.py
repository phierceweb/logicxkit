"""A multiband compressor's settings: bands by frequency range, each a compressor or an expander,
beside the plug-in's globals. Pro-MB reads from its pairs by band layout, Multipressor from its
table — a Multipressor band switched off (`Band N Monitor`) is no band at all, its range the next
live band's, as its editor draws it. A plan lays the source's bands over the target's — 20 Hz to
20 kHz in at most the target's count, a stretch no band covers as a band set to pass it untouched
(0 dB threshold, 1:1 ratios, no make-up) — and reports what does not cross."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...au.services.aupreset import parse_au_state
from ...au.services.austate_write import patch_pairs, replace_data
from ...au.services.embed import find_au_plists
from .._binary import find_blocks, read_block_floats
from .plugin_params import decode, table_for
from .slot_width import plugin_variant
from .mb_segments import SLIVER, _hz, segments  # noqa: F401
from .slider import interp, snap

UNLIMITED = -30.0                    # Pro-MB's widest downward range: a compressor without a limit


@dataclass(frozen=True)
class MBand:
    low: float                       # Hz
    high: float
    mode: str                        # compress | expand
    threshold: float                 # dB
    ratio: float
    level: float = 0.0               # dB make-up
    on: bool = True
    range: float | None = None       # dB: Pro-MB's limit on the gain change, negative downward
    attack: float | None = None
    release: float | None = None
    time_unit: str = "ms"            # "%" for Pro-MB: percentages of a program-dependent time
    knee: float | None = None        # dB
    lookahead: float | None = None   # ms
    expander: tuple[float, float, float] | None = None   # Multipressor's (threshold dB, ratio, reduction dB) beside the compressor
    number: int = 0

    def label(self) -> str:
        parts = [f"{_hz(self.low)}-{_hz(self.high)} {self.mode} {self.threshold:+.1f} dB {self.ratio:.2f}:1"]
        if self.range is not None:
            parts.append(f"range {self.range:+.1f} dB")
        if self.attack is not None and self.release is not None:
            parts.append(f"{self.attack:g}/{self.release:g} {self.time_unit}")
        if self.level:
            parts.append(f"{self.level:+.1f} dB")
        if self.expander and self.expander[1] > 1.001:
            parts.append(f"expand {self.expander[0]:+.0f} dB {self.expander[1]:.2f}:1 to {self.expander[2]:+.0f} dB")
        return " ".join(parts) + ("" if self.on else " (off)")


def read_mbands(payload: bytes, m, tables: dict) -> list[MBand]:
    raw = m.raw
    if m.component:
        pairs = dict(_state(payload, m).param_pairs or [])
        lay, curves = raw["bands"], raw["curves"]
        out = []
        for n in range(lay["count"]):
            base = n * lay["stride"]
            row = {f: pairs.get(base + i) for f, i in lay.items() if f not in ("count", "stride")}
            state = raw["states"][int(round(row["state"] or 0))]
            if state == "unused":
                continue
            freq = (lambda v: 2 ** v) if raw.get("frequency") == "log2" else (lambda v: v)
            out.append(MBand(freq(row["low"]), freq(row["high"]), raw["modes"][int(round(row["mode"] or 0))],
                             interp(curves["threshold"], row["threshold"]), interp(curves["ratio"], row["ratio"]),
                             row["level"], state == "enabled", row["range"], row["attack"], row["release"], "%",
                             row["knee"], row["lookahead"], number=n + 1))
        return out
    blocks = find_blocks(payload)
    table = table_for(tables, m.type, plugin_variant(payload))
    if not blocks or table is None:
        raise ValueError(f"{m.plugin}: no parameter table to read the block by")
    idx, _t, n = blocks[0]
    d = decode(table, read_block_floats(payload, idx, n))
    lo_edge, hi_edge = (float(e) for e in raw["edges"])
    live = [i for i, slot in enumerate(raw["slots"]) if str(d[slot["on"]]).lower() in ("on", "1", "1.0")]
    out = []
    for n, i in enumerate(live):
        slot = raw["slots"][i]
        low = out[-1].high if out else lo_edge            # an off band's range belongs to the live band above it
        high = float(d[slot["high"]]) if "high" in slot and n + 1 < len(live) else hi_edge
        exp = (float(d[slot["exp_threshold"]]), float(d[slot["exp_ratio"]]), float(d[slot["reduction"]]))
        out.append(MBand(low, high, "compress", float(d[slot["threshold"]]), float(d[slot["ratio"]]), float(d[slot["level"]]),
                         True, None, float(d[slot["attack"]]), float(d[slot["release"]]), "ms", None, None, exp, i + 1))
    return out


def neutral(b: MBand) -> bool:
    """A band that changes nothing: 1:1 both ways and no make-up."""
    return b.ratio <= 1.001 and not (b.expander and b.expander[1] > 1.001) and abs(b.level) < 0.05


def plan_mbands(settings, target) -> tuple[dict, list[MBand], list[str], dict]:
    """``(values, bands, notes, placed)``: a native target's table values, or a third-party's
    bands with its vocabulary globals; ``placed`` maps a source band number to the target's slot
    (its field names) or band number."""
    source, notes = settings.map, []
    if target.component is None:
        values, placed = _into_slots(settings, target, notes)
        bands = []
    else:
        values, bands, placed = _into_layout(settings, target, notes)
    for what, why in source.not_carried.items():
        notes.append(f"{source.plugin} {what}: {why}")
    for what, why in target.not_carried.items():
        notes.append(f"{target.plugin} {what}: {why}")
    return values, bands, notes, placed


def _into_slots(settings, target, notes: list[str]) -> tuple[dict, dict]:
    """A native target: its slots' table values from the source's bands and globals, and which
    slot each source band landed in."""
    raw, source = target.raw, settings.map
    slots, steps, ranges = raw["slots"], raw.get("steps", {}), raw.get("ranges", {})
    segs = segments(settings.bands, tuple(raw["edges"]), len(slots), source.plugin, target.plugin, notes)
    values, placed = {}, {}
    percent = False

    def within(what: str, value: float, band: MBand | None) -> float:
        lo, hi = ranges.get(what, (-math.inf, math.inf))
        held = min(max(value, lo), hi)
        if held != value:
            where = f"band {band.number}: " if band else ""
            notes.append(f"{where}{what} {value:g} is past {target.plugin}'s {lo:g}..{hi:g}; set to {held:g}")
        return held

    for i, slot in enumerate(slots):
        lo, hi, b = segs[i] if i < len(segs) else (raw["edges"][1], raw["edges"][1], None)
        values[slot["on"]] = "On" if i < len(segs) and (b is None or b.on) else "Off"
        if "high" in slot:
            values[slot["high"]] = snap(target, slot["high"], round(within("crossover", hi, b), 1))
        if b is None:
            if i < len(segs):                               # an uncovered stretch passes untouched
                values[slot["threshold"]] = _step(0.0, steps.get("threshold"))
                values[slot["ratio"]], values[slot["exp_ratio"]] = 1.0, 1.0
                values[slot["level"]] = _step(0.0, steps.get("level"))
            continue
        placed[b.number] = slot
        values[slot["threshold"]], values[slot["ratio"]] = _step(0.0, steps.get("threshold")), 1.0
        if b.mode == "compress" and (b.range is None or b.range <= 0):
            values[slot["threshold"]] = snap(target, slot["threshold"], _step(within("threshold", b.threshold, b), steps.get("threshold")))
            values[slot["ratio"]] = snap(target, slot["ratio"], round(within("ratio", b.ratio, b), 3))
            if b.range is not None and b.range > UNLIMITED + 0.05:
                notes.append(f"band {b.number} {b.label()}: {source.plugin}'s range stops the gain change at "
                             f"{b.range:+.1f} dB; {target.plugin} has no limit")
        elif b.mode == "expand" and b.range is not None and b.range <= 0:
            values[slot["exp_threshold"]] = _step(within("exp_threshold", b.threshold, b), steps.get("threshold"))
            values[slot["exp_ratio"]] = round(within("exp_ratio", b.ratio, b), 3)
            values[slot["reduction"]] = round(b.range, 1)
        else:
            notes.append(f"band {b.number} {b.label()}: upward {b.mode}ion has no analogue in {target.plugin}; "
                         f"the band passes as it is")
        values[slot["level"]] = snap(target, slot["level"], _step(within("level", b.level, b), steps.get("level")))
        if b.time_unit == "ms" and b.attack is not None:
            values[slot["attack"]] = snap(target, slot["attack"], round(within("attack", b.attack, b), 3))
            values[slot["release"]] = snap(target, slot["release"], round(within("release", b.release, b), 3))
        else:
            percent = True
        if b.knee is not None:
            notes.append(f"band {b.number}: knee {b.knee:.0f} dB has no analogue in {target.plugin}")
    if percent:
        notes.append(f"attack and release are percentages in {source.plugin}; {target.plugin} keeps its own")
    g = settings.values
    look = [b.lookahead for _lo, _hi, b in segs if b is not None and b.on and b.lookahead is not None]
    if "lookahead" in target.items and (look or "lookahead_on" in g):
        ms = max(look) if look and g.get("lookahead_on", True) else 0.0
        values[target.items["lookahead"].param] = snap(target, target.items["lookahead"].param, round(within("lookahead", ms, None), 3))
        if look and len(set(round(x, 3) for x in look)) > 1:
            notes.append(f"lookahead: the bands differ ({', '.join(f'{x:g}' for x in look)} ms); the longest carried (approximate)")
    if "output_gain" in g and "output_gain" in target.items:
        values[target.items["output_gain"].param] = snap(target, target.items["output_gain"].param, round(within("output_gain", g["output_gain"], None), 2))
    if g.get("input_gain"):
        notes.append(f"input_gain {g['input_gain']:+.1f} dB: no analogue in {target.plugin}")
    if "mix" in g and abs(g["mix"] - 100) > 0.05:
        notes.append(f"mix {g['mix']:g}%: no analogue in {target.plugin}")
    return values, placed


def _into_layout(settings, target, notes: list[str]) -> tuple[dict, list[MBand], dict]:
    """A third-party target: the source's live bands as its bands, its vocabulary globals, and
    which band number each source band became."""
    count = target.raw["bands"]["count"]
    fmin, fmax = target.raw.get("range_hz", (0.0, math.inf))
    source_is_native = settings.map.component is None
    bands: list[MBand] = []
    placed: dict = {}
    for b in sorted(settings.bands, key=lambda b: b.low):
        if not b.on or (source_is_native and neutral(b)):
            continue
        if len(bands) >= count:
            notes.append(f"band {b.number} {b.label()}: {target.plugin} has {count} bands; dropped")
            continue
        low, high = max(b.low, fmin), min(b.high, fmax)
        if (low, high) != (b.low, b.high):
            notes.append(f"band {b.number}: {target.plugin}'s crossovers run {_hz(fmin)} to {_hz(fmax)}; "
                         f"{_hz(b.low)}-{_hz(b.high)} becomes {_hz(low)}-{_hz(high)}")
        mode, threshold, ratio, rng = "compress", b.threshold, b.ratio, b.range
        if b.expander and b.expander[1] > 1.001:
            if b.ratio <= 1.001:
                mode, threshold, ratio, rng = "expand", b.expander[0], b.expander[1], b.expander[2]
            else:
                notes.append(f"band {b.number} {b.label()}: expansion beside compression has no place in one "
                             f"{target.plugin} band; not carried")
        if rng is None:
            rng = UNLIMITED
            notes.append(f"band {b.number} {b.label()}: {target.plugin}'s range set to {UNLIMITED:+.0f} dB, its widest")
        attack, release, unit = (b.attack, b.release, b.time_unit) if b.time_unit == "%" else (None, None, "%")
        bands.append(MBand(low, high, mode, threshold, ratio, b.level, True, rng, attack, release, unit,
                           b.knee, b.lookahead, None, len(bands) + 1))
        placed[b.number] = len(bands)
    if any(b.time_unit == "ms" and b.attack is not None for b in settings.bands):
        notes.append(f"attack and release in milliseconds: {target.plugin}'s are percentages, its own kept")
    values = {}
    g = settings.values
    if "output_gain" in g and "output_gain" in target.items:
        values["output_gain"] = round(g["output_gain"], 2)
    if "lookahead" in g and "lookahead_on" in target.items:
        values["lookahead_on"] = g["lookahead"] > 0
        if g["lookahead"] > 0:
            bands = [MBand(**{**b.__dict__, "lookahead": min(g["lookahead"], 20.0)}) for b in bands]
    if g.get("auto_gain"):
        notes.append(f"auto_gain on: no analogue in {target.plugin}")
    return values, bands, placed


def write_mbands(payload: bytes, m, bands: list[MBand]) -> bytes:
    """A third-party's band layout written: the bands in order, the rest of the layout unused;
    a band's attack, release, knee and lookahead only when it carries them."""
    raw, lay = m.raw, m.raw["bands"]
    if len(bands) > lay["count"]:
        raise ValueError(f"{m.plugin} has {lay['count']} bands, not {len(bands)}")
    curves = {k: tuple((float(y), float(x)) for x, y in v) for k, v in raw["curves"].items()}
    log = raw.get("frequency") == "log2"
    by_id: dict[int, float] = {}
    for n in range(lay["count"]):
        base = n * lay["stride"]
        if n >= len(bands):
            by_id[base + lay["state"]] = float(raw["states"].index("unused"))
            continue
        b = bands[n]
        by_id.update({base + lay["state"]: float(raw["states"].index("enabled" if b.on else "disabled")),
                      base + lay["low"]: math.log2(b.low) if log else b.low,
                      base + lay["high"]: math.log2(b.high) if log else b.high,
                      base + lay["mode"]: float(raw["modes"].index(b.mode)),
                      base + lay["threshold"]: interp(curves["threshold"], b.threshold),
                      base + lay["ratio"]: interp(curves["ratio"], b.ratio),
                      base + lay["level"]: b.level})
        if b.range is not None:
            by_id[base + lay["range"]] = max(-30.0, min(30.0, b.range))
        if b.time_unit == "%" and b.attack is not None and b.release is not None:
            by_id[base + lay["attack"]], by_id[base + lay["release"]] = b.attack, b.release
        if b.knee is not None:
            by_id[base + lay["knee"]] = b.knee
        if b.lookahead is not None:
            by_id[base + lay["lookahead"]] = b.lookahead
    plist = _state(payload, m, plist=True)
    return replace_data(payload, "data", patch_pairs(plist["data"], by_id))


def _state(payload: bytes, m, plist: bool = False):
    found = next((pl for _off, pl in find_au_plists(payload) if "manufacturer" in pl), None)
    if found is None or not isinstance(found.get("data"), bytes):
        raise ValueError(f"{m.plugin}: the slot holds no AU state with id/value pairs")
    return found if plist else parse_au_state(found)


def _step(value: float, step: float | None) -> float:
    return round(value, 3) if not step else round(math.floor(value / step + 0.5 + 1e-9) * step, 6)
