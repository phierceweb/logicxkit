"""The lane writer held to Logic's own Event List saves: our events equal Logic's byte for byte
once head +15, the Event List's selection state, is masked, and read back as the same lanes."""

import unittest
import _goldens
from logicxkit.logic.services.regions.automation import FOLDER_NAME, RELATIVE, named, read_automation
from logicxkit.logic.services.regions.automation_write import clear_lane, copy_lane, set_lane
from logicxkit.logic.services.song.events import BAR_ONE, events
from logicxkit.logic.services.arrange.groups import FADER_IDS
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.sequence import sequences
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logicx import project_data

VOLUME, PAN = FADER_IDS["Volume"], FADER_IDS["Pan"]


def _object(data, name):
    return next(r["object_id"] for r in read_tracks(data) if r["name"] == name)


def _folder(data, track_object):
    """The track's automation folder payload: every event line, head +15 (selection) masked."""
    import struct
    records = project_records(data)
    for t in sequences(records):
        q = records[t.start].raw[HEADER:]
        if named(q, FOLDER_NAME) and struct.unpack_from("<I", q, 234)[0] == track_object:
            out = []
            for e in events(records[t.end].raw[HEADER:]):
                h = bytearray(e.head)
                h[15] = 0
                out.append((bytes(h), e.lines))
            return out
    return None


def _lane_events(data, track_object, fader, relative=False):
    """The lane's events on the track's folder, +15 masked, in file order."""
    import struct
    return [h for h, _ls in _folder(data, track_object)
            if h[0] == 0x50 and bool(struct.unpack_from("<H", h, 0)[0] & RELATIVE) == relative and h[12] == fader]


def _lanes(data, track):
    return sorted((ln.parameter, ln.region, tuple(p.position for p in ln.points), tuple(p.value for p in ln.points))
                  for a in read_automation(data) if a.track == track for ln in a.lanes)


@_goldens.needs("automation-pan-point-logic", "automation-pan-two-points-logic", "automation-relative-volume-logic")
class HeldToLogicTest(unittest.TestCase):
    def test_a_pan_lane_matches_logics_event_list_events(self):
        base, logic = project_data(_goldens.path("automation-pan-point-logic")), project_data(_goldens.path("automation-pan-two-points-logic"))
        a2 = _object(base, "Audio 2")
        ours = set_lane(base, a2, PAN, [(BAR_ONE, 40), (BAR_ONE + 3840, 90)])
        self.assertEqual(_lane_events(ours, a2, PAN), _lane_events(logic, a2, PAN))
        self.assertEqual(_lanes(ours, "Audio 2"), _lanes(logic, "Audio 2"))

    def test_a_relative_volume_lane_matches_logics(self):
        base, logic = project_data(_goldens.path("automation-pan-two-points-logic")), project_data(_goldens.path("automation-relative-volume-logic"))
        a2 = _object(base, "Audio 2")
        ours = set_lane(base, a2, VOLUME, [(BAR_ONE, 64), (BAR_ONE + 3840, 64)], relative=True)
        self.assertEqual(_lane_events(ours, a2, VOLUME, True), _lane_events(logic, a2, VOLUME, True))
        self.assertEqual(_lanes(ours, "Audio 2"), _lanes(logic, "Audio 2"))

    def test_copy_and_clear_read_back(self):
        data = project_data(_goldens.path("automation-pan-two-points-logic"))
        a2, a3 = _object(data, "Audio 2"), _object(data, "Audio 3")
        copied = copy_lane(data, a2, a3, PAN)
        self.assertEqual([ln for ln in _lanes(copied, "Audio 3")], [("Pan", False, (38400, 42240), (40.0, 90.0))])
        cleared = clear_lane(copied, a3, PAN)
        self.assertEqual(_lanes(cleared, "Audio 3"), [])
        self.assertEqual(_lanes(cleared, "Audio 2"), _lanes(data, "Audio 2"))

    def test_a_copied_lane_keeps_its_half_tick_point(self):
        """Logic's region-border Volume point sits half a tick before bar 1; the copy keeps it there."""
        data = project_data(_goldens.path("automation-pan-two-points-logic"))
        a2, a3 = _object(data, "Audio 2"), _object(data, "Audio 3")
        copied = copy_lane(data, a2, a3, VOLUME)
        (lane,) = [ln for ln in _lanes(copied, "Audio 3") if ln[0] == "Volume"]
        self.assertEqual(lane[2][:2], (38399.5, 38400.0))
        self.assertEqual(_lane_events(copied, a3, VOLUME), _lane_events(data, a2, VOLUME))

    def test_two_points_at_one_position_are_refused(self):
        data = project_data(_goldens.path("automation-pan-two-points-logic"))
        with self.assertRaises(ValueError):
            set_lane(data, _object(data, "Audio 2"), PAN, [(BAR_ONE, 40), (BAR_ONE, 90)])


@_goldens.needs("automation-shown-logic")
class OnTheBlankTest(unittest.TestCase):
    def test_a_fade_on_an_empty_folder(self):
        data = project_data(_goldens.path("automation-shown-logic"))
        a1 = _object(data, "Audio 1")
        ours = set_lane(data, a1, VOLUME, [(BAR_ONE, 90), (BAR_ONE + 4 * 3840, 60)])
        self.assertEqual(_lanes(ours, "Audio 1"), [("Volume", False, (38400, 53760), (90.0, 60.0))])
        with self.assertRaises(ValueError):
            set_lane(data, 999999, VOLUME, [(BAR_ONE, 90)])


@_goldens.needs("automation-shown-logic", "automation-ours-resave-logic")
class ResaveTest(unittest.TestCase):
    """Logic opened three lanes `--set` wrote onto the blank, listed the six points in its Event
    List as written, and re-saved; the re-save's folder is our write byte for byte — order
    included — but for head +15, the selection state Logic sets on save."""

    def _ours(self):
        data = project_data(_goldens.path("automation-shown-logic"))
        a1 = _object(data, "Audio 1")
        ours = set_lane(data, a1, VOLUME, [(BAR_ONE, 90), (BAR_ONE + 4 * 3840, 60)])
        ours = set_lane(ours, a1, PAN, [(BAR_ONE, 40), (BAR_ONE + 2 * 3840, 90)])
        return a1, set_lane(ours, a1, VOLUME, [(BAR_ONE, 64), (BAR_ONE + 4 * 3840, 80)], relative=True)

    def test_the_resaved_folder_is_our_write_byte_for_byte(self):
        a1, ours = self._ours()
        logic = project_data(_goldens.path("automation-ours-resave-logic"))
        self.assertEqual(_folder(ours, a1), _folder(logic, a1))
        self.assertEqual(len(_folder(ours, a1)), 6)

    def test_the_resave_reads_as_our_write(self):
        a1, ours = self._ours()
        logic = project_data(_goldens.path("automation-ours-resave-logic"))
        self.assertEqual(_lanes(logic, "Audio 1"), _lanes(ours, "Audio 1"))
        self.assertEqual(_lanes(logic, "Audio 1"), [(ln["parameter"], ln["region"], tuple(ln["ticks"]), tuple(ln["values"]))
                                                    for ln in sorted(_goldens.fact("automation-ours-resave-logic", "lanes"), key=lambda ln: (ln["parameter"], ln["region"]))])


if __name__ == "__main__":
    unittest.main()
