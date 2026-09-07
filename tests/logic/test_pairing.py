"""Pairing template rows with session rows: object id first, then label, then a unique name."""

import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.pairing import extra_rows, format_map, pair_rows, parse_map, propose_map, row_key


def row(key, oid, name, label, member=False, grouping=False):
    return {"key": key, "object_id": oid, "name": name, "label": label, "member": member,
            "grouping": grouping, "colour": 16, "hidden": False, "owner": None, "stack_index": 0}


TEMPLATE = [row(0, 192, "Drums", "Sub 1", grouping=True), row(1, 88, "Kick In", "Audio 1", True),
            row(2, 92, "Snare", "Audio 3", True), row(3, 504, "Vox", "Audio 20"), row(4, 80, "Master", "Output 1-2")]


class PairTest(unittest.TestCase):
    def test_same_ids_pair_by_object(self):
        session = [row(0, 192, "Drums", "Sub 1", grouping=True), row(1, 88, "Kick In", "Audio 1", True),
                   row(2, 92, "Snare Top", "Audio 3", True), row(3, 504, "Vox", "Audio 20"), row(4, 80, "Master", "Output 1-2")]
        pairs = pair_rows(TEMPLATE, session)
        self.assertEqual([(p.template["name"], p.session["name"], p.rule) for p in pairs],
                         [("Drums", "Drums", "object"), ("Kick In", "Kick In", "object"),
                          ("Snare", "Snare Top", "object"), ("Vox", "Vox", "object"), ("Master", "Master", "object")])

    def test_a_reused_id_that_agrees_on_nothing_falls_back_to_the_label(self):
        session = [row(0, 192, "Drums", "Sub 1", grouping=True), row(1, 88, "Kick In", "Audio 1", True),
                   row(2, 92, "Guitar", "Audio 7", True), row(3, 300, "Snare", "Audio 3"), row(4, 80, "Master", "Output 1-2")]
        pairs = {p.template["name"]: p for p in pair_rows(TEMPLATE, session)}
        self.assertEqual((pairs["Snare"].session["object_id"], pairs["Snare"].rule), (300, "label"))
        self.assertEqual((pairs["Vox"].session, pairs["Vox"].rule), (None, "missing"))
        self.assertEqual([r["name"] for r in extra_rows(list(pairs.values()), session)], ["Guitar"])

    def test_a_known_row_pairs_first_whatever_it_is_called(self):
        session = [row(0, 700, "Drums", "Aux 1"), row(1, 900, "Drums", "Aux 9")]
        template = [row(0, 300, "Drums", "Aux 2")]
        self.assertEqual([p.session for p in pair_rows(template, session)], [None])
        pairs = pair_rows(template, session, known={900: 0})
        self.assertEqual([(p.session["object_id"], p.rule) for p in pairs], [(900, "made")])

    def test_two_template_rows_with_one_name_and_label_each_keep_their_own_made_row(self):
        template = [row(0, 504, "Vox", "Audio 20"), row(1, 504, "Vox", "Audio 20")]
        session = [row(0, 900, "Vox", "Audio 30"), row(1, 901, "Vox", "Audio 31")]
        pairs = pair_rows(template, session, known={900: 0, 901: 1})
        self.assertEqual([(p.template["key"], p.session["object_id"], p.rule) for p in pairs],
                         [(0, 900, "made"), (1, 901, "made")])

    def test_a_row_the_map_leaves_alone_is_claimed_by_no_rule(self):
        session = [row(0, 88, "Vox Double", "Audio 1"), row(1, 504, "Vox", "Audio 20")]
        template = [row(0, 88, "Kick In", "Audio 1"), row(1, 504, "Vox", "Audio 20")]
        by_object = pair_rows(template, session)
        self.assertEqual([(p.template["name"], p.rule) for p in by_object], [("Kick In", "object"), ("Vox", "object")])
        forced = parse_map("Vox Double (Audio 1) -> (none)\nVox (Audio 20) -> Vox (Audio 20)\n")
        self.assertEqual(forced, {"Vox Double (Audio 1)": None, "Vox (Audio 20)": "Vox (Audio 20)"})
        pairs = pair_rows(template, session, forced=forced)
        self.assertEqual([(p.template["name"], p.session and p.session["name"], p.rule) for p in pairs],
                         [("Kick In", None, "missing"), ("Vox", "Vox", "map")])

    def test_a_unique_name_pairs_last_and_a_duplicate_does_not(self):
        session = [row(0, 700, "Drums", "Sub 4", grouping=True), row(1, 701, "Kick In", "Audio 9", True),
                   row(2, 702, "Vox", "Audio 21"), row(3, 703, "Vox", "Audio 22"), row(4, 80, "Master", "Output 1-2")]
        pairs = {p.template["name"]: p for p in pair_rows(TEMPLATE, session)}
        self.assertEqual((pairs["Kick In"].session["object_id"], pairs["Kick In"].rule), (701, "name"))
        self.assertEqual(pairs["Vox"].rule, "missing")
        self.assertEqual(pairs["Drums"].rule, "name")

    def test_template_order_is_kept(self):
        session = list(reversed(TEMPLATE))
        self.assertEqual([p.template["key"] for p in pair_rows(TEMPLATE, session)], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()


class MatchQualityTest(unittest.TestCase):
    def _rows(self, n, *, offset=0, names=None):
        return [{"key": i, "object_id": 100 + i + offset,
                 "name": (names[i] if names else f"T{i}"), "label": f"Audio {i + 1}"}
                for i in range(n)]

    def test_a_session_cut_from_the_template_scores_one(self):
        from logicxkit.logic.services.pairing import match_quality, pair_rows
        rows = self._rows(8)
        self.assertEqual(match_quality(pair_rows(rows, list(rows))), 1.0)

    def test_an_unrelated_project_scores_near_zero(self):
        from logicxkit.logic.services.pairing import match_quality, pair_rows
        template = self._rows(8)
        session = self._rows(8, offset=900, names=[f"X{i}" for i in range(8)])
        self.assertEqual(match_quality(pair_rows(template, session)), 0.0)

    def test_a_few_hand_added_tracks_still_score_high(self):
        from logicxkit.logic.services.pairing import match_quality, pair_rows
        template = self._rows(20)
        session = [dict(r) for r in template]
        for r in session[:2]:
            r["object_id"] += 5000        # two rows re-made since the cut
        self.assertGreater(match_quality(pair_rows(template, session)), 0.85)

    def test_no_rows_is_zero_not_a_crash(self):
        from logicxkit.logic.services.pairing import match_quality
        self.assertEqual(match_quality([]), 0.0)


class MapTest(unittest.TestCase):
    LEGACY = [row(0, 700, "Drums", "Sub 1", grouping=True), row(1, 701, "Guitar 1", "Audio 1", True),
              row(2, 702, "Vox 1", "Audio 4"), row(3, 703, "Bass", "Audio 3"), row(4, 704, "Stereo Out", "Output 1-2")]
    TEMPLATE = [row(0, 192, "Drums", "Sub 1", grouping=True), row(1, 88, "Gtr 1 DI", "Audio 20", True),
                row(2, 89, "Gtr 1 Amp", "Audio 25", True), row(3, 92, "Bass DI", "Audio 17"), row(4, 93, "Bass Amp", "Audio 18"),
                row(5, 504, "Lead Vox", "Audio 23"), row(6, 80, "Master", "Output 1-2")]

    def test_proposal_prefers_same_name_then_the_di_then_gives_up(self):
        got = {e["session"]: (e["template"], e["confidence"]) for e in propose_map(self.TEMPLATE, self.LEGACY)}
        self.assertEqual(got["Drums (Sub 1)"], ("Drums (Sub 1)", "high"))
        self.assertEqual(got["Guitar 1 (Audio 1)"], ("Gtr 1 DI (Audio 20)", "medium"))
        self.assertEqual(got["Bass (Audio 3)"], ("Bass DI (Audio 17)", "medium"))
        self.assertEqual(got["Stereo Out (Output 1-2)"], ("Master (Output 1-2)", "high"))
        self.assertEqual(got["Vox 1 (Audio 4)"], (None, "none"))

    def test_the_map_file_round_trips_and_a_forced_pair_wins(self):
        text = format_map(propose_map(self.TEMPLATE, self.LEGACY), self.TEMPLATE)
        text = "\n".join(line.replace("-> (none)", "-> Lead Vox (Audio 23)") if line.startswith("Vox 1 (Audio 4)") else line
                         for line in text.splitlines())
        forced = parse_map(text)
        self.assertEqual(forced["Vox 1 (Audio 4)"], "Lead Vox (Audio 23)")
        pairs = {p.template["name"]: p for p in pair_rows(self.TEMPLATE, self.LEGACY, forced=forced)}
        self.assertEqual((pairs["Lead Vox"].session["name"], pairs["Lead Vox"].rule), ("Vox 1", "map"))
        self.assertEqual((pairs["Gtr 1 DI"].session["name"], pairs["Gtr 1 DI"].rule), ("Guitar 1", "map"))
        self.assertEqual(pairs["Gtr 1 Amp"].rule, "missing")
        self.assertEqual([row_key(r) for r in extra_rows(list(pairs.values()), self.LEGACY)], [])

    def test_with_a_map_the_label_rule_is_off(self):
        legacy = [row(0, 900, "Guitar 1", "Audio 1")]
        template = [row(0, 88, "Kick In", "Audio 1")]
        self.assertEqual(pair_rows(template, legacy)[0].rule, "label")
        self.assertEqual(pair_rows(template, legacy, forced={})[0].rule, "missing")

    def test_a_map_naming_a_missing_template_track_is_refused(self):
        session = [row(0, 700, "Vox 1", "Audio 4")]
        with self.assertRaises(ValueError) as cm:
            pair_rows(TEMPLATE, session, forced={"Vox 1 (Audio 4)": "Vox (Audio 21)"})
        self.assertIn("template track that does not exist", str(cm.exception))

    def test_awkward_names_round_trip_through_the_map(self):
        session = [row(0, 700, "Take #2", "Audio 1"), row(1, 701, "#1 Vox", "Audio 4"), row(2, 702, "Gtr", "Audio 9"),
                   row(3, 703, "Vocal Harmony High", "Audio 5")]
        template = [row(0, 88, "Vox", "Audio 20"), row(1, 89, "Gtr -> Amp", "Audio 2"),
                    row(2, 90, "Vocal Harmony High", "Audio 23")]
        entries = [{"session": "Take #2 (Audio 1)", "template": "Vox (Audio 20)", "confidence": "high", "why": "x"},
                   {"session": "#1 Vox (Audio 4)", "template": None, "confidence": "none", "why": "y"},
                   {"session": "Gtr (Audio 9)", "template": "Gtr -> Amp (Audio 2)", "confidence": "medium", "why": "z"},
                   {"session": "Vocal Harmony High (Audio 5)", "template": "Vocal Harmony High (Audio 23)",
                    "confidence": "high", "why": "same name"}]
        text = format_map(entries, template)
        self.assertEqual(parse_map(text), {"Take #2 (Audio 1)": "Vox (Audio 20)", "#1 Vox (Audio 4)": None,
                                           "Gtr (Audio 9)": "Gtr -> Amp (Audio 2)",
                                           "Vocal Harmony High (Audio 5)": "Vocal Harmony High (Audio 23)"})
        pairs = pair_rows(template, session, forced=parse_map(text))
        self.assertEqual([(p.template["name"], p.session and p.session["name"]) for p in pairs],
                         [("Vox", "Take #2"), ("Gtr -> Amp", "Gtr"), ("Vocal Harmony High", "Vocal Harmony High")])

    def test_a_map_naming_a_missing_track_or_a_double_target_is_refused(self):
        with self.assertRaises(ValueError):
            pair_rows(self.TEMPLATE, self.LEGACY, forced={"Nope (Audio 9)": "Bass DI (Audio 17)"})
        with self.assertRaises(ValueError):
            pair_rows(self.TEMPLATE, self.LEGACY, forced={"Bass (Audio 3)": "Bass DI (Audio 17)", "Vox 1 (Audio 4)": "Bass DI (Audio 17)"})


class LeaveOutTest(unittest.TestCase):
    def test_the_proposal_lists_unclaimed_template_tracks_with_a_plus(self):
        from logicxkit.logic.services.pairing import format_map, parse_map_full
        t = [{"key": 0, "name": "Kick In", "label": "Audio 1", "object_id": 1},
             {"key": 1, "name": "Vox", "label": "Audio 2", "object_id": 2}]
        text = format_map([{"session": "Vox (Audio 9)", "template": "Vox (Audio 2)", "confidence": "high", "why": "same name"}], t)
        self.assertIn("\n+ Kick In (Audio 1)\n", text)
        forced, excluded = parse_map_full(text)
        self.assertEqual((forced, excluded), ({"Vox (Audio 9)": "Vox (Audio 2)"}, set()))
        forced, excluded = parse_map_full(text.replace("+ Kick In", "- Kick In"))
        self.assertEqual(excluded, {"Kick In (Audio 1)"})

    def test_a_left_out_template_row_pairs_with_nothing(self):
        from logicxkit.logic.services.pairing import pair_rows
        t = [{"key": 0, "name": "Kick In", "label": "Audio 1", "object_id": 1},
             {"key": 1, "name": "Vox", "label": "Audio 2", "object_id": 2}]
        s = [{"key": 0, "name": "Kick In", "label": "Audio 5", "object_id": 9},
             {"key": 1, "name": "Vox", "label": "Audio 9", "object_id": 8}]
        pairs = pair_rows(t, s, forced={"Vox (Audio 9)": "Vox (Audio 2)"}, excluded={"Kick In (Audio 1)"})
        self.assertEqual([(p.template["name"], p.session["name"]) for p in pairs], [("Vox", "Vox")])
        with self.assertRaises(ValueError):
            pair_rows(t, s, excluded={"Snare (Audio 3)"})

    def test_a_bad_leave_out_line_is_refused(self):
        from logicxkit.logic.services.pairing import parse_map_full
        with self.assertRaises(ValueError):
            parse_map_full("- \n")
        with self.assertRaises(ValueError):
            parse_map_full('- "Kick In (Audio 1)" extra\n')
