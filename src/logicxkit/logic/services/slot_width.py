"""A slot record's width: the seven fields that say mono or stereo, the per-plug-in config
index each width takes (`PLUGIN_CFG`), and the variant base that identifies the plug-in
(`plugin_variant`). `insert` re-exports these for its callers.
"""

from __future__ import annotations

import struct

from .._binary import find_blocks
from .records import HEADER

# WIDTH. A plugin instance carries its own width and Logic does NOT derive it from the channel
# (its own files contain channel/slot disagreements), so a cloned mono donor stays mono on a
# stereo bus. The channel's width is at OCuA payload+123 (a literal channel count).
#
# A slot's width is SEVEN fields, not six:
#   +81            per-plugin config INDEX (not a channel count — Gain's stereo index is 3)
#   +84, +118/+119 channel counts
#   +116..117      plugin-VARIANT id, selecting the mono or stereo build of the plugin
#   +156 (+157)    one byte per input bus: main, then side chain
# Setting the counts without the variant id tells Logic "stereo" while still pointing it at the
# mono build. +82/+83 (bus counts) must be left alone.
SLOT_COUNT_AT = (84, 118, 119)
SLOT_CFG_AT = 81
SLOT_VARIANT_AT = 116
SLOT_BUS_AT = (156, 157)
MONO, STEREO = 1, 2

PLUGIN_CFG = {
    236: {MONO: 1, STEREO: 2},   # Channel EQ
    154: {MONO: 1, STEREO: 2},   # Compressor
    157: {MONO: 1, STEREO: 2},   # Enveloper
    199: {MONO: 1, STEREO: 2},   # Limiter
    183: {MONO: 1, STEREO: 3},   # Gain
    147: {MONO: 1, STEREO: 2},   # Echo
    243: {MONO: 1, STEREO: 2},   # Linear Phase EQ
    194: {MONO: 1, STEREO: 2},   # Multipressor
    193: {MONO: 1, STEREO: 2},   # Adaptive Limiter
    179: {MONO: 1, STEREO: 2},   # Noise Gate (stockfx-dynamics2-mono/-defaults)
    284: {MONO: 1, STEREO: 2},   # Vintage Tube EQ (stockfx-eq-mono/-defaults)
    286: {MONO: 1, STEREO: 2},   # Vintage Console EQ (same)
    311: {MONO: 1, STEREO: 2},   # Single Band EQ (same)
    150: {MONO: 1, STEREO: 3},   # SilverVerb (stockfx-dr-mono/-defaults)
    166: {MONO: 1, STEREO: 3},   # EnVerb (same)
    231: {MONO: 1, STEREO: 9},   # Space Designer (same)
    248: {MONO: 1, STEREO: 3},   # Delay Designer (same)
    287: {MONO: 1, STEREO: 3},   # ChromaVerb (same)
    246: {MONO: 1, STEREO: 2},   # Match EQ (stockfx-dr2-mono/-defaults); Tape Delay reads Echo's (147)
    148: {MONO: 1, STEREO: 3},   # Stereo Delay (stockfx-dr-mono, stockfx-dr2-defaults)
    259: {MONO: 1, STEREO: 3},   # Sample Delay (stockfx-dr3-mono/-defaults)
    299: {MONO: 1, STEREO: 10},  # Quantec Room Simulator (stockfx-dr-mono, stockfx-dr3-defaults)
    145: {MONO: 1, STEREO: 3},   # Chorus (stockfx-mod-mono/-defaults)
    146: {MONO: 1, STEREO: 3},   # Flanger (same)
    152: {MONO: 1, STEREO: 3},   # Phaser and Microphaser (same)
    161: {MONO: 1, STEREO: 3},   # Ensemble (same)
    181: {MONO: 1, STEREO: 3},   # Modulation Delay (same)
    185: {MONO: 1, STEREO: 3},   # Tremolo (same)
    229: {MONO: 1, STEREO: 3},   # Scanner Vibrato (same)
    252: {MONO: 1, STEREO: 3},   # Ringshifter (same)
    258: {MONO: 1, STEREO: 3},   # Spreader (same)
    162: {MONO: 1, STEREO: 3},   # AutoFilter (stockfx-dist-mono/-defaults)
    163: {MONO: 1, STEREO: 2},   # Bitcrusher (same)
    164: {MONO: 1, STEREO: 2},   # Distortion (same)
    165: {MONO: 1, STEREO: 2},   # Overdrive (same)
    191: {MONO: 1, STEREO: 2},   # Clip Distortion (same)
    196: {MONO: 1, STEREO: 2},   # Phase Distortion (same)
    221: {MONO: 1, STEREO: 2},   # EVOC 20 Filterbank (same; its mono counts read 2, 1, 2)
    228: {MONO: 1, STEREO: 2},   # Distortion II (same)
    159: {MONO: 1, STEREO: 2},   # Pitch Shifter (stockfx-amp-mono/-defaults)
    187: {MONO: 1, STEREO: 2},   # SubBass (same)
    197: {MONO: 1, STEREO: 2},   # Exciter (same)
    249: {MONO: 1, STEREO: 2},   # Vocal Transformer (same)
    274: {MONO: 1, STEREO: 2},   # Amp Designer (same)
    297: {MONO: 1, STEREO: 2},   # Bass Amp Designer (same)
    242: {MONO: 1, STEREO: 2},   # BPM Counter (stockfx-util-mono/-defaults; its mono record is the longer one)
    253: {MONO: 1, STEREO: 2},   # Test Oscillator (same)
    255: {MONO: 1, STEREO: 2},   # Level Meter (same)
    288: {MONO: 1, STEREO: 3},   # Phat FX (stockfx-mfx-mono/-defaults)
    289: {MONO: 1, STEREO: 3},   # Step FX (same)
    301: {MONO: 1, STEREO: 2},   # Beat Breaker (same)
    314: {MONO: 1, STEREO: 2},   # Remix FX (same)
    156: {MONO: 1, STEREO: 2},   # Expander (stockfx-dynamics2-mono/-defaults; the records are one length)
    291: {MONO: 1, STEREO: 2},   # DeEsser 2 (same)
    235: {MONO: 1, STEREO: 2},   # Pitch Correction (stockfx-amp-mono/-defaults)
    239: {MONO: 1, STEREO: 2},   # Tuner (stockfx-util-mono/-defaults)
    240: {MONO: 1, STEREO: 2},   # MultiMeter (same)
    315: {MONO: 1, STEREO: 2},   # Loudness Meter (same)
    285: {MONO: 1, STEREO: 2},   # Vintage Graphic EQ (stockfx-eq-mono/-defaults)
    (273, 1623): {MONO: 1, STEREO: 3},   # Pedalboard; its Tru-Tape Delay (variant 2050) is measured stereo only
    # One build: Logic puts these on a mono channel as Mono -> Stereo, the record as on a stereo
    # one (counts 2, index 2), so `set_slot_format` leaves them alone and `validate` lets them be.
    155: {MONO: 2, STEREO: 2},   # Fuzz-Wah (same)
    168: {MONO: 2, STEREO: 2},   # Spectral Gate (same)
    230: {MONO: 2, STEREO: 2},   # Rotor Cabinet (same)
    # Measured at one width only, so refused at the other: Direction Mixer (182), Stereo Spread
    # (198), Correlation Meter (241) and Binaural Post-Processing (269) stereo, Tru-Tape Delay stereo
}


def plugin_cfg(raw: bytes, type_id: int | None = None) -> dict | None:
    """The width configs of a slot's plug-in: by its type and variant base where they are
    measured apart (Pedalboard and its Tru-Tape Delay share a type), else by its type."""
    if type_id is None:
        blocks = find_blocks(raw[HEADER:])
        type_id = blocks[0][1] if blocks else None
    return PLUGIN_CFG.get((type_id, plugin_variant(raw[HEADER:]))) or PLUGIN_CFG.get(type_id)


def one_build(raw: bytes) -> bool:
    """A plug-in Logic writes as its stereo record on either channel."""
    cfg = plugin_cfg(raw)
    return cfg is not None and cfg[MONO] == cfg[STEREO]


def slot_format(raw: bytes) -> int | None:
    """The channel count a slot record declares, or None if it declares none."""
    payload = raw[HEADER:]
    seen = {payload[o] for o in SLOT_COUNT_AT if o < len(payload)} - {0}
    return seen.pop() if len(seen) == 1 else None


def plugin_variant(payload: bytes) -> int | None:
    """The plug-in's variant base — `+116` less the config index `+81` — the same for its mono
    and stereo builds and unique per plug-in where the block's type id is not (Tape Delay and
    Echo are both type 147). None when the record carries no variant (class v2/v3)."""
    if len(payload) <= SLOT_VARIANT_AT + 1:
        return None
    variant = struct.unpack_from("<H", payload, SLOT_VARIANT_AT)[0]
    return variant - payload[SLOT_CFG_AT] if variant else None


def set_slot_format(raw: bytes, fmt: int, type_id: int | None = None) -> bytes:
    """Rewrite a slot's width — channel counts, config index and plugin-variant id together.

    ``type_id`` is read from the record's own parameter chunk when not supplied.
    """
    if slot_format(raw) == fmt:
        return raw          # already the right width — no mapping needed to change nothing
    if type_id is None:
        blocks = find_blocks(raw[HEADER:])
        type_id = blocks[0][1] if blocks else None
    cfg_map = plugin_cfg(raw, type_id)
    if cfg_map is None:
        raise ValueError(f"plug-in type {type_id} has no measured width config for a {'stereo' if fmt == STEREO else 'mono'} "
                         "channel; it goes onto a channel of the width it was saved at (a guessed index is "
                         "wrong for e.g. Gain, whose stereo index is 3)")
    if cfg_map[MONO] == cfg_map[STEREO]:
        return raw          # one build for either channel: Logic writes the same record on both
    buf = bytearray(raw)
    old_cfg = buf[HEADER + SLOT_CFG_AT]
    new_cfg = cfg_map[fmt]

    for off in SLOT_COUNT_AT:
        at = HEADER + off
        if at < len(buf) and buf[at] in (MONO, STEREO):
            buf[at] = fmt
    buf[HEADER + SLOT_CFG_AT] = new_cfg

    at = HEADER + SLOT_VARIANT_AT
    if at + 1 < len(buf):
        variant = struct.unpack_from("<H", buf, at)[0]
        if variant:  # 0 in class versions that do not carry it
            struct.pack_into("<H", buf, at, variant - old_cfg + new_cfg)

    main, side = (HEADER + o for o in SLOT_BUS_AT)
    old_main = buf[main] if main < len(buf) else 0
    if main < len(buf) and buf[main] in (MONO, STEREO):
        buf[main] = fmt
    # a stereo instance may legitimately keep a mono side chain — only follow when they agreed
    if side < len(buf) and buf[side] in (MONO, STEREO) and buf[side] == old_main:
        buf[side] = fmt
    return bytes(buf)
