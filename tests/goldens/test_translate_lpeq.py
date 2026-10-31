"""Linear Phase EQ as an eq-family target: a Channel EQ's bands carried into it by `swap-plugin`,
today's swap writing the copy Logic re-saved, and that re-save keeping every row. Skips without the
public corpus."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run

from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.plugin_params import load_tables
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.translate.translate import load_maps, map_for, read_settings
from logicxkit.logicx import project_data

SOURCE, OURS, RESAVE = "translate-proq-ours-resave-logic", "translate-lpeq-ours", "translate-lpeq-ours-resave-logic"
MAPS, TABLES = load_maps(), load_tables()


def _settings(key: str):
    data = project_data(_goldens.path(key))
    facts = _goldens.entry(key)["facts"]
    payload = channel_slots(data, owner_by_label(data, facts["channel"]))[facts["slot"] - 1].raw[HEADER:]
    m = map_for(payload, MAPS)
    return m, read_settings(payload, m, TABLES)


def _floats(bundle: Path) -> list[float]:
    data = project_data(bundle)
    payload = channel_slots(data, owner_by_label(data, "Audio 2"))[0].raw[HEADER:]
    return read_block_floats(payload, *find_blocks(payload)[0][::2])


@_goldens.needs(SOURCE, OURS, RESAVE)
class LinearPhaseEqTargetTest(unittest.TestCase):
    def test_the_bands_cross_slot_for_slot_and_logic_keeps_them(self):
        (cheq, src), (lpeq, ours), (_m, kept) = _settings(SOURCE), _settings(OURS), _settings(RESAVE)
        self.assertEqual((cheq.plugin, lpeq.plugin, lpeq.family), ("Channel EQ", "Linear Phase EQ", "eq"))
        self.assertEqual(len(src.bands), len(ours.bands))
        for a, b, c in zip(src.bands, ours.bands, kept.bands, strict=True):
            with self.subTest(band=a.number, shape=a.shape):
                self.assertEqual((a.shape, a.on), (b.shape, b.on))
                self.assertEqual((b.shape, b.on), (c.shape, c.on))
                for name in ("frequency", "gain", "q"):
                    self.assertAlmostEqual(getattr(a, name), getattr(b, name), places=2)   # Logic holds 15999.999 where the grid reads 16000
                    self.assertAlmostEqual(getattr(b, name), getattr(c, name), places=2)   # 16000 kept as 15999.999
        self.assertEqual(src.master, ours.master)
        self.assertAlmostEqual(ours.master, kept.master, places=3)

    def test_todays_swap_writes_the_copy_logic_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run("swap-plugin", _goldens.path(SOURCE), "--from", "Channel EQ", "--to", "Linear Phase EQ",
                             "--channel", "Audio 2", "--out", tmp)
            self.assertEqual(code, 0, text)
            rebuilt = _floats(Path(tmp) / _goldens.path(SOURCE).name)
        self.assertEqual(rebuilt, _floats(_goldens.path(OURS)))


if __name__ == "__main__":
    unittest.main()
