"""On every public Logic save the channel-count record's `+61` equals the shown-slot word every channel record carries
at `+30` — the fact `shown.show_slots` writes (2026-11-13). The writes of this tool staged before then may differ; they
are left out."""

import json
import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG, is_channel_count
from logicxkit.logic.services.mixer.shown import SHOWN_MIRROR_AT
from logicxkit.logic.services.mixer.slots import SHOWN_AT
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data


def logics_saves() -> list[str]:
    public = json.loads(_goldens.PUBLIC.read_text())
    return sorted(k for k, e in public.items() if isinstance(e, dict) and str(e.get("path", "")).endswith(".logicx")
                  and (k.endswith(("-logic", "-12-4")) or (k.endswith("-13-0") and not k.endswith("-ours-13-0"))))


class ShownMirrorGolden(unittest.TestCase):
    def test_the_count_record_copies_the_shown_word_on_every_logic_save(self):
        seen, several = 0, []
        for key in logics_saves():
            path = _goldens.path(key)
            if path is None:
                continue
            records = project_records(project_data(path))
            words = {struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in records
                     if r.tag == CHANNEL_TAG and len(r.raw) - HEADER >= SHOWN_AT + 2}
            counts = [r.raw[HEADER:] for r in records if is_channel_count(r)]
            if len(words) != 1 or len(counts) != 1:
                several.append(key)
                continue
            with self.subTest(key):
                (shown,) = words
                self.assertEqual(counts[0][SHOWN_MIRROR_AT], shown)
            seen += 1
        self.assertEqual(several, [])                           # every Logic save carries one word and one count record
        if not seen:
            self.skipTest("no public corpus")
        self.assertGreater(seen, 300)


if __name__ == "__main__":
    unittest.main()
