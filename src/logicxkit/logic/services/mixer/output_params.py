"""The four output plug-ins' float blocks — Linear Phase EQ, Multipressor, Adaptive Limiter,
Limiter — as far as Logic's own one-knob saves pin them.

Each table maps a parameter name to its index in the `GAMETSPP` float block. Only measured
indices are listed, except Linear Phase EQ's bands, which follow the measured band from
index 1 in four floats per band: `[enable, freq_hz, gain_db, q]` (Low Cut's enable, Peak 3's
frequency, gain and Q measured; the default frequency ladder at every fourth index confirms
the stride). A cut band has no gain: its third float is the slope order, dB/Oct ÷ 6 (2.0 for
the default 12 dB/Oct low cut, 4.0 for the 24 dB/Oct high cut).
"""

from __future__ import annotations

LINEAR_PHASE_EQ, MULTIPRESSOR, ADAPTIVE_LIMITER, LIMITER = 243, 194, 193, 199

BAND_ORDER = ["low_cut", "low_shelf", "peak1", "peak2", "peak3", "peak4", "high_shelf", "high_cut"]
BAND_FIELDS = ("enable", "freq", "gain", "q")
CUT_FIELDS = ("enable", "freq", "slope", "q")
CUT_BANDS = ("low_cut", "high_cut")
BAND_FIRST = 1                                   # float 0 precedes the bands (not measured)


def band_fields(band: str) -> tuple[str, ...]:
    return CUT_FIELDS if band in CUT_BANDS else BAND_FIELDS


def lpeq_index(band: str, field: str) -> int:
    if band not in BAND_ORDER or field not in band_fields(band):
        raise ValueError(f"no Linear Phase EQ parameter {band!r}.{field!r}")
    return BAND_FIRST + 4 * BAND_ORDER.index(band) + band_fields(band).index(field)


PARAMS: dict[int, dict[str, int]] = {
    LINEAR_PHASE_EQ: {f"{band}_{field}": lpeq_index(band, field) for band in BAND_ORDER for field in band_fields(band)},
    MULTIPRESSOR: {"band1_threshold": 41, "band1_ratio": 42, "band1_makeup": 43, "xover_1_2": 25},
    ADAPTIVE_LIMITER: {"gain": 2, "out_ceiling": 3, "lookahead": 5, "remove_dc": 6},
    LIMITER: {"gain": 1, "lookahead": 2, "release": 4, "output_level": 5},
}
FLOATS = {LINEAR_PHASE_EQ: 52, MULTIPRESSOR: 62, ADAPTIVE_LIMITER: 10, LIMITER: 13}
NAMES = {LINEAR_PHASE_EQ: "Linear Phase EQ", MULTIPRESSOR: "Multipressor",
         ADAPTIVE_LIMITER: "Adaptive Limiter", LIMITER: "Limiter"}


def set_params(type_id: int, floats: list[float], spec: dict[str, float | bool]) -> list[float]:
    """``floats`` with every named parameter of ``spec`` written at its measured index."""
    table = PARAMS.get(type_id)
    if table is None:
        raise ValueError(f"plug-in type {type_id} has no parameter table")
    if len(floats) != FLOATS[type_id]:
        raise ValueError(f"{NAMES[type_id]}: {len(floats)} floats, its block holds {FLOATS[type_id]}")
    out = list(floats)
    for name, value in spec.items():
        if name not in table:
            raise ValueError(f"{NAMES[type_id]}: no parameter {name!r} (known: {', '.join(sorted(table))})")
        out[table[name]] = float(value)
    return out


def read_params(type_id: int, floats: list[float]) -> dict[str, float]:
    """Every measured parameter of the block, by name."""
    table = PARAMS.get(type_id, {})
    return {name: floats[i] for name, i in table.items() if i < len(floats)}
