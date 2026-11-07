"""An instrument donor written into Inst 1's slot 1 and re-saved by Logic: every record of that
channel comes back as written, the stamped slot included. What Logic rewrote on load is the other
instrument channel's two archives (Inst 2, Logic's own Klopfgeist): the 16-byte instance id each
ends in, a version-1 UUID it mints again (`instrument-quick-sampler-stamped-resave-logic`). The written
copy is a stored output (`replace-plugin --at 1` with a harvested donor the package does not ship);
the writer is not re-run here, so this pins what Logic does with it, not the writer."""

import unittest

import _goldens

from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

OURS, LOGICS = "instrument-quick-sampler-stamped-ours", "instrument-quick-sampler-stamped-resave-logic"
ID_LEN = 16


def records_of(data: bytes, channel: str) -> dict[int, bytes]:
    """The channel's `UCuA` payloads by key."""
    owner = next(o for o, c in channels(data).items() if c.label == channel)
    return {r.key: r.raw[HEADER:] for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner}


@_goldens.needs(OURS, LOGICS)
class StampedInstrumentTest(unittest.TestCase):
    def test_the_written_channel_comes_back_as_written(self):
        ours, logics = project_data(_goldens.path(OURS)), project_data(_goldens.path(LOGICS))
        self.assertEqual(records_of(ours, "Inst 1"), records_of(logics, "Inst 1"))

    def test_logic_rewrites_the_other_instruments_archive_ids_alone(self):
        ours, logics = records_of(project_data(_goldens.path(OURS)), "Inst 2"), records_of(project_data(_goldens.path(LOGICS)), "Inst 2")
        self.assertEqual(sorted(ours), sorted(logics))
        differ = sorted(k for k in ours if ours[k] != logics[k])
        self.assertEqual(len(differ), 2)
        for key in differ:
            mine, theirs = ours[key], logics[key]
            self.assertEqual(mine[:-ID_LEN], theirs[:-ID_LEN])
            self.assertNotEqual(mine[-ID_LEN:], theirs[-ID_LEN:])
            self.assertEqual(theirs[-ID_LEN + 6] >> 4, 1)             # a version-1 UUID
            self.assertEqual(mine[-ID_LEN + 6] >> 4, 1)

    def test_the_instrument_is_still_the_donor(self):
        names = [r.name for r, _p in slot_payloads(project_data(_goldens.path(LOGICS))) if r.channel == "Inst 1"]
        self.assertEqual(names, ["Quick Sampler"])


if __name__ == "__main__":
    unittest.main()
