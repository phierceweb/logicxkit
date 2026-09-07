"""logicxkit — tools for Logic Pro projects, channel strips and Audio Unit state.

Subpackages:
- ``logicxkit.logic``  — Logic Pro channel-strip (.cst) build/decode, .logicx analysis.
- ``logicxkit.au``     — 3rd-party plugin presets/states via a headless AU host.
- ``logicxkit.logicx`` — the .logicx container format; a leaf both logic and au read through.

A pf-core consumer (foundation tier). Each gear domain owns a subpackage; ``logicxkit.utils``
and ``logicxkit.logicx`` are support leaves (only what ≥2 domains actually call). The
subpackage import graph is a DAG — enforced by tests/test_package_layering.py.
"""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("logicxkit")
except PackageNotFoundError:      # a source tree that was never installed
    __version__ = "0+unknown"
