# CLAUDE.md — CocoBackup

Extension-specific notes. Shared conventions (target versions, headless
verification, the Local Repository dev install, releases) live in the repo
root `CLAUDE.md`. The Blender behaviour this rests on (the keyconfig layers,
why an exported preset duplicates add-on shortcuts, the "user deleted this"
ghost) is in the vault note **Blender/Keymaps and keyconfigs**; read it before
changing `keymap_diff.py`.

## What it is

One JSON file (format 2) with four optional sections: `keymaps` (a diff),
`preferences`, `themes` and `addons`. Exported and imported from the coconut
button in the 3D Viewport header or File ▸ Export / Import. Also an optional
autosave that writes to a `Backup` folder next to the .blend.

## Layout

- `keymap_diff.py` — `export_keymaps()` / `import_keymaps()`.
- `prefs_io.py` — a generic RNA walker, `dump()` / `load()`, plus the section
  choices in `export_preferences()` / `export_addons()`.
- `themes_io.py` — theme presets and the active theme, as whole themes.
- `addons_resolve.py` — which missing add-ons can be enabled or installed.
- `autosave.py` — the autosave timer and its rotation.
- `ui.py` — the header button and its panel.
- `__init__.py` — preferences, the operators (export, import, the report
  popup and its buttons) and the File menu entries.

The operators are `cocobackup.export_backup` / `cocobackup.import_backup`:
`import` is a Python keyword, so `bpy.ops.cocobackup.import` cannot be called.

## Keymaps are a diff against stock + add-ons

Base = `keyconfigs.default` + `keyconfigs.addon`, compared with
`keyconfigs.user`. **Not** `keyconfigs.active` and not `is_user_modified`: with
a preset such as MyPreset loaded, both are relative to the preset, and the
preset's own changes would never reach the backup.

Items are paired by identity (operator + explicitly set properties, or
`propvalue` in a modal keymap), exact key first, then keymap order. A second
pass pairs what is left by operator + key, ignoring properties: the user copy
of an add-on item can carry different properties (Zen UV Sticky UV Editor on
Shift+T did), and "remove + add" would, on import, remove the add-on's merged
item, which is the permanent ghost. Added items that are switched off are
dropped: they do nothing, and in practice they are switched-off add-on copies a
preset baked in.

Import looks items up by identity + original key, then falls back to operator
+ key only when exactly one item matches. That fallback is what carries a
5.2 backup into 4.5: every paint mode's brush-size `wm.radial_control` on F
changed properties between them.

Enum-flag properties must be written as a `set`. A list is refused without an
error, the item then no longer matches its spec, and every re-import added it
again (it was `mesh.select_linked_pick`'s `delimit`).

## Preferences are walked, not listed

`dump()` reads every RNA property, so new Blender preferences are covered
without code changes. It is bounded by **depth**, not by a seen-set of
`as_pointer()`: a nested struct at offset 0 shares its parent's address, and a
seen-set silently dropped whole theme sections.

`_load_collection` leaves an unchanged add-on collection alone. Clearing and
re-adding fires every update callback: CocoPies re-registers all its pies.

Import order is preferences, add-on settings, keymaps. An add-on may rebuild its
shortcuts when its settings change (CocoPies does, and its X suppressions come
back on until its deferred pass runs), and the keymap diff has to land last.

## Headless tests do not see the default keymap

Under `--background` the default keyconfig holds 12 items instead of
thousands, so every keymap test has to run in a real window
(`--factory-startup --no-window-focus`, driven from a `bpy.app.timers`
callback that ends in `quit_blender()`). The checks that matter:

- export with no changes is empty;
- export → import in a second fresh session gives an identical keymap, and a
  re-export equals the original;
- a second import reports everything as "already";
- an add-on item moved to another key stays **one** item.

Verified 2026-09-26 on 4.5 and 5.2, cross-version both ways, and against the
user's real 5.2 setup (MyPreset, 35 add-ons): re-importing its own backup
changes nothing, and it restored a deleted and a renamed CocoPies pie.

## The header button

Appended to `VIEW3D_MT_editor_menus`, the row that draws View / Select / Add /
Object, so it lands after those menus and after what other add-ons append
there (Machin3, Hard Ops, PowerSave...), where the user asked for it. It is a
`layout.popover`, so the panel opens anchored under the button like View /
Select, with a dropdown arrow the user decided they want. It was a
`wm.call_panel` icon button first (no arrow), but that opens the panel wherever
the mouse is. For no arrow, a row with `emboss = 'PULLDOWN_MENU'` draws the
popover without it (exists on 4.5 too). The panel's buttons force
`INVOKE_DEFAULT`: under `wm.call_panel` they ran with EXEC, which skipped the
file browser and exported to an empty path.

1.0.0 put it in the tool header by wrapping `draw_tool_settings`;
`ui._unwrap_old_tool_header()` undoes that wrapper if a session still has it.

## Missing add-ons: switched on first, offered to switch off

`addons_resolve.classify()` sorts each add-on the backup names but this
machine is not running into disabled (installed, switched off), available
(listed by an online repository Blender has already synced) or unavailable.
The import operator enables or installs every disabled or available one
**before** anything else is applied. Done later, an add-on's tool shortcuts
(Bool Tool's Box Carve) had no operator yet, read as Blender's own, and the
reset pass removed them as "you had added it". As a second guard,
`keymap_diff._command_exists()` keeps the reset pass away from any shortcut
whose operator is not registered.

There is no separate dialog: the user wanted one window. The report lists
the add-ons it switched on as unticked CHOICE rows; `cocobackup.disable_addons`
("Disable Selected Add-ons") switches the ticked ones off with
`addons_resolve.disable()` and drops their settings and shortcut rows.
Differing themes are CHOICE rows too, with their own
`cocobackup.replace_themes` ("Replace Selected Themes"). The parsed backup and
every run's results live in `_state["job"]`; `_build_report()` rebuilds the
list from all runs, and a revert is recorded on the run's own entry
(`_mark_reverted`) so the rebuild keeps it.

The report's buttons do **not** reopen it: on 5.2 the popup stays open after a
click, and reopening it stacked a second copy on top. They only redraw. How
4.5 behaves on a click was not checked. The last row has a Save Preferences
button (`wm.save_userpref`).

`extensions.package_install` returns FINISHED even when the download failed.
Measured: an SSL "certificate has expired" error in Blender's own Python, sent
only to the Info editor. `install()` therefore checks that the add-on is
actually enabled afterwards. From a script-driven Blender here, downloads fail
that way and `repo_sync_all` never fetches a listing. An isolated install test
(`BLENDER_USER_RESOURCES` pointed at a scratch folder, with the user's
`blender_org/.blender_ext/index.json` copied in) reaches "available" but cannot
complete the download, so the online install path is **not verified
end-to-end**. Enabling an installed-but-disabled add-on is verified.

## The import report

After an import `cocobackup.show_report` opens a popup inside Blender: a
summary and a scrollable UIList (`WindowManager.cocobackup_report`, SKIP_SAVE)
in five groups: Add-ons / Extensions (set up, settings restored per add-on),
Shortcuts (Blender's own), Add-on shortcuts (one sub-group per add-on),
Preferences, Themes. Only real changes are listed; "ALREADY" lines never are,
and when nothing changes the popup says so in one line.

The user rejected, in order: a `.report.txt` opened in an external editor (it
has to stay inside Blender), every shortcut listed including unchanged ones,
and hundreds of theme colours counted as "preferences changed".

A shortcut's add-on is `keymap_diff.item_owner()`: the operator's Python class
module, or for `wm.call_menu*` / `wm.call_panel` the menu's. It is stored in
the backup as `owner` at export time, since on the target machine the add-on
may be missing. Blender's own (C operators, `bl_ui`, `bl_operators`) is "".

## Themes are whole things

`themes_io` exports the user's `presets/interface_theme/*.xml` and the active
theme's values. Import: a missing preset is installed, an identical one
skipped, a different one (or a different active theme) becomes an unticked
row in the report, so nothing is overwritten unless the user says so. The active theme's key in the overwrite set is
`themes_io.ACTIVE` = "<active theme>". It used to be "\0active", and a
StringProperty truncates at NUL, so a ticked "replace" arrived as "" and was
silently kept. Format-1 backups kept the theme inside `preferences`;
`_upgrade()` moves it.

## Autosave

`autosave.py`: a persistent `bpy.app.timers` tick every N minutes (addon
preferences, also in the coconut panel) writes
`<name>_autosave_<dd-mm-YYYY_HH.MM>.blend` in a `Backup` folder next to the file (created on the first autosave) with
`save_as_mainfile(copy=True)`, so the open file keeps its path and dirty state,
and deletes all but the newest M. It writes only if a `depsgraph_update_post`
since the last autosave or save flagged a change, and skips unsaved files and
renders. The name is day-first because the user asked for it (`/` is not
allowed in Windows names), so it does not sort by date: rotation sorts by
modification time. Two autosaves in the same minute overwrite each other.
Verified on 4.5 and 5.2: the folder is created, the oldest by time is the one
deleted, and `bpy.data.filepath` is unchanged.

## Import restores, it does not just add

A diff only touches what it names, so a shortcut changed after the export
(the user's test: Eyedropper Colorband E -> F, View2D Scroller Activate
switched off) survived the import and the report was silent about it.
`import_keymaps(reset_extra=True)` therefore re-diffs after applying and puts
back to stock every change the backup does not contain: a moved or
switched-off item back to its stock key, a user-added item removed, a removed
stock item re-created. Each one is a RESET line in the report. The import
dialog's "Undo shortcut changes not in the backup" (on by default) turns it
off, for merging a backup into a machine's own customisations instead.
Verified on 4.5 and 5.2 with all four kinds: the result equals the export
state, a second import reports nothing, and with the option off nothing moves.

## Shortcut rows, and reverting one

`import_keymaps()` returns `entries`, one dict per shortcut: word, owner,
keymap, what (`describe()`: the operator's or menu's title, or for a modal
keymap the action's own name from `km.modal_event_values`, so "Cancel" rather
than "modal CANCEL"), event (`change_event()`: "Key changed", "Switched off"...),
key before/after (`key_label()`: `any` reads "Esc (any modifier)" instead of
"Any+Ctrl+Shift+Alt+OS+Esc"), and an `undo` recipe. The report draws them as
columns, with a checkbox; `cocobackup.revert_selected` replays `apply_undo()`
for the ticked rows only ("Revert Selected Shortcuts"). Shortcuts put back by the reset pass sit under their own sub-heading.

`_set_key()` goes through `_set_type()`: an item's `type` only accepts events
of its current `map_type` (a mouse item refuses "F"), the keymap editor
switches map_type for you and RNA does not, and the refusal used to be
swallowed. Found testing Fill Tool Modal Map: moving its Middle Mouse item to F
and back silently did nothing.

## The coconut shows whether the file is saved

Three icons, all drawn by the user (`icons/`), chosen by `ui.file_state()`:

| State | Condition | Icon |
| --- | --- | --- |
| unsaved | `bpy.data.filepath` empty: the file is nowhere on disk | `coconut_unsaved.png`, red |
| saved | a path, `bpy.data.is_dirty` false | `coconut_saved.png`, green |
| modified | a path, `is_dirty` true | `coconut.png`, plain |

Red means only "never saved", not "has unsaved changes"; the user was explicit
about that. `is_dirty` flips
after an operator's undo push, which is after `depsgraph_update_post`, so every
depsgraph, save, load, undo and redo event schedules one check 0.1 s later.
That check redraws the 3D Viewport headers only if the state really flipped.
Nothing polls. Operators called from a script do not set `is_dirty`, so the
"plain after an edit" case can only be checked by hand.
