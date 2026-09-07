"""WindowImage OCR — Apple Vision via the vendored Swift script.

Vision reads Logic's UI text essentially verbatim (validated against the
hand-read fader table for the Recording template), which makes the
"sends / fader levels are visual-only" layer semi-machine-readable: OCR the
auto-saved ``WindowImage.jpg``, then pull the fader row out of the token
positions. Coordinates are normalized [0, 1] with origin bottom-left
(Vision's convention). Pairing fader values with channel names stays a human
step — the image shows whatever view was open at save, so automatic pairing
could silently mislabel.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from logicxkit.utils.swiftrun import SwiftRunError, native_dir, run_swift, swift_available

from logicxkit.logicx import first_alternative

DB_TOKEN = re.compile(r"^[+-]?\d{1,3}\.\d$")
_Y_TOL = 0.02  # tokens within this normalized-y distance sit on one UI row
_TIMEOUT_S = 180


class OcrError(RuntimeError):
    """OCR failed: missing toolchain/script/image, crash, or bad output."""


def _script() -> Path:
    return native_dir() / "vision_ocr.swift"


def _default_runner(args: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        return run_swift(_script(), list(args), timeout)
    except SwiftRunError as e:
        raise OcrError(str(e)) from e


class OcrClient:
    def __init__(self, runner=None, timeout: float = _TIMEOUT_S):
        self._runner = runner or _default_runner
        self._timeout = timeout

    @staticmethod
    def available() -> bool:
        return swift_available() and _script().exists()

    def ocr_image(self, path: str | Path) -> dict:
        rc, out, err = self._runner([str(path)], self._timeout)
        if rc != 0:
            tail = (err or out).strip().splitlines()
            raise OcrError(tail[-1] if tail else f"ocr exited {rc}")
        start = out.find("{")
        if start < 0:
            raise OcrError(f"unparseable OCR output: {out[:120]!r}")
        try:
            return json.loads(out[start:])
        except json.JSONDecodeError as e:
            raise OcrError(f"bad OCR JSON: {e}") from e

    def ocr_logicx(self, bundle: str | Path) -> dict:
        p = Path(bundle)
        img = p / "Alternatives" / first_alternative(p) / "WindowImage.jpg"
        if not img.exists():
            raise OcrError(f"no WindowImage.jpg in {p}")
        return self.ocr_image(img)


def fader_row(items: list[dict], y_tol: float = _Y_TOL) -> list[dict]:
    """The dominant horizontal band of dB-looking tokens, left-to-right.

    Mixer fader readouts share one y row; stray numeric text elsewhere on
    screen (sample rate, tempo) lands in its own band and is discarded.
    """
    toks = sorted((i for i in items if DB_TOKEN.match(i["text"].strip())),
                  key=lambda i: i["y"])
    if not toks:
        return []
    bands: list[list[dict]] = [[toks[0]]]
    for t in toks[1:]:
        if abs(t["y"] - bands[-1][-1]["y"]) <= y_tol:
            bands[-1].append(t)
        else:
            bands.append([t])
    return sorted(max(bands, key=len), key=lambda i: i["x"])
