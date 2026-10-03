"""What a plug-in is called: the display name in a slot's name string, and Logic's own names
for native block types and their variants."""

from __future__ import annotations

import re

# Canonical plugin display names, most-specific needle first.
_PLUGINS = [
    ("Neutron 5 Transient Shaper", "Neutron"), ("Neutron 5", "Neutron 5"),
    ("Pro-Q 4", "Pro-Q 4"), ("Pro-C 2", "Pro-C 2"), ("Pro-MB", "Pro-MB"), ("Pro-L", "Pro-L"),
    ("smartGate", "smart:gate"), ("smartComp", "smart:comp"), ("InPhase", "InPhase"),
    ("Channel EQ", "Channel EQ"), ("ChanEQ", "Channel EQ"), ("Compressor", "Compressor"),
    ("Enveloper", "Enveloper"), ("Noise Gate", "Noise Gate"), ("Gain", "Gain"),
    ("SVT", "SVT"), ("Nectar", "Nectar 4"), ("Ozone", "Ozone 11"), ("Soldano", "Soldano"),
    ("Archetype", "Archetype"), ("Melodyne", "Melodyne"), ("EZbass", "EZbass"),
    ("Addictive", "Addictive Trigger"), ("Stealth", "Stealth"),
]

_PLUGIN_TOKEN = re.compile(rb"[A-Za-z][ -~]{2,42}")


def plugin_name(window: bytes) -> str | None:
    for m in _PLUGIN_TOKEN.finditer(window):
        s = m.group().decode("latin-1")
        for needle, disp in _PLUGINS:
            if needle in s:
                return disp
    return None


# Native plugin type ids, for naming a slot whose record carries no readable name string.
# The verbs are the config's own donor types (the spec's `donors` map).
PLUGIN_NAMES = {236: "Channel EQ", 154: "Compressor", 157: "Enveloper", 199: "Limiter",
                243: "Linear Phase EQ", 194: "Multipressor", 193: "Adaptive Limiter",
                183: "Gain", 147: "Echo", 287: "ChromaVerb", 150: "SilverVerb",
                166: "EnVerb", 231: "Space Designer", 158: "Klopfgeist",
                291: "DeEsser 2", 156: "Expander", 179: "Noise Gate", 311: "Single Band EQ",
                286: "Vintage Console EQ", 285: "Vintage Graphic EQ", 284: "Vintage Tube EQ",
                246: "Match EQ", 148: "Stereo Delay", 248: "Delay Designer",
                299: "Quantec Room Simulator", 273: "Pedalboard", 259: "Sample Delay",
                145: "Chorus", 161: "Ensemble", 146: "Flanger", 152: "Phaser", 181: "Modulation Delay",
                252: "Ringshifter", 229: "Scanner Vibrato", 258: "Spreader", 185: "Tremolo",
                163: "Bitcrusher", 191: "Clip Distortion", 164: "Distortion", 228: "Distortion II",
                165: "Overdrive", 196: "Phase Distortion", 162: "AutoFilter", 221: "EVOC 20 Filterbank",
                155: "Fuzz-Wah", 168: "Spectral Gate", 230: "Rotor Cabinet",
                274: "Amp Designer", 297: "Bass Amp Designer", 235: "Pitch Correction", 159: "Pitch Shifter",
                249: "Vocal Transformer", 197: "Exciter", 187: "SubBass",
                182: "Direction Mixer", 198: "Stereo Spread", 242: "BPM Counter", 241: "Correlation Meter",
                255: "Level Meter", 315: "Loudness Meter", 240: "MultiMeter", 239: "Tuner", 253: "Test Oscillator",
                301: "Beat Breaker", 289: "Step FX", 314: "Remix FX", 288: "Phat FX", 269: "Binaural Post-Processing"}

# One block type, several plug-ins: told apart by the variant base (`slot_width.plugin_variant`).
# The type's entry above names the member that keeps the plain table and donor keys.
PLUGIN_VARIANTS = {147: {200: "Tape Delay", 216: "Echo"},
                   273: {1623: "Pedalboard", 2050: "Tru-Tape Delay"},
                   152: {283: "Phaser", 336: "Microphaser"}}

NATIVE_INSTRUMENTS = {158}          # type ids that sit in the instrument slot, not an insert


def native_name(type_id: int | None, variant: int | None = None) -> str | None:
    """Logic's name for a native block: the variant's where the type is shared, else the type's."""
    return PLUGIN_VARIANTS.get(type_id, {}).get(variant) or PLUGIN_NAMES.get(type_id)


def native_names() -> dict:
    """Every known name, by type id and by ``(type id, variant base)``, for a harvest."""
    return {**PLUGIN_NAMES, **{(t, v): n for t, vs in PLUGIN_VARIANTS.items() for v, n in vs.items()}}
