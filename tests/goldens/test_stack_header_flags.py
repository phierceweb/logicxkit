"""The stack header row's +40: bit 0x80 is expanded, bit 0x20 selected, and bit 0x40 occurs on
summing headers alone — on no folder header across every 12.4 save on this machine (64 of the public
corpus's 116 summing headers carry it, so it marks something about a summing stack, not a fresh one;
not decoded)."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.stacks import read_stacks
from logicxkit.logic.services.arrange.tracklist import EXPANDED_AT, arrange_run
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import MEASURED_FORMAT, file_format
from logicxkit.logicx import project_data

SUMMING_BIT = 0x40


def _logic_saves() -> list[str]:
    return sorted(k for k, e in _goldens.manifest().items() if isinstance(e, dict)
                  and str(e.get("path", "")).endswith(".logicx") and "logic" in k.split("-"))


class StackHeaderFlagsTest(unittest.TestCase):
    def test_bit_0x40_sits_on_summing_headers_alone(self):
        seen = {"summing": set(), "folder": set()}
        for key in _logic_saves():
            bundle = _goldens.path(key)
            if bundle is None:
                continue
            data = project_data(bundle)
            if file_format(data) != MEASURED_FORMAT:
                continue
            records = project_records(data)
            count = _goldens.manifest()[key].get("facts", {}).get("tracks")
            count = count if isinstance(count, int) else None
            rows = {struct.unpack_from("<I", records[i].raw, HEADER + 8)[0]: records[i].raw for i in arrange_run(records, count)}
            for stack in read_stacks(data, count):
                if stack.object_id in rows:
                    seen[stack.kind].add(rows[stack.object_id][HEADER + EXPANDED_AT] & SUMMING_BIT)
        if not seen["summing"]:
            self.skipTest("no public corpus on this machine")
        self.assertEqual((seen["summing"], seen["folder"]), ({0, SUMMING_BIT}, {0}))


if __name__ == "__main__":
    unittest.main()
