# resources/data — data the tools need but did not author

Everything here was written by Logic Pro or by a plugin vendor, so none of it is tracked. The
package carries its own copy of what Logic wrote on a blank project — `src/logicxkit/data`,
record templates and native donors regenerated from the public corpus by `bin/regen_data.py` —
so a fresh clone needs this root only for third-party donors and AU tables, each generated on
your own machine from your own plugins. `resources/data` is the default root; point
`LOGICXKIT_DATA` at a directory of the same shape to use another copy. The packaged file wins
over one here of the same name, and `logic donors` leaves the plug-ins the package ships to it.

    donors/     plugin-slot donor records (`*.slot`) and `manifest.json`. Made by
                `bin/run logic donors PROJECT_OR_STRIP` from any project or channel strip that
                carries the plugin; `logic chains` reads them.
    logic/      record templates Logic saved, one JSON each: an aux channel, an instrument
                channel with its default slots, a fresh audio channel, a group triple and a
                section name record. Each JSON says which Logic build wrote it. To remake one,
                add the object in Logic, save, and copy the record's header and payload out
                (`bin/run logic recdiff` finds it).
    au/         AU parameter tables, `<manufacturer>_<subtype>.json`, from
                `swift src/logicxkit/native/auprobe.swift list` against the installed plugins.

A missing file raises `MissingData` naming both the path it looked for and this README, so the
error tells you which kind to generate; the tests that need one skip and say so.
