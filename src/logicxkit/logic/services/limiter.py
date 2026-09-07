"""Logic Limiter — parameter model.

Float index == Apple's own parameterID (from Logic's `Limiter.plist` GUI descriptor, and
corroborated against the factory preset corpus):

  [1] Gain dB · [2] Lookahead ms · [3] Softknee · [4] Release ms · [5] Output Level dB
  [6] Gain Reduction · [7] True Peak Detection · [8] Mode

Blocks vary in length across Logic versions (6..13 floats) as parameters were appended;
Logic reads a short block fine, so callers patch only as many values as the target holds.
"""

from __future__ import annotations

MODES = {"Legacy": 0, "Precision": 1}
MODES_INV = {v: k for k, v in MODES.items()}

# Logic's factory default, for any value the caller does not set.
_DEFAULTS = {"gain": 0.0, "lookahead": 5.0, "softknee": 1, "release": 250.0,
             "ceiling": 0.0, "gain_reduction": 0.0, "true_peak": 1, "mode": "Precision"}


def build_limiter(spec: dict) -> list[float]:
    """Returns floats[0..12]; index 0 and 9-12 are always 0.0 in Logic-written states."""
    v = {**_DEFAULTS, **spec}
    if v["mode"] not in MODES:
        raise ValueError(f"unknown limiter mode '{v['mode']}' (valid: {list(MODES)})")
    return [
        0.0,
        float(v["gain"]),            # [1]
        float(v["lookahead"]),       # [2]
        float(v["softknee"]),        # [3]
        float(v["release"]),         # [4]
        float(v["ceiling"]),         # [5]
        float(v["gain_reduction"]),  # [6]
        float(v["true_peak"]),       # [7]
        float(MODES[v["mode"]]),     # [8]
        0.0, 0.0, 0.0, 0.0,
    ]


def decode_limiter(floats: list[float]) -> dict:
    def at(i: int, default: float = 0.0) -> float:
        return floats[i] if i < len(floats) else default

    return {
        "gain": round(at(1), 2),
        "lookahead": round(at(2), 2),
        "softknee": int(round(at(3))),
        "release": round(at(4), 2),
        "ceiling": round(at(5), 2),
        "true_peak": int(round(at(7))),
        "mode": MODES_INV.get(int(round(at(8))), int(round(at(8)))),
    }
