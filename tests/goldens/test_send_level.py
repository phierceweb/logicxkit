"""Send level, mode and bypass, and the fader, against Logic 12.4's own saves: one change per
save on one send, three fader steps, and Logic's save of a copy the commands wrote. Skips
without the public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.mixer.levels import fader_word, read_levels, shown_db
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logicx import project_data

MODES = ("send-mode-pre-fader-logic", "send-mode-post-fader-logic", "send-independent-pan-logic",
         "send-bypass-logic", "send-level-0db-logic")
STEPS = ("fader-step-120-logic", "fader-step-200-logic", "fader-step-113-logic")
OURS, LOGICS = "send-set-ours", "send-set-resave-logic"


def sends(key: str) -> list:
    return read_sends(project_data(_goldens.path(key)))[0]


@_goldens.needs(*MODES)
class LogicsSendSettingsTest(unittest.TestCase):
    def test_each_save_reads_as_the_one_change_it_made(self):
        for key in MODES:
            with self.subTest(key):
                (s,) = sends(key)
                found = {"mode": s.mode, "bypassed": s.bypassed,
                         "independent_pan": s.independent_pan, "shown": shown_db(s.level_exact)}
                self.assertEqual(found, {k: _goldens.fact(key, k) for k in found})

    def test_logics_0_db_stop_sits_above_the_mark(self):
        (s,) = sends("send-level-0db-logic")
        self.assertEqual(round(s.level_exact * (1 << 24)),
                         _goldens.fact("send-level-0db-logic", "word"))


@_goldens.needs(*STEPS)
class LogicsFaderStepsTest(unittest.TestCase):
    def test_a_step_reads_as_logic_shows_it(self):
        for key in STEPS:
            with self.subTest(key):
                lv = read_levels(project_data(_goldens.path(key)))[0]
                self.assertEqual((lv["fader_fixed"], shown_db(lv["fader_exact"])),
                                 (_goldens.fact(key, "word"), _goldens.fact(key, "shown")))

    def test_a_step_on_a_mark_stores_the_laws_own_word(self):
        self.assertEqual((fader_word(-5.3), fader_word(2.7)),
                         (_goldens.fact("fader-step-120-logic", "word"),
                          _goldens.fact("fader-step-200-logic", "word")))


@_goldens.needs(OURS, LOGICS)
class LogicKeptWrittenSettingsTest(unittest.TestCase):
    def test_both_read_as_the_commands_wrote_them(self):
        for key in (OURS, LOGICS):
            with self.subTest(key):
                found = [[s.bus, shown_db(s.level_exact), s.mode, s.bypassed] for s in sends(key)]
                self.assertEqual(found, _goldens.fact(key, "sends"))
                lv = read_levels(project_data(_goldens.path(key)))[0]
                self.assertEqual((shown_db(lv["fader_exact"]), lv["pan_display"]),
                                 (_goldens.fact(key, "fader"), _goldens.fact(key, "pan")))

    def test_logic_kept_each_send_record_and_the_fader_word(self):
        self.assertEqual([s.raw for s in sends(LOGICS)], [s.raw for s in sends(OURS)])
        ours, logics = (read_levels(project_data(_goldens.path(k)))[0] for k in (OURS, LOGICS))
        self.assertEqual((logics["fader_fixed"], logics["pan"]), (ours["fader_fixed"], ours["pan"]))


if __name__ == "__main__":
    unittest.main()
