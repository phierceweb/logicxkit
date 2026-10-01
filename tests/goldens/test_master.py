"""The output plug-ins on the Stereo Out and on a track, and one parameter per save, as Logic's
own saves wrote them (2026-09-16). Skips without the public corpus."""

import unittest
import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.binding import channels
from logicxkit.logic.services.chain_report import PLUGIN_NAMES
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.output_params import NAMES, PARAMS
from logicxkit.logicx import project_data

OUT_LABEL = "Output 1-2"
DONOR_KEYS = ("master-out-lpeq-logic", "master-out-multipressor-logic", "master-out-adaptive-limiter-logic",
              "master-out-limiter-logic", "master-track-lpeq-logic", "master-track-multipressor-logic",
              "master-track-adaptive-limiter-logic", "master-track-limiter-logic")
PARAM_KEYS = ("master-lpeq-peak3-gain-logic", "master-lpeq-peak3-freq-logic", "master-lpeq-peak3-q-logic",
              "master-lpeq-lowcut-on-logic", "master-mp-band1-threshold-logic", "master-mp-band1-ratio-logic",
              "master-mp-band1-makeup-logic", "master-mp-xover-1-2-logic", "master-adl-gain-logic",
              "master-adl-out-ceiling-logic", "master-adl-lookahead-logic", "master-adl-remove-dc-logic",
              "master-lim-gain-logic", "master-lim-output-level-logic", "master-lim-release-logic",
              "master-lim-lookahead-logic")
PARAM_NAMES = {"Peak 3 Gain": "peak3_gain", "Peak 3 Frequency": "peak3_freq", "Peak 3 Q": "peak3_q",
               "Low Cut": "low_cut_enable", "Band 1 Comp. Threshold": "band1_threshold",
               "Band 1 Comp. Ratio": "band1_ratio", "Band 1 Make Up": "band1_makeup",
               "Band 2 Xover Frequency 1/2": "xover_1_2", "Gain": "gain", "Out Ceiling": "out_ceiling",
               "Lookahead": "lookahead", "Remove DC": "remove_dc", "Output Level": "output_level",
               "Release": "release"}


def _inserts(data: bytes, label: str) -> list[tuple[int, list[float]]]:
    """(plug-in type id, floats) of the strip labelled ``label``, in slot order."""
    owner = next(o for o, c in channels(data).items() if c.label == label)
    out = []
    for r in sorted((r for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner), key=lambda r: r.key):
        blocks = find_blocks(r.raw[HEADER:])
        if blocks:
            idx, type_id, n = blocks[0]
            out.append((type_id, read_block_floats(r.raw[HEADER:], idx, n)))
    return out


@_goldens.needs(*DONOR_KEYS)
class DonorSavesTest(unittest.TestCase):
    def test_each_save_adds_the_next_plugin_on_its_channel(self):
        for key in DONOR_KEYS:
            with self.subTest(key):
                facts = _goldens.entry(key)["facts"]
                data = project_data(_goldens.path(key))
                label = OUT_LABEL if facts["channel"] == "Stereo Out" else facts["channel"]
                self.assertEqual([PLUGIN_NAMES[t] for t, _f in _inserts(data, label)], facts["inserts"])

    def test_the_slot_config_byte_is_the_tables_mono_and_stereo_value(self):
        """Audio 1 is mono and the Stereo Out stereo: each plug-in's config byte reads as PLUGIN_CFG says."""
        from logicxkit.logic.services.insert import MONO, PLUGIN_CFG, SLOT_CFG_AT, STEREO
        data = project_data(_goldens.path("master-track-limiter-logic"))
        owners = {c.label: o for o, c in channels(data).items()}
        for label, width in ((OUT_LABEL, STEREO), ("Audio 1", MONO)):
            for r in project_records(data):
                if r.tag == b"UCuA" and r.owner == owners[label] and (blocks := find_blocks(r.raw[HEADER:])):
                    with self.subTest(label=label, type_id=blocks[0][1]):
                        self.assertEqual(r.raw[HEADER + SLOT_CFG_AT], PLUGIN_CFG[blocks[0][1]][width])

    def test_the_output_channels_records_have_the_tracks_shape(self):
        """Same type ids, float counts and block offset on the Stereo Out as on Audio 1."""
        data = project_data(_goldens.path("master-track-limiter-logic"))
        out, trk = _inserts(data, OUT_LABEL), _inserts(data, "Audio 1")
        self.assertEqual([(t, len(f)) for t, f in out], [(t, len(f)) for t, f in trk])
        self.assertEqual({t for t, _f in out}, set(NAMES))


@_goldens.needs("master-out-lpeq-logic")
class LinearPhaseEqLayoutTest(unittest.TestCase):
    """The band stride, pinned by the default frequency ladder Logic wrote at every fourth index,
    and the cut bands' slope orders where a peak band keeps its gain."""

    def test_the_default_frequency_ladder_sits_at_every_fourth_index(self):
        from logicxkit.logic.services.output_params import BAND_ORDER, lpeq_index
        floats = dict(_inserts(project_data(_goldens.path("master-out-lpeq-logic")), OUT_LABEL))[243]
        ladder = [floats[lpeq_index(band, "freq")] for band in BAND_ORDER]
        self.assertEqual([round(f) for f in ladder], [20, 75, 100, 250, 750, 2500, 7500, 20000])

    def test_the_cut_bands_third_float_is_a_slope_order(self):
        from logicxkit.logic.services.output_params import lpeq_index
        floats = dict(_inserts(project_data(_goldens.path("master-out-lpeq-logic")), OUT_LABEL))[243]
        self.assertEqual((floats[lpeq_index("low_cut", "slope")], floats[lpeq_index("high_cut", "slope")]), (2.0, 4.0))
        self.assertAlmostEqual(floats[lpeq_index("low_cut", "q")], 0.71, places=2)


@_goldens.needs(*PARAM_KEYS)
class ParameterSavesTest(unittest.TestCase):
    def test_each_save_moved_the_measured_float(self):
        for key in PARAM_KEYS:
            with self.subTest(key):
                facts = _goldens.entry(key)["facts"]
                type_id = next(t for t, n in NAMES.items() if n == facts["plugin"])
                floats = dict(_inserts(project_data(_goldens.path(key)), OUT_LABEL))[type_id]
                index = PARAMS[type_id][PARAM_NAMES[facts["parameter"]]]
                self.assertAlmostEqual(floats[index], facts["value"], places=3)


@_goldens.needs("blank-base")
class WriteOnTheBlankTest(unittest.TestCase):
    """The example mastering config applied to the blank project puts the four plug-ins on the
    Stereo Out at the keys Logic's own inserts took, with the named parameters written."""

    def test_the_example_config_places_the_chain(self):
        from pathlib import Path
        from logicxkit.logic import chain_plan
        from logicxkit.logic.services.chains import load_chain_config, load_extra_donors
        from logicxkit.logic.services.insert import insert_slots
        from logicxkit.utils.data import data_dirs
        data = project_data(_goldens.path("blank-base"))
        cfg = load_chain_config(Path(__file__).resolve().parents[2] / "config" / "example-mastering.json")
        extra, _derived = load_extra_donors(cfg, 5, data_dirs("donors"))
        plan, report = chain_plan(data, cfg, None, None, extra=extra)
        self.assertEqual(report["matched"], ["Stereo Out"])
        written = insert_slots(data, plan)
        inserts = _inserts(written, OUT_LABEL)
        self.assertEqual([t for t, _f in inserts], [243, 194, 193, 199])
        floats = dict(inserts)
        self.assertAlmostEqual(floats[243][PARAMS[243]["peak3_gain"]], 1.5, places=4)
        self.assertAlmostEqual(floats[193][PARAMS[193]["out_ceiling"]], -0.3, places=4)
        self.assertAlmostEqual(floats[199][PARAMS[199]["output_level"]], -0.1, places=4)
        logic = _inserts(project_data(_goldens.path("master-out-limiter-logic")), OUT_LABEL) if _goldens.path("master-out-limiter-logic") else None
        if logic:
            self.assertEqual([t for t, _f in logic], [t for t, _f in inserts])

    def test_the_written_chain_reads_back_and_a_lost_value_is_reported(self):
        import struct
        from pathlib import Path
        from logicxkit.logic import chain_plan
        from logicxkit.logic.services.chains import load_chain_config, load_extra_donors, verify_channel_values
        from logicxkit.logic.services.insert import insert_slots
        from logicxkit.utils.data import data_dirs
        data = project_data(_goldens.path("blank-base"))
        cfg = load_chain_config(Path(__file__).resolve().parents[2] / "config" / "example-mastering.json")
        extra, _derived = load_extra_donors(cfg, 5, data_dirs("donors"))
        plan, _report = chain_plan(data, cfg, None, None, extra=extra)
        written = insert_slots(data, plan)
        self.assertEqual(verify_channel_values(written, cfg, extra), [])
        self.assertTrue(verify_channel_values(data, cfg, extra))          # nothing written yet
        marker = struct.pack("<f", -0.3)                                    # the Adaptive Limiter's out ceiling
        at = written.index(marker)
        broken = written[:at] + struct.pack("<f", 0.0) + written[at + 4:]
        self.assertTrue(any("did not take" in line for line in verify_channel_values(broken, cfg, extra)))


@_goldens.needs("master-ours-resave-logic", "blank-base")
class ResaveTest(unittest.TestCase):
    """Logic opened the chain the example config wrote onto the blank, showed every configured
    value in the plug-in windows and re-saved it; the re-save keeps the chain and the floats,
    the Multipressor ratio snapped to Logic's own step."""

    def test_the_resave_keeps_the_chain_and_its_parameters(self):
        from pathlib import Path
        cfg = __import__("json").loads((Path(__file__).resolve().parents[2] / "config" / "example-mastering.json").read_text())
        wanted = {e["donor"]: e.get("params", {}) for e in cfg["chains"]["Stereo Out"]["plugins"]}
        by_type = {243: "linear_phase_eq", 194: "multipressor", 193: "adaptive_limiter", 199: "limiter"}
        inserts = _inserts(project_data(_goldens.path("master-ours-resave-logic")), OUT_LABEL)
        self.assertEqual([PLUGIN_NAMES[t] for t, _f in inserts], _goldens.fact("master-ours-resave-logic", "inserts"))
        for type_id, floats in inserts:
            for name, value in wanted[by_type[type_id]].items():
                with self.subTest(NAMES[type_id], parameter=name):
                    places = 1 if name in ("band1_ratio", "peak3_q") else 3   # Logic snaps both to its steps
                    self.assertAlmostEqual(floats[PARAMS[type_id][name]], float(value), places=places)


if __name__ == "__main__":
    unittest.main()
