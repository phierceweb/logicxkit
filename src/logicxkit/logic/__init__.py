"""Logic Pro channel-strip (.cst) build/decode — native Channel EQ + Compressor."""

from logicxkit.logic._binary import (  # noqa: F401
    find_blocks,
    identify_plugin,
    patch_block_floats,
    read_block_floats,
)
from logicxkit.logic.services.comp import build_comp, decode_comp  # noqa: F401
from logicxkit.logic.services.eq import build_eq, decode_eq  # noqa: F401
from logicxkit.logic.services.graft import (  # noqa: F401
    channel_info,
    graft,
    preset_labels,
    provenance,
    relabel_presets,
    set_provenance,
    seam,
)
from logicxkit.logic.services.limiter import build_limiter, decode_limiter  # noqa: F401
from logicxkit.logic.services.neural import (  # noqa: F401
    find_au_plists,
    neural_states,
    read_neural,
)
from logicxkit.logic.services.pst import PLUGINS, build_pst, factory_default  # noqa: F401
from logicxkit.logic.services.chains import (  # noqa: F401
    base_donors,
    chain_plan,
    channel_references,
    describe_duplicates,
    donor_from_cst,
    duplicate_chain_slots,
    find_donors,
    load_chain_config,
    load_extra_donors,
    strip_chain,
    strip_params,
    strip_path,
    verify_strip_values,
    width_plan,
)
from logicxkit.logic.services.donors import (  # noqa: F401
    donor_key,
    harvest_donors,
    load_donor_library,
)
from logicxkit.logic.services.insert import (  # noqa: F401
    ProjRecord,
    apply_float_overrides,
    channel_formats,
    insert_slots,
    instance_offsets,
    project_records,
    set_channel_format,
    set_slot_bypass,
    set_slot_format,
    slot_bypassed,
    slot_format,
    slot_index_base,
    widen_channels,
    relabel_slot,
)
from logicxkit.logic.services.validate import validate_project  # noqa: F401
from logicxkit.logic.services.retrack import (  # noqa: F401
    copy_project,
    cst_references,
    find_project,
    missing_strips,
    retrack,
    retrack_bundle,
)
from logicxkit.logic.services.records import (  # noqa: F401
    Record,
    plugin_slots,
    read_records,
    replace_slots,
    write_records,
)
from logicxkit.logic.services.project import analyze, read_project  # noqa: F401
from logicxkit.logic.services.spec import (  # noqa: F401
    assemble,
    build_strip,
    decode_strip,
    load_spec,
    resolve_base,
    template_path_for,
)
