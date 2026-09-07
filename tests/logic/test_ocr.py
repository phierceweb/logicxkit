"""WindowImage OCR: Vision-runner parsing + fader-row extraction from text items."""
import json
import unittest

from logicxkit.logic.services.ocr import OcrClient, OcrError, fader_row

CANNED = json.dumps({
    "image": "/tmp/x.jpg", "width": 2056, "height": 1263, "count": 5,
    "items": [
        {"text": "1.8", "conf": 1.0, "x": 0.196, "y": 0.180, "w": 0.01, "h": 0.01},
        {"text": "-9.0", "conf": 1.0, "x": 0.228, "y": 0.181, "w": 0.01, "h": 0.01},
        {"text": "-11.3", "conf": 1.0, "x": 0.260, "y": 0.179, "w": 0.01, "h": 0.01},
        {"text": "44.1", "conf": 1.0, "x": 0.497, "y": 0.962, "w": 0.01, "h": 0.01},
        {"text": "Kick In", "conf": 1.0, "x": 0.166, "y": 0.756, "w": 0.03, "h": 0.01},
    ],
})


class FakeRunner:
    def __init__(self, rc=0, out=CANNED, err=""):
        self.rc, self.out, self.err = rc, out, err

    def __call__(self, args, timeout):
        return self.rc, self.out, self.err


class TestOcrClient(unittest.TestCase):
    def test_parses_items(self):
        d = OcrClient(runner=FakeRunner()).ocr_image("/tmp/x.jpg")
        self.assertEqual(d["width"], 2056)
        self.assertEqual(len(d["items"]), 5)

    def test_error_raises(self):
        with self.assertRaises(OcrError):
            OcrClient(runner=FakeRunner(rc=1, out="", err="ERROR: no image")).ocr_image("x")


class TestFaderRow(unittest.TestCase):
    def test_extracts_dominant_db_band_sorted_by_x(self):
        items = json.loads(CANNED)["items"]
        row = fader_row(items)
        self.assertEqual([r["text"] for r in row], ["1.8", "-9.0", "-11.3"])

    def test_isolated_db_token_outside_band_excluded(self):
        items = json.loads(CANNED)["items"]
        row = fader_row(items)
        self.assertNotIn("44.1", [r["text"] for r in row])

    def test_no_db_tokens_is_empty(self):
        self.assertEqual(fader_row([{"text": "Kick", "conf": 1, "x": 0, "y": 0,
                                     "w": 0, "h": 0}]), [])


if __name__ == "__main__":
    unittest.main()
