"""Describe what a chain plan does to a project, before it does it.

`insert_slots` replaces any existing slot at a key it writes, so on an already-dialled song a
run discards that work. Naming it is a separate concern from building the plan, and lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chains import channel_references
from .chains_channels import channel_name
from .insert import HEADER, plugin_variant

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


def _slot_name(payload: bytes, type_id: int | None = None) -> str:
    """What to call a plugin slot when reporting what a chain replaces.

    The name string first — it is the only thing a third-party slot carries — then the native
    type id, then the bare id, so a report never says "?" about work someone is about to lose.
    """
    from .._binary import find_blocks
    from .project import _plugin_name

    name = _plugin_name(payload)
    if name:
        return name
    if type_id is None:
        blocks = find_blocks(payload)
        type_id = blocks[0][1] if blocks else None
    return native_name(type_id, plugin_variant(payload)) or (f"type {type_id}" if type_id else "unnamed plugin")


@dataclass(frozen=True)
class ChainChange:
    """What applying a chain plan does to one channel."""
    owner: int
    ref: str
    before: list[str]        # plugin names already on the channel, in slot-key order
    after: list[str]         # plugin names the plan places, in slot-key order
    replaced: list[str]      # names at keys the plan overwrites — this is the work being lost

    @property
    def reordered(self) -> bool:
        """The same plugins, in a different order — a silent rearrangement of a dialled chain."""
        return bool(self.before) and sorted(self.before) == sorted(self.after) \
            and self.before != self.after

    def line(self) -> str:
        if not self.before:
            return f"{self.ref:26s} + {' -> '.join(self.after)}"
        verb = "REORDER" if self.reordered else "REPLACE"
        return (f"{self.ref:26s} {verb}  {' -> '.join(self.before)}"
                f"  ==>  {' -> '.join(self.after)}")


def chain_changes(data: bytes, plan: dict) -> list[ChainChange]:
    """Per channel, the chain that is there and the chain the plan would leave.

    `insert_slots` replaces any existing slot at a key it writes, so on an already-dialled song
    a run discards that work. Nothing said so before it happened.
    """
    from .transplant import channel_slots

    refs = channel_references(data)
    out = []
    for owner, slots in sorted(plan.items()):
        existing = {r.key: _slot_name(r.raw[HEADER:]) for r in channel_slots(data, owner)}
        placed = {e[1]: _slot_name(e[0][HEADER:], e[6]) for e in slots}
        survives = {k: v for k, v in existing.items() if k not in placed}
        out.append(ChainChange(
            owner=owner,
            ref=refs.get(owner) or channel_name(data, owner),
            before=[existing[k] for k in sorted(existing)],
            after=[v for _k, v in sorted({**survives, **placed}.items())],
            replaced=[existing[k] for k in sorted(existing) if k in placed],
        ))
    return out
