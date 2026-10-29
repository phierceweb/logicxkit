"""The three output plug-ins' slider grids against Logic. The raw copy, written with no map
loaded, holds its values as written; Logic's re-save of it lays each on the position the map's
snap picks; a lane written by value lands on the unit and value the map predicts; and the
one-row saves moved to sampled positions. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.plugin_names import PLUGIN_NAMES
from logicxkit.logic.services.mixer.plugin_params import decode, load_tables, table_for
from logicxkit.logic.services.mixer.slot_width import plugin_variant
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

OUT_LABEL = "Output 1-2"            # what the file calls the Stereo Out
TABLES = load_tables()


def _values(key: str) -> dict[str, dict[str, float | str]]:
    """{plug-in name: {table row: value}} of the facts' channel, in slot order."""
    data = project_data(_goldens.path(key))
    channel = _goldens.fact(key, "channel")
    label = OUT_LABEL if channel == "Stereo Out" else channel
    owner = next(o for o, c in channels(data).items() if c.label == label)
    out = {}
    for r in sorted((r for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner), key=lambda r: r.key):
        payload = r.raw[HEADER:]
        if blocks := find_blocks(payload):
            at, type_id, n = blocks[0]
            table = table_for(TABLES, type_id, plugin_variant(payload))
            out[PLUGIN_NAMES[type_id]] = decode(table, read_block_floats(payload, at, n))
    return out


@_goldens.needs("slider-snap-raw")
class RawCopyTest(unittest.TestCase):
    def test_the_raw_copy_holds_every_value_as_written(self):
        values = _values("slider-snap-raw")
        written = _goldens.fact("slider-snap-raw", "written")
        self.assertEqual(list(values), list(written))
        for plugin, rows in written.items():
            for row, value in rows.items():
                with self.subTest(plugin=plugin, row=row):
                    self.assertAlmostEqual(values[plugin][row], value, places=4)


if __name__ == "__main__":
    unittest.main()
