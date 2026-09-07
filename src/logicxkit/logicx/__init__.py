"""logicxkit.logicx — the Logic project *container* format.

Bundle layout and OCuA channel blocks, with no opinion on what the bytes inside a channel
mean. Both ``logicxkit.logic`` (strip semantics) and ``logicxkit.au`` (plugin state) read
projects through here, so it imports no sibling package.
"""

from logicxkit.logicx.container import (  # noqa: F401
    channel_blocks,
    channel_label,
    first_alternative,
    is_bundle,
    project_data,
    read_states,
)
