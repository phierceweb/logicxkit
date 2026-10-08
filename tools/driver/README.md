# tools/driver — recording a golden from Logic Pro

Every byte logicxkit decodes was pinned the same way: one deliberate change in Logic, one
Save As, one diff against the save before it. These scripts do the driving through macOS
accessibility (System Events) and real mouse events; nothing here talks to Logic's own
scripting, which hangs it.

    drive.py             one action, one Save As, per step; steps come from a JSON file
    saveas.applescript   the guarded Save As: waits for the Save window, types name and folder
    press.applescript    press a control bar button or Project Settings control by name
    diff.py              changed ProjectData records and DisplayState keys between two saves
    click.swift, dclick.swift, drag.swift, winids-all.swift
                         real mouse events and Logic's window list (ids, layers, frames)
    axdump.swift, axact.swift
                         the accessibility tree of a Logic window as one line per element, and
                         press/pick/set on an element by that line's path
    controls.py          `chains --verify`'s reader: opens a bundle, reads every plug-in's
                         Controls view on the named tracks, closes without saving, prints JSON
    example-steps.json   the step shapes: `bar`, `menu`, `press`/`increment`/`choose`,
                         `popover`, `clickpop`, `sheet`, `dragslider`

Compile the Swift helpers once (`swiftc -O click.swift -o bin/click`, likewise the others);
`drive.py` falls back to `swift <file>` when `bin/` is empty. Give the terminal Accessibility
and Screen Recording permission; the first run asks.

## The loop

1. Start from a project Logic made on this machine — `File > New > Empty Project`, one
   audio track — or a public corpus save (`tests/corpus/`). Copy it under `out/scratch`;
   never Save (Cmd-S) the original, only Save As.
2. `open -a "Logic Pro" <copy>`; wait ~25 s; press **Skip All** or **Continue** on any dialog.
3. `LOGIC_SAVE_PREFIX=<family> python3 tools/driver/drive.py steps.json 1` — each step performs
   one action and saves `CLAUDE <family> <number> <label> (Logic save).logicx`.
4. `python3 tools/driver/diff.py <save A> <save B>` per consecutive pair. Record offsets 14,
   15, 173 and 258 and the `qeSM` carrying the project name churn on every save; ignore them.
5. Stage the saves with `python3 tools/stage_public.py spec.json` — a spec names each save,
   its public bundle name, a manifest key, a note and the facts a test may assert — and write
   the test under `tests/goldens/` reading them through `_goldens.path(key)` and
   `_goldens.fact(key, name)`.

Only saves of a project born in Logic on your machine are redistributable; a session with
anyone's music or third-party plug-in state stays out of the public corpus.

## Traps, each of which has already cost an hour

| Symptom | Cause | Do this |
|---|---|---|
| Typed file name became key commands, project closed | The Save As dialog did not open; keystrokes hit the main window | `saveas.applescript` waits for the window named **Save** and returns `NO SAVE DIALOG`; the driver stops |
| `entire contents` returns nothing for the rest of the session | The whole-tree walk dies after a window resize or zoom | Walk `UI elements` of the group whose description is "Control Bar"; Project Settings controls are direct children |
| Logic freezes, then every later step fails | `tell application "Logic Pro" …` hangs Logic | Only ever address System Events |
| AppleScript syntax errors with no obvious cause | `before`, `after`, `items`, `kind`, `folder`, `line` are reserved words | Rename the variable |
| Pane buttons or tabs ignore `click` | Toolbar and tab-group items need the action | `perform action "AXPress"` |
| A popover, plug-in menu or Sends menu is invisible to System Events | Logic's popovers and NSMenus are not in the accessibility tree | They are their own untitled window in `winids-all`; click by offset from that window's origin (`clickpop`), or type into a plug-in menu's search field and click the first row |
| A stepper ignores every action | Its row's checkbox is off | Tick the row first |
| Digits typed with no field focused switch screensets | Number keys are key commands | Double-click the value first and check the focused element is a text field before typing |
| A click lands on nothing | A plug-in window opened over the tracks area | Close plug-in windows by their `close` button before clicking the lane |
| A position guard on the LCD passes before the playhead moved | The LCD shows two positions: the playhead on top, the right locator below | Read the top `Playhead Position` group, or verify from what Logic then creates |
| A list editor's value slider jumps by 10, or a bar field by 4 | List sliders step on their own scale under `AXIncrement`/`AXDecrement`; an `AXValue` set moves one unit toward the target | Loop the set and read back; a list popup takes `click menu item` on its accessibility menu |
| The Sends slot menu closes on a click | Logic draws its rows itself; the search field has focus | Type the bus name into the search field, then Down and Return |
| Save As with a name that exists | The replace sheet blocks the driver | Never reuse a save name |
