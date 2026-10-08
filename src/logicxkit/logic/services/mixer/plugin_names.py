"""What a plug-in is called: the display name in a slot's name string, and Logic's own names
for native block types and their variants."""

from __future__ import annotations

import re

from .slot_identity import NATIVE, CODED, slot_header
from .slot_width import plugin_variant

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
                301: "Beat Breaker", 289: "Step FX", 314: "Remix FX", 288: "Phat FX", 269: "Binaural Post-Processing",
                # the instruments, by Logic's saves of each one (`instrument-*-logic`)
                189: "ES1", 201: "ES M", 202: "ES P", 203: "ES E", 213: "Vintage Electric Piano", 214: "ES2",
                216: "Vintage B3", 219: "EFM1", 220: "EVOC 20 PolySynth", 222: "Sculpture", 223: "Vintage Clav",
                238: "Ultrabeat", 279: "Retro Synth", 281: "Drum Synth", 313: "Alchemy",
                # MIDI effects and three effects (`instrument-fx-*-logic`); 320 by
                # Logic's own settings file, its slot's short name "Mastering"
                290: "Transposer", 300: "Arpeggiator", 302: "Scripter", 303: "Note Repeater", 304: "Randomizer",
                305: "Modifier", 307: "Velocity Processor", 308: "Chord Trigger", 309: "Modulator",
                188: "EVOC 20 TrackOscillator", 320: "Mastering Assistant", 321: "ChromaGlow"}

# One block type, several plug-ins: told apart by the variant base (`slot_width.plugin_variant`).
# The type's entry above names the member that keeps the plain table and donor keys.
# 273 is Pedalboard and its 35 stompboxes, each a pedal alone in an Audio FX slot (`instrument-fx-stomp-*-logic`).
PLUGIN_VARIANTS = {147: {200: "Tape Delay", 216: "Echo"},
                   273: {1623: "Pedalboard", 1640: "Vintage Drive", 1656: "Grinder", 1672: "Fuzz Machine",
                         1688: "Retro Chorus", 1705: "Robo Flanger", 1722: "The Vibe", 1739: "Auto-Funk",
                         1755: "Blue Echo", 1771: "Squash Compressor", 1787: "OctaFuzz",
                         1803: "Happy Face Fuzz", 1819: "Monster Fuzz", 1835: "Candy Fuzz",
                         1851: "Double Dragon", 1867: "Rawk! Distortion", 1883: "Hi-Drive",
                         1899: "Spin Box", 1916: "Roto Phase", 1933: "Heavenly Chorus",
                         1950: "Trem-O-Tone", 1967: "Phaze 2", 1984: "Roswell Ringer",
                         2001: "Total Tremolo", 2018: "Classic Wah", 2034: "Modern Wah",
                         2050: "Tru-Tape Delay", 2066: "Spring Box", 2082: "Phase Tripper",
                         2099: "Flange Factory", 2116: "Tube Burner", 2132: "Tie Dye Delay",
                         2148: "Dr. Octave", 2164: "Graphic EQ", 2180: "Wham", 2196: "Grit"},
                   152: {283: "Phaser", 336: "Microphaser"},
                   313: {2464: "Alchemy", 2465: "Sample Alchemy"}}

NATIVE_INSTRUMENTS = {158}          # type ids that sit in the instrument slot, not an insert

# Logic's own plug-ins that carry no type id: a four-letter code and a variant word
# (`slot_identity`), by (code, word) — `instrument-*-logic`, `instrument-fx-*-logic`.
CODED_NAMES = {("ANML", 0): "Drum Kit Designer", ("SAM1", 0): "Sampler", ("PRRT", 0): "Quick Sampler",
               ("ExI2", 0): "External Instrument", ("InWr", 1): "Vintage Mellotron",
               ("InWr", 2): "Studio Horns", ("InWr", 3): "Studio Strings", ("InWr", 4): "Studio Piano",
               ("InWr", 5): "Studio Bass", ("_AS_", 0): "Auto Sampler", ("_IO_", 0): "I/O"}


def native_name(type_id: int | None, variant: int | None = None) -> str | None:
    """Logic's name for a native block: the variant's where the type is shared, else the type's."""
    return PLUGIN_VARIANTS.get(type_id, {}).get(variant) or PLUGIN_NAMES.get(type_id)


def coded_name(code: str, word: int) -> str | None:
    return CODED_NAMES.get((code, word))


def own_name(payload: bytes) -> str | None:
    """Logic's name for a slot holding one of its own plug-ins — the tables', else the header's
    short one — or None for an Audio Unit's slot and for a record with no slot header."""
    head = slot_header(payload)
    if head is None or head.maker not in (NATIVE, CODED):
        return None
    if head.maker == CODED:
        return coded_name(head.code, head.word) or head.name or str(head.code)
    return native_name(head.code, plugin_variant(payload)) or head.name or f"type {head.code}"


def native_names() -> dict:
    """Every known name, by type id and by ``(type id, variant base)``, for a harvest."""
    return {**PLUGIN_NAMES, **{(t, v): n for t, vs in PLUGIN_VARIANTS.items() for v, n in vs.items()}}
