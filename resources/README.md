# resources/ — reference material, read-only

Where the Logic-authored files the tools and tests read for reference are staged: templates,
controlled saves, finished mixes, a channel-strip library snapshot, older projects. Everything
here is a copy — the originals stay in Logic's own library under `~/Music`.

**Nothing in this directory is ever modified, renamed, moved or deleted by the tools.**
Generated output goes to `out/`, and an experiment starts from a copy made into `out/`.

Gitignored except this file and `data/README.md`. The material itself is Logic- and
vendor-authored project data and is not redistributable, so a fresh clone gets an empty
directory — stage your own using the layout below. Producing any of it needs Logic Pro on
macOS.

## Layout

    templates/    .logicx templates re-saved from the current Logic (File > Save As… here).
    experiments/  Controlled saves made by Logic itself: one deliberate change per save, named
                  `NN-what-changed`, so a diff against the previous one isolates the bytes.
                  These are the ground truth the decoders and goldens measure against.
    mixes/        A finished song: the mixed-down .logicx project (with its Audio Files
                  folder) and the bounced master.
    strips/       A snapshot of a channel-strip library (`~/Music/Audio Music Apps/Channel
                  Strip Settings/Track/<library>/`), copied as folders, dated in a note.
    legacy/       Projects cut from an older template — different track layout, older
                  plugins — for the migration path. Audio optional; the layout is the point.
    data/         Record templates, plugin-slot donors and AU parameter tables the tools load
                  rather than merely read. `data/README.md` says how each kind is made.

## Naming

- Keep Logic's own names for templates and mixes; the folder says what they are.
- Controlled saves: a running number, then the one thing that changed —
  `13-header-baseline`, `14-header-no-track-numbers`, … Never Cmd-S the file you started
  from; Save As.
- A `NOTES.md` beside a group of files may record the date, Logic version and what was done.

## How the tools reach it

`tests/_paths.py` reads only what is staged here — never Logic's live library, which
`tests/_liveguard.py` refuses outright. Goldens skip when a file is absent, so a machine
without this directory runs green but proves less. `LOGICXKIT_RESOURCES` overrides the root,
and `experiments/manifest.json` maps each golden's key to its file and facts.
