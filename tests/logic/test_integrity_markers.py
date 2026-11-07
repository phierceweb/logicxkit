"""The gate's flex marker block check, and an object index entry with no name."""

import unittest

from _records import chan, env_obj, uuid
from logic.test_integrity import COUNT, KEYS, KICK, block, project, standard

from logicxkit.logic.services.stream.integrity import regressions, require_no_regression, structural_report
from logicxkit.logic.services.regions.regions import MARKER_KIND_AT
from logicxkit.logic.services.arrange.reorder import move_track


class MarkerBlocksTest(unittest.TestCase):
    def test_a_block_that_lost_its_mark_is_refused_and_named(self):
        entries = standard()
        broken = bytearray(entries[4])
        broken[MARKER_KIND_AT] = 0
        entries[4] = bytes(broken)
        with self.assertRaisesRegex(ValueError, r"marker_blocks: 1 .*object 144 at tick 46080 \(type 0x24\), "
                                                r"marker block 2: 0x88 bytes without the 0xAA mark"):
            require_no_regression(project(standard()), project(entries))

    def test_a_block_cut_short_is_refused(self):
        entries = standard()
        entries[-1] = entries[-1][:40]
        found = regressions(project(standard()), project(entries))
        self.assertIn("marker_blocks: 1", "".join(found))
        self.assertIn("not whole 80-byte chunks", "".join(found))

    def test_blocks_before_the_first_entry_are_refused(self):
        found = regressions(project(standard()), project([block(0)] + standard()))
        self.assertIn("marker block 1 before the first entry", "".join(found))

    def test_a_flexed_entry_losing_its_blocks_is_refused_and_named(self):
        found = regressions(project(standard()), project(standard()[:3]))
        self.assertIn("marker_blocks: 1 flexed entr(ies) lost their marker blocks: "
                      "['object 144 at tick 46080 (type 0x24): 3 -> 0']", found)

    def test_a_midi_entry_gaining_blocks_is_refused(self):
        entries = standard()
        found = regressions(project(entries), project([entries[0], block(0)] + entries[1:]))
        self.assertEqual(found, ["marker_blocks: 1 MIDI entr(ies) gained marker blocks: "
                                 "['object 88 at tick 42240 (type 0x20): 0 -> 1']"])

    def test_an_entry_slipped_between_a_flexed_entry_and_its_blocks_is_refused_twice(self):
        e = standard()
        found = regressions(project(e), project([e[1], e[2], e[0]] + e[3:]))
        self.assertEqual(found, ["marker_blocks: 1 flexed entr(ies) lost their marker blocks: "
                                 "['object 144 at tick 46080 (type 0x24): 3 -> 0']",
                                 "marker_blocks: 1 MIDI entr(ies) gained marker blocks: "
                                 "['object 88 at tick 42240 (type 0x20): 0 -> 3']"])

    def test_audio_block_counts_changing_or_growing_from_zero_pass(self):
        e = standard()
        requantized = [e[0], e[1], block(-4410), block(0), e[2], block(-13230), block(44100)]
        self.assertEqual(regressions(project(e), project(requantized)), [])

    def test_hit_targets_that_stop_rising_are_refused_and_named(self):
        for name, target in (("backwards", -1), ("repeated", 0)):
            entries = standard()
            entries[5] = block(44100, target)
            with self.subTest(name), self.assertRaisesRegex(
                    ValueError, r"marker_blocks: 1 .*object 144 at tick 46080 \(type 0x24\), marker block 3: "
                                r"target at or before the previous hit's"):
                require_no_regression(project(standard()), project(entries))

    def test_a_broken_block_the_input_had_stays_silent(self):
        entries = standard()
        entries[5] = entries[5][:MARKER_KIND_AT] + b"\0" + entries[5][MARKER_KIND_AT + 1:]
        data = project(entries)
        self.assertEqual(len(structural_report(data)["marker_blocks"]), 1)
        self.assertEqual(regressions(data, move_track(data, KEYS, before=KICK, track_count=COUNT)), [])


class NamelessObjectIndexTest(unittest.TestCase):
    def test_the_index_of_an_object_whose_name_does_not_decode_is_checked(self):
        nameless = (env_obj(500, b"Gitarre \xfc"), chan(272, "Audio 1", uuid=uuid(500)))
        data = project(standard(), extra=nameless)
        report = structural_report(data)
        self.assertIsNone(report["unreadable"])
        self.assertEqual(report["bad_object_index"], [500])


if __name__ == "__main__":
    unittest.main()
