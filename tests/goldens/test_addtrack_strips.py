"""Which `Audio` strip a new audio track takes, against Logic's own adds: Logic never binds a bare
stub that keeps its own UUID, one no track has used; it inserts a fresh strip there, mono or
stereo, and the Preview strip stays last. A deleted track's strip, its UUID zeroed, it binds
whatever its width (`gone-d3-logic`, in `test_gone_ids.py`; a mono one made stereo, `gone-m2-logic`)."""

import unittest

import _goldens
from _stackview import load, obj
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.mixer.binding import bound_channels, channels, input_labels, output_labels

# (before, after, the track each add follows, stereo, adds); `tracks-*` and `stackid-*` are Logic
# 12.3.1's and 12.4's New Audio Track and New Tracks…, `upgraded-*` three adds to one song
PAIRS = (("blank-base", "tracks-two-audio-logic", "Audio 1", False, 1),
         ("tracks-two-audio-logic", "tracks-three-audio-logic", "Audio 2", False, 1),
         ("tracks-three-audio-logic", "tracks-stereo-pair-logic", "Audio 3", True, 1),
         ("stackid-base0-logic", "stackid-s1-logic", "Audio 3", True, 2),
         ("gone-m1-logic", "gone-m2-logic", "Audio 2", True, 1))      # a deleted mono track's strip, bound and made stereo
OWNER_PAIRS = (("upgraded-baseline-logic", "upgraded-three-audio-logic", None, False, 3),
               ("mix-04-12-4", "mix-04-12-4-newtrack-logic", "Drums", True, 1))   # a shaped mono strip left free, bound and made stereo
TEN = "master-track-limiter-logic"


def audio_strips(data: bytes) -> list[tuple]:
    """Each `Audio` strip in owner order: label, in use, input, output."""
    ins, outs = input_labels(data), output_labels(data)
    return [(c.label, c.in_use, ins.get(o), outs.get(o)) for o, c in sorted(channels(data).items())
            if c.label.startswith("Audio ")]


def replay(before: str, anchor: str | None, stereo: bool, adds: int) -> bytes:
    data, count = load(before)
    after = obj(data, anchor) if anchor else [r for r in read_tracks(data, count) if r["depth"] == 0][-1]["object_id"]
    for i in range(adds):
        data, report = add_track(data, name=f"Added {i + 1}", after=after, stereo=stereo, track_count=count + i)
        after = report["object_id"]
    return data


class _Replay(unittest.TestCase):
    pairs: tuple = ()

    def test_the_audio_strips_are_logics(self):
        for before, after, anchor, stereo, adds in self.pairs:
            with self.subTest(after):
                self.assertEqual(audio_strips(replay(before, anchor, stereo, adds)), audio_strips(load(after)[0]))


@_goldens.needs(*(k for p in PAIRS for k in p[:2]))
class LogicsAddsTest(_Replay):
    pairs = PAIRS


@_goldens.needs(*(k for p in OWNER_PAIRS for k in p[:2]))
class LogicsAddsOnASongTest(_Replay):
    pairs = OWNER_PAIRS


@_goldens.needs(TEN, "addtrack-fresh-logic", "midi-import-resave-logic")
class PreviewStaysLastTest(unittest.TestCase):
    def test_ten_adds_keep_the_unused_stubs_and_the_preview_strip_last(self):
        data, count = load(TEN)
        after = obj(data, "Audio 1")
        for i in range(10):
            data, report = add_track(data, name=f"FX {i + 1:02d}", after=after, track_count=count + i)
            self.assertEqual(report["label"], channels(data)[report["owner"]].label)
            after = report["object_id"]
        objects, bound = channel_objects(data), {own: o for o, own in bound_channels(data).items()}
        named = [(c.label, objects[bound[o]].name if o in bound else None)
                 for o, c in sorted(channels(data).items()) if c.label.startswith("Audio ")]
        self.assertEqual(named, [("Audio 1", "Audio 1")] + [(f"Audio {n + 2}", f"FX {n + 1:02d}") for n in range(10)]
                         + [("Audio 12", None), ("Audio 13", None), ("Audio 14", "Preview")])

    def test_a_fresh_strip_can_go_first(self):
        """`midi-import-resave-logic`: Audio 1 and 2 are unused stubs, so the strip takes Audio 1."""
        data, count = load("midi-import-resave-logic")
        out, report = add_track(data, name="New", after=obj(data, "Studio Grand"), track_count=count)
        self.assertEqual((report["label"], [s[:2] for s in audio_strips(out)]),
                         ("Audio 1", [("Audio 1", True), ("Audio 2", False), ("Audio 3", False), ("Audio 4", True)]))

    def test_with_no_unused_stub_the_fresh_strip_goes_before_the_preview_strip(self):
        data, count = load("addtrack-fresh-logic")
        out, report = add_track(data, name="New One", after=obj(data, "Audio 1"), track_count=count)
        labels = {o: c.label for o, c in channels(out).items()}
        self.assertEqual(report["label"], labels[report["owner"]])
        bound = {o: own for o, own in bound_channels(out).items()}
        preview = next(o for o, x in channel_objects(out).items() if x.name == "Preview")
        audio = sorted(o for o, label in labels.items() if label.startswith("Audio "))
        self.assertEqual((audio[-1], audio[-2]), (bound[preview], report["owner"]))


if __name__ == "__main__":
    unittest.main()
