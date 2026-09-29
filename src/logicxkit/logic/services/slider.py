"""One of Logic's own sliders as measured: the (units, value) points of its Controls-view row,
sampled position by position (`automation` in a native map's JSON). A value written between two
sampled positions goes to the nearer one, the value Logic keeps on load. An automation point is
0..1 over the slider: Logic lays it on units floor(value x `per` + `offset`), clamped at the
slider's top — `per` 128 for most rows, the slider's span for a percentage, the Channel EQ's
gains affine — and the slider's own scale gives the value. Without a measured slider a lane is
reported, not guessed."""

from __future__ import annotations

import math

SWITCH_PER = 128.0                     # units per 1.0 for most of Logic's own parameters


def interp(points, x: float) -> float:
    """Piecewise-linear through monotonic ``points``, clamped to their ends."""
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def along(curve, x: float, inverse: bool = False) -> float:
    """Units to value along a slider's (units, value) curve, or value to units; a curve spanning
    over twenty times, like a frequency's, is followed in the log domain."""
    logs = all(v > 0 for _u, v in curve) and curve[-1][1] / min(v for _u, v in curve) > 20
    if inverse:
        return interp(tuple((math.log2(v) if logs else v, u) for u, v in curve), math.log2(x) if logs and x > 0 else x)
    y = interp(tuple((u, math.log2(v) if logs else v) for u, v in curve), x)
    return 2 ** y if logs else y


def slider_curve(m, param: str):
    """The measured (units, value) points of one of Logic's own parameters, or None."""
    table = m.raw.get("automation", {}).get(param)
    return tuple((float(x), float(y)) for x, y in table["units"]) if table and table.get("units") else None


def snap(m, param: str, value: float) -> float:
    """``value`` on the nearer of the two sampled slider positions around it — the value Logic
    keeps, exactly; a tie goes to the lower position (Logic's own choice at a midpoint depends on
    the knob). Between positions not sampled, or unmeasured, the value stays as it is and Logic
    lays it on the slider itself."""
    curve = slider_curve(m, param)
    if curve is None:
        return value
    value = round(value, 4)                                       # a curve's 115.000009 means 115: no float noise decides a tie
    if any(v == value for _u, v in curve):
        return value
    below = max(((u, v) for u, v in curve if v < value), default=None)
    above = min(((u, v) for u, v in curve if v > value), default=None)
    if below and above and above[0] - below[0] == 1:          # both neighbours measured: the nearer value
        down = round(value - below[1], 6) <= round(above[1] - value, 6)
        return round(below[1] if down else above[1], 4)
    unit = round(along(curve, value, inverse=True))            # a gap in the samples: the curve's unit, if sampled
    hit = next((v for u, v in curve if u == unit), None)
    return round(hit, 4) if hit is not None else value


def units_at(value: float, per: float, offset: float, top: float) -> float:
    """The slider units Logic lays a point on: floor(value x per + offset), within the slider."""
    return max(0.0, min(math.floor(value * per + offset + 1e-9), top))


def point_at(units: float, per: float, offset: float = 0.0) -> float:
    """The 0..1 that lands on ``units``: the middle of the unit, so no rounding tips it down
    (a value a hair under a unit, from a point's own quantization, counts as that unit)."""
    return min(1.0, max(0.0, (math.floor(units + 1e-4) + 0.5 - offset) / per))


def point_for(m, param: str, value: float | bool) -> tuple[float, float, float, bool]:
    """A native parameter's own value as its 0..1 point: (point, the slider unit it lands on,
    that unit's value, whether the table sampled that unit — else the value is interpolated).
    A switch is 1.0 or 0.0."""
    if isinstance(value, bool):
        return (1.0 if value else 0.0), (1.0 if value else 0.0), (1.0 if value else 0.0), True
    per, offset, curve = slider_by_name(m, param)
    units = max(0.0, min(float(round(along(curve, value, inverse=True))), curve[-1][0]))
    return point_at(units, per, offset), units, round(along(curve, units), 4), is_linear(curve) or any(u == units for u, _v in curve)


def is_linear(curve) -> bool:
    """A row whose sampled values run at one step per unit (the dB rows): a value between two
    samples is exact, not a guess — every value Logic wrote on one sits on a whole unit of its line
    (`tests/goldens/test_translate_snap.py`)."""
    (u0, v0), (u1, v1) = curve[0], curve[-1]
    if u1 == u0:
        return True
    step = (v1 - v0) / (u1 - u0)
    return all(abs(v - (v0 + step * (u - u0))) <= 1e-6 * max(1.0, abs(v)) for u, v in curve)


def slider_by_name(m, param: str | None) -> tuple[float, float, tuple[tuple[float, float], ...]]:
    """(units per 1.0 of automation, the offset, the slider's (units, value) points)."""
    table = m.raw.get("automation", {}).get(param or "")
    if not table or not table.get("units"):
        raise ValueError(f"{m.plugin} {param}: its slider is not measured for automation; the lane cannot be carried")
    return (float(table.get("per", SWITCH_PER)), float(table.get("offset", 0.0)),
            tuple((float(x), float(y)) for x, y in table["units"]))
