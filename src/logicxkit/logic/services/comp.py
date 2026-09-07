"""Logic Compressor — threshold..auto-release <-> spec.

float layout: [0] opaque; [1] Threshold dB; [2] Ratio; [3] Attack ms; [4] Release ms;
[5] Gain dB; [6] Knee; [7] Peak/RMS (0=peak,1=rms); [8] Auto Gain; [9] Output Dist;
[10] Circuit Type; [11] Lim Threshold; [12] Limiter; [13] Auto Release.
We patch [1..13]; [0] and [14:] are left as the template has them.
"""

from __future__ import annotations

CIRCUITS = {
    "Platinum": 0, "ClassicVCA": 1, "VintageVCA": 2, "VintageFET": 3,
    "VintageOpto": 4, "FET": 5, "StudioFET": 6, "StudioVCA": 7, "StudioOpto": 8,
}
CIRCUITS_INV = {v: k for k, v in CIRCUITS.items()}


def build_comp(comp_spec: dict) -> list[float]:
    """Returns floats[0..13] (14 values). float[0] is 0.0 (opaque, matches factory)."""
    c = comp_spec
    circ = c.get("circuit", "Platinum")
    if circ not in CIRCUITS:
        raise ValueError(f"unknown circuit '{circ}' (valid: {list(CIRCUITS)})")
    return [
        0.0,                                   # [0] opaque
        float(c["threshold"]),                 # [1]
        float(c["ratio"]),                     # [2]
        float(c["attack"]),                    # [3]
        float(c["release"]),                   # [4]
        float(c.get("gain", 0.0)),             # [5]
        float(c.get("knee", 0.5)),             # [6]
        float(c.get("peak_rms", 0.7)),         # [7]
        float(c.get("auto_gain", 0)),          # [8]
        float(c.get("output_dist", 0)),        # [9]
        float(CIRCUITS[circ]),                 # [10]
        float(c.get("limiter_threshold", 0)),  # [11]
        float(c.get("limiter", 0)),            # [12]
        float(c.get("auto_release", 0)),       # [13]
    ]


def decode_comp(floats: list[float]) -> dict:
    return {
        "circuit": CIRCUITS_INV.get(int(round(floats[10])), int(round(floats[10]))),
        "threshold": round(floats[1], 2),
        "ratio": round(floats[2], 2),
        "attack": round(floats[3], 2),
        "release": round(floats[4], 2),
        "gain": round(floats[5], 2),
        "knee": round(floats[6], 3),
        "peak_rms": round(floats[7], 3),
        "auto_gain": int(round(floats[8])),
        "auto_release": int(round(floats[13])),
    }
