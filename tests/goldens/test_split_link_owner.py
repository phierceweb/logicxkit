"""The split-link word in Logic's own saves: its re-save of a copy this tool cut kept the words as
written, and its own later save of a set reads 0 on every record."""

import struct
import unittest

import _goldens

from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.regions.audio_regions import REGION_TAG
from logicxkit.logic.services.regions.region_edit import NO_LINK, SPLIT_LINK_FROM_END
from logicxkit.logic.services.stream.stream import project_records


def link_words(key: str) -> list[int]:
    return [struct.unpack_from("<I", r.raw, len(r.raw) - SPLIT_LINK_FROM_END)[0]
            for r in project_records(first_project_data(_goldens.path(key))) if r.tag == REGION_TAG]


@_goldens.needs("arrangement-gaps-resave", "live-set-pieces")
class LogicKeepsTheWordTest(unittest.TestCase):
    def test_logic_re_saved_our_words_as_written_and_its_own_later_save_reads_zero(self):
        words = link_words("arrangement-gaps-resave")
        self.assertTrue({NO_LINK, 1, 0xFFFFFF01} <= set(words))
        later = set(link_words("live-set-pieces"))
        self.assertEqual(later, {0})


if __name__ == "__main__":
    unittest.main()
