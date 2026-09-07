"""logicxkit.au — Audio Unit preset/state intelligence (read-only).

Decodes plugin settings wherever Logic or the plugin stores them: standalone
.aupreset / .ffp preset files, and AU ClassInfo plists embedded in .cst strips
and .logicx ProjectData. Static parsers cover FabFilter/classic-AU parameter
tables and Waves XPst; the AU host (vendored Swift probe) instantiates the real
plugin headless for named, UI-formatted values of everything else.
"""

from logicxkit.au.services.aupreset import AuState, parse_au_state  # noqa: F401
from logicxkit.au.services.embed import find_au_plists, fourcc  # noqa: F401
from logicxkit.au.services.ffp import FfpError, FfpPreset, parse_ffp  # noqa: F401
from logicxkit.au.services.host import (  # noqa: F401
    AuDump, AuHost, AuHostError, AuParam, is_headless_safe,
)
from logicxkit.au.services.waves import extract_xpst  # noqa: F401
