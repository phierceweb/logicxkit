"""Logic Channel EQ — 8 bands + master gain <-> human-readable spec.

Per band: ``[Q_or_unused, enable, freq_hz, gain_dB_or_slope]``. 8 bands in a fixed order,
then ``float[32]`` = Master Gain (dB). For ``hpf``/``lpf`` the 4th float is the slope.
"""

from __future__ import annotations

BAND_ORDER = ["hpf", "low_shelf", "peak1", "peak2", "peak3", "peak4", "high_shelf", "lpf"]

# Logic's flat default per band: (Q, enable, freq, gain/slope)
EQ_FLAT = {
    "hpf":        (0.00, 0.0,    20.0, 4.0),
    "low_shelf":  (0.71, 1.0,    75.0, 0.0),
    "peak1":      (1.00, 1.0,   100.0, 0.0),
    "peak2":      (0.60, 1.0,   250.0, 0.0),
    "peak3":      (0.30, 1.0,   750.0, 0.0),
    "peak4":      (0.30, 1.0,  2500.0, 0.0),
    "high_shelf": (0.20, 1.0,  7500.0, 0.0),
    "lpf":        (1.00, 0.0, 20000.0, 4.0),
}
EQ_MASTER_DEFAULT = 0.71
FILTER_BANDS = {"hpf", "lpf"}


def build_eq(eq_spec: dict) -> list[float]:
    """eq_spec: {role: {freq, gain?, q?, slope?}, ..., master_gain?}. Returns 33 floats."""
    eq_spec = dict(eq_spec)
    master = float(eq_spec.pop("master_gain", EQ_MASTER_DEFAULT))
    bands = {role: list(EQ_FLAT[role]) for role in BAND_ORDER}

    for role, p in eq_spec.items():
        if role not in bands:
            raise ValueError(f"unknown EQ band '{role}' (valid: {BAND_ORDER})")
        if role in FILTER_BANDS:
            bands[role] = [0.0, 1.0, float(p["freq"]), float(p.get("slope", 4))]
        else:
            bands[role] = [float(p.get("q", EQ_FLAT[role][0])), 1.0,
                           float(p["freq"]), float(p.get("gain", 0.0))]

    out: list[float] = []
    for role in BAND_ORDER:
        out += bands[role]
    out.append(master)
    return out  # 33 floats


def decode_eq(floats: list[float]) -> dict:
    """Inverse of build_eq: a clean spec of only the active/changed bands."""
    spec: dict = {}
    for i, role in enumerate(BAND_ORDER):
        q, en, freq, gain = floats[i * 4: i * 4 + 4]
        if en <= 0.5:
            continue
        if role in FILTER_BANDS:
            spec[role] = {"freq": round(freq, 1), "slope": round(gain, 1)}
        elif abs(gain) > 0.001:
            spec[role] = {"freq": round(freq, 1), "gain": round(gain, 2), "q": round(q, 3)}
    if len(floats) > 32 and abs(floats[32] - EQ_MASTER_DEFAULT) > 0.001:
        spec["master_gain"] = round(floats[32], 3)
    return spec
