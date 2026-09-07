# out/ — generated output

Everything the tools produce: patched project copies, built strips and `.pst` settings,
harvested donors, extracted window images, and run notes.

Regenerate rather than hand-editing, so the transform stays reproducible. Nothing here is
authoritative — `in/` plus the config is the source of truth — and no tracked file may point
at a path under `out/`.

Gitignored except this file: a fresh clone gets an empty directory.
