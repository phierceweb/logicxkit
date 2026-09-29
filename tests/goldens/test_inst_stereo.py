"""A stereo instrument channel: the one Logic made itself carries `INST_FRESH_STEREO`, the bytes
`add-track --instrument --stereo` writes. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.binding import channel_label
from logicxkit.logic.services.insert import HEADER, is_mixer_record, project_records
from logicxkit.logicx import project_data

LOGIC = "sessionplayer-track-logic"


@_goldens.needs(LOGIC)
class LogicsStereoInstrumentTest(unittest.TestCase):
    def test_its_one_stereo_instrument_channel_carries_the_set(self):
        from logicxkit.logic.services.channel_alloc import INST_FRESH, INST_FRESH_STEREO
        channels = [r.raw[HEADER:] for r in project_records(project_data(_goldens.path(LOGIC)))
                    if is_mixer_record(r) and channel_label(r.raw[HEADER:]).startswith("Inst ")]
        stereo = [p for p in channels if p[123] == 2]
        self.assertEqual(len(stereo), 1)
        self.assertEqual({at: stereo[0][at] for at in INST_FRESH_STEREO}, INST_FRESH_STEREO)
        for p in channels:
            if p[123] == 1:
                self.assertEqual({at: p[at] for at in INST_FRESH}, INST_FRESH)


if __name__ == "__main__":
    unittest.main()
