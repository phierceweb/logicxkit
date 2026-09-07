"""AU host wrapper: shells to the vendored Swift probe; parses its JSON; degrades safely."""
import json
import unittest

from logicxkit.au.services.host import AuHost, AuHostError, is_headless_safe

CANNED = json.dumps({
    "component": "FabFilter: Pro-C 2", "type": "aufx", "subtype": "FC2p",
    "manufacturer": "FabF", "paramCount": 2,
    "params": [
        {"id": 0, "name": "Threshold", "unit": "generic", "min": -60, "max": 0,
         "default": -18, "value": -6.5, "display": "-6.50 dB"},
        {"id": 1, "name": "Ratio", "unit": "generic", "min": 0, "max": 1,
         "default": 0.6, "value": 0.6, "display": "2.00:1"},
    ],
})


class FakeRunner:
    def __init__(self, rc=0, out=CANNED, err=""):
        self.rc, self.out, self.err = rc, out, err
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append((args, timeout))
        return self.rc, self.out, self.err


class TestAuHost(unittest.TestCase):
    def test_dump_preset_parses_params(self):
        host = AuHost(runner=FakeRunner())
        dump = host.dump_preset("/tmp/x.aupreset")
        self.assertEqual(dump.component, "FabFilter: Pro-C 2")
        self.assertEqual(dump.subtype, "FC2p")
        self.assertEqual(len(dump.params), 2)
        self.assertEqual(dump.params[0].name, "Threshold")
        self.assertEqual(dump.params[0].display, "-6.50 dB")

    def test_changed_params_filters_defaults(self):
        host = AuHost(runner=FakeRunner())
        dump = host.dump_preset("/tmp/x.aupreset")
        changed = dump.changed_params()
        self.assertEqual([p.name for p in changed], ["Threshold"])

    def test_error_raises_with_stderr_tail(self):
        host = AuHost(runner=FakeRunner(rc=1, out="", err="ERROR: component not found"))
        with self.assertRaises(AuHostError) as ctx:
            host.dump_preset("/tmp/x.aupreset")
        self.assertIn("component not found", str(ctx.exception))

    def test_non_json_output_raises(self):
        host = AuHost(runner=FakeRunner(out="objc[123]: mayhem"))
        with self.assertRaises(AuHostError):
            host.dump_preset("/tmp/x.aupreset")


class TestHeadlessDenylist(unittest.TestCase):
    def test_known_crashers_are_denied(self):
        self.assertFalse(is_headless_safe("Soni"))
        self.assertFalse(is_headless_safe("ksWV"))

    def test_normal_manufacturers_allowed(self):
        self.assertTrue(is_headless_safe("FabF"))
        self.assertTrue(is_headless_safe("iZtp"))


if __name__ == "__main__":
    unittest.main()
