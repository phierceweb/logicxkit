"""Logic 13.0's re-saves of the public writer saves and the stock plug-in saves — the bundles the 12.4 campaign
re-saved — staged as `<key>-13-0` beside `<key>` and `<key>-12-4` (2026-11-13: each opened on a slim copy, missing
audio skipped, saved with no change). Each reads as its source through every reader and validates clean. Past the
eleven-twins set, 13.0 rewrites what a save with inserts carries: a channel word (`OCuA +81`, 0 -> 2 on 32 channel
records), the slots' view bytes (`+151`, `+148`), a channel's two trailing keyed archives (regenerated shorter, or
renumbered 14/15 -> 7/8 with the shown-slot word `OCuA +30`/`nCuA +61` lowered on the add-track order save), the state of
the seven plug-ins in `RESTATED` and Pitch Correction's archive four bytes longer; the MIDI FX and utility saves carry
words in the instrument object (`ivnE +386..391`) and one save a lane value word (`vEuA +48..50`) 13.0 recomputes.
Skips without the public corpus."""

import json
import unittest
from collections import Counter

import _goldens
from goldens.test_logic_12_4 import VIEW_AT, VIEW_BIT, reading
from goldens.test_logic_13_0_twins import CHURN, allowed, paired

from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.stream.validate import file_format, validate_project
from logicxkit.logicx import project_data

SUFFIX, TWIN = "-13-0", "-12-4"
NEW_RECORDS, REPAIRED = {b"gnnT", b"ktSU"}, {b"karT"}                 # 13.0's two records; track lists pair positionally
RESIZED = {b"gnoS", b"MroC", b"UCuA"}
# past the view bytes and the archive stamps `allowed` masks; 12.4 also restated Space Designer and Neutron, whose
# 13.0 archives differ in their trailing stamps alone
RESTATED = {"Pedalboard", "ChromaVerb", "Tuner", "Remix FX", "Beat Breaker", "Multipressor", "Soni/sGat"}
LONGER = {"Pitch Correction": 4}
VIEW_BYTES = {148, VIEW_AT}
CHANNEL_WORD = {b"OCuA": {81}}
CHANNEL_WORDS_SET = 32
RENUMBERED = "addtrack-order-logic"                                     # trailing archives 14/15 -> 7/8, the shown-slot word lowered
BEYOND = {RENUMBERED: {b"OCuA": {30}, b"nCuA": {61}},
          "autoset-mb-resave-logic": {b"vEuA": {48, 49, 50}},
          "stockfx-mfx-defaults": {b"ivnE": set(range(386, 392))},
          "stockfx-mfx-mono": {b"ivnE": set(range(386, 392))},
          "stockfx-mfx-spots": {b"ivnE": set(range(386, 392))},
          "stockfx-util-mono": {b"ivnE": set(range(386, 389))},
          "stockfx-util-spots": {b"ivnE": set(range(386, 391))}}
RESTATED_ARCHIVES = {"slots-remove-logic": {(1, 10)}}                  # an archive the reader lists as no slot
# (12.x length, 13.0 length) of every unnamed keyed archive 13.0 regenerated — a channel's two trailing ones — and how
# many records each pair covers over the twins
UNNAMED_RESIZED = Counter({(1342, 907): 20, (2787, 303): 20, (1342, 1323): 2, (1428, 1441): 2, (1051, 649): 1, (1151, 1188): 1,
                           (1234, 803): 1, (1261, 803): 1, (1286, 855): 1, (1391, 1428): 1, (1392, 907): 1, (1478, 965): 1,
                           (1549, 1014): 1, (1659, 1118): 1, (1685, 1118): 1, (1753, 303): 1, (3181, 303): 1, (3613, 2721): 1,
                           (4001, 303): 1, (5069, 303): 1, (5232, 303): 1, (5321, 2721): 1, (5357, 303): 1, (6151, 303): 1,
                           (6278, 303): 1, (19022, 303): 1})


def pairs() -> list[tuple[str, str]]:
    """(13.0 key, its source) over the public manifest alone (the owner's twins have their own golden): the
    sources the 12.4 campaign re-saved."""
    known = {k for k, e in json.loads(_goldens.PUBLIC.read_text()).items() if isinstance(e, dict) and "path" in e}
    return sorted((k, k[:-len(SUFFIX)]) for k in known
                  if k.endswith(SUFFIX) and k[:-len(SUFFIX)] in known and k[:-len(SUFFIX)] + TWIN in known)


def slots(data: bytes) -> dict[tuple[int, int], str]:
    """(channel owner, slot key) -> plug-in name for every slot the reader lists."""
    owner_of = {c.label: o for o, c in channels(data).items()}
    return {(owner_of[r.channel], r.key): r.name for r, _p in slot_payloads(data)}


class Logic130PublicTwinsTest(unittest.TestCase):
    def found(self) -> list[tuple[str, str]]:
        out = [(k, s) for k, s in pairs() if _goldens.path(k) is not None and _goldens.path(s) is not None]
        if not out:
            self.skipTest("no public corpus")
        return out

    def test_the_twins_are_staged(self):
        self.assertGreaterEqual(len(self.found()), 93)

    def test_each_twin_reads_as_its_source(self):
        for key, source in self.found():
            with self.subTest(key):
                data = project_data(_goldens.path(key))
                self.assertEqual(file_format(data), 2514)
                self.assertEqual(reading(key), reading(source))
                self.assertEqual(validate_project(data), [])

    def test_the_records_differ_in_the_measured_ways_alone(self):
        words_set, restated, unnamed = 0, set(), Counter()
        for key, source in self.found():
            with self.subTest(key):
                base = project_data(_goldens.path(source))
                same, added, removed = paired(source, key)
                archives = {b"UCuA"} if key == RENUMBERED + SUFFIX else set()
                self.assertLessEqual({r.tag for r in added} - CHURN, NEW_RECORDS | REPAIRED | archives)
                self.assertLessEqual({r.tag for r in removed} - CHURN, REPAIRED | archives)
                self.assertEqual(sum(r.tag == b"karT" for r in added), sum(r.tag == b"karT" for r in removed))
                if archives:
                    self.assertEqual(sorted((r.key, len(r.raw)) for r in removed if r.tag == b"UCuA"), [(14, 2823), (15, 1378)])
                    self.assertEqual(sorted((r.key, len(r.raw)) for r in added if r.tag == b"UCuA"), [(7, 2823), (8, 1378)])
                named, beyond = slots(base), BEYOND.get(source, {})
                for ra, rb in same:
                    if ra.tag in CHURN | {b"gnoS"}:
                        continue
                    old, new = ra.raw[HEADER:], rb.raw[HEADER:]
                    if len(old) != len(new):
                        self.assertIn(ra.tag, RESIZED | ({b"OCuA"} if key == RENUMBERED + SUFFIX else set()), (ra.tag, ra.owner, ra.key))
                        if ra.tag == b"UCuA":
                            name = named.get((ra.owner, ra.key))
                            if name is None:
                                self.assertIn((len(old), len(new)), UNNAMED_RESIZED, (ra.owner, ra.key))
                                unnamed[(len(old), len(new))] += 1
                            else:
                                self.assertEqual(len(new) - len(old), LONGER.get(name), (name, len(old), len(new)))
                        continue
                    stray = {i for i in range(len(old)) if old[i] != new[i] and not allowed(ra.tag, old, new, i)}
                    if not stray:
                        continue
                    if ra.tag == b"UCuA":
                        name = named.get((ra.owner, ra.key))
                        if stray - VIEW_BYTES:
                            if name is None:
                                self.assertIn((ra.owner, ra.key), RESTATED_ARCHIVES.get(source, set()), (ra.owner, ra.key))
                            else:
                                self.assertIn(name, RESTATED, (name, sorted(stray)[:8]))
                                restated.add(name)
                        if VIEW_AT in stray:
                            self.assertEqual(old[VIEW_AT] - new[VIEW_AT], VIEW_BIT, name)
                        continue
                    allowed_here = beyond.get(ra.tag, set()) | CHANNEL_WORD.get(ra.tag, set())
                    self.assertLessEqual(stray, allowed_here, (ra.tag, ra.owner, ra.key, sorted(stray)[:12]))
                    if ra.tag == b"OCuA" and 81 in stray:
                        self.assertEqual((old[81], new[81]), (0, 2))
                        words_set += 1
        self.assertEqual(words_set, CHANNEL_WORDS_SET)
        self.assertEqual(restated, RESTATED)
        self.assertEqual(unnamed, UNNAMED_RESIZED)

    def test_every_slot_keeps_its_place_and_name(self):
        for key, source in self.found():
            with self.subTest(key):
                mine, was = (slot_payloads(project_data(_goldens.path(k))) for k in (key, source))
                self.assertEqual([(r.channel, r.key, r.name) for r, _p in mine], [(r.channel, r.key, r.name) for r, _p in was])


if __name__ == "__main__":
    unittest.main()
