"""Shared helpers across logicxkit subpackages.

Intentionally empty. The x32 (OSC text) and logic (binary) formats share concepts
(EQ, compressor, round-trip, decode->edit->rebuild) but NO encoding code. Promote a
helper here only when there are >=2 identical call sites — not merely analogous ones.
"""
