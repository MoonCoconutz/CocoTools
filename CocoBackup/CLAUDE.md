# CLAUDE.md — CocoBackup

Extension-specific notes. Shared conventions (headless verification, the Local
Repository dev install, releases) live in the repo root `CLAUDE.md`. The
Blender behaviour this rests on (the keyconfig layers, why an exported preset
duplicates add-on shortcuts, the "user deleted this" ghost) is in the vault
note **Blender/Keymaps and keyconfigs**; read it before changing
`keymap_diff.py`.

**Blender 5.2+ only** (`blender_version_min = "5.2.0"`), the user's decision
of 2026-09-27: the 4.5 compatibility code was removed then (a per-call check
of which key fields exist, the loose "same operator, same key" lookup that
carried 5.2 backups into 4.5, `getattr` guards around APIs 5.2 has). Use 5.2
APIs directly; do not test on 4.5.

## What it is

One JSON file (format 4) with four optional sections: `keymaps` (a diff, plus
the keymap preset in use), `preferences`, `themes` and `addons`, and a small
`machine` block (home, Blender user and install folders). Exported and
imported from the save-icon button in the 3D Viewport header or File ▸ Export
/ Import. Also an optional autosave that writes to a `Backup` folder next to
the .blend.

Format 3 added a shortcut's own settings edits (`new_props`) and nested
operator settings. Format 4 (1.2.0) added `machine`, each add-on's folder
(`dir`) and `keymaps.preset`. Formats 2 and 3 import unchanged (their paths
are moved by guessing, see below, and they carry no preset); format 1 existed
only during development and is no longer read.

## Layout

- `keymap_diff.py` — `export_keymaps()` / `import_keymaps()` / `apply_undo()`,
  and the keymap preset: `export_preset()` / `apply_preset()`.
- `prefs_io.py` — a generic RNA walker, `dump()` / `load()`, plus the section
  choices in `export_preferences()` / `export_addons()`, and moving paths
  between machines (`path_moves()` / `relocate()`).
- `themes_io.py` — theme presets and the active theme, as whole themes.
- `addons_resolve.py` — which missing add-ons can be enabled or installed.
- `autosave.py` — the autosave timer and its rotation.
- `ui.py` — the header button and its panel.
- `__init__.py` — preferences, the operators (export, import, the report
  popup and its buttons) and the File menu entries. The four "Include"
  options are the `_Sections` mixin both file operators inherit.

The operators are `cocobackup.export_backup` / `cocobackup.import_backup`:
`import` is a Python keyword, so `bpy.ops.cocobackup.import` cannot be called.

## Keymaps are a diff against stock + add-ons

Base = `keyconfigs.default` + `keyconfigs.addon`, compared with
`keyconfigs.user`. **Not** `keyconfigs.active` and not `is_user_modified`: with
a preset such as MyPreset loaded, both are relative to the preset, and the
preset's own changes would never reach the backup.

Everything goes through one pairing, `_pair()`: each user item is matched with
the stock or add-on item it is a version of. Export, import, the reset pass
and a single revert all use it, so they cannot disagree about which item is
which. Within an identity (operator + explicitly set properties, nested
operator groups included, or `propvalue` in a modal keymap): exact key, then
the same key switched on/off, then keymap order. The on/off step exists
because View Center moved to F with a switched-off copy left on Button4
paired either way round depending on keymap order (measured on the user's
setup). Then what is left pairs by operator + key ignoring properties and
on/off: a user copy can carry other properties than its stock item, and
"remove + add" would, on import, remove the add-on's merged item, which is the
permanent ghost.

A pair whose properties differ is only an edit if the user copy *set*
something differently (`_props_within`): Delete on X with `confirm` off is
recorded as `new_props`; Zen UV's Sticky UV Editor, whose MyPreset copy merely
*lost* `ui_button`, is not. 1.0 dropped every property edit from the backup.

Added items that are switched off are dropped: they do nothing, and in
practice they are switched-off add-on copies a preset baked in. An added item
is not created when the same item, or a stock/add-on item it is a
lost-settings copy of, is already on that key (the preset duplicates in the
vault note would otherwise spread), nor when its operator or the menu/panel it
opens is not registered: `keymap_items.new()` accepts an unknown operator
without complaint.

Import pairs this machine's items the same way and edits the one paired with
the backup's stock item, wherever this machine moved it. So the report's
"before" is this machine's key, not stock's, and a revert puts that back.
Backup settings this Blender's operator does not have are dropped first
(`_normalized`), or the item never compared equal and every import re-added
it. A stock item this Blender does not have is SKIPPED with the reason.

Properties written alone do not mark a keymap as edited: `is_user_modified`
stays False and the edit is gone after a restart (measured on 5.2).
`_set_state()` therefore always writes the key fields last.

Enum-flag properties must be written as a `set`. A list is refused without an
error, the item then no longer matches its spec, and every re-import added it
again (it was `mesh.select_linked_pick`'s `delimit`).

## Preferences are walked, not listed

`dump()` reads every RNA property, so new Blender preferences are covered
without code changes. It is bounded by **depth**, not by a seen-set of
`as_pointer()`: a nested struct at offset 0 shares its parent's address, and a
seen-set silently dropped whole theme sections.

`bl_*` properties are skipped both ways. On 5.2 every `AddonPreferences` and
the keyconfig preferences read `bl_idname` back as `"\x06"`, and 1.0 exported
it for every add-on, ready to be written back on another machine.

`prefs_io.MACHINE` leaves out settings that belong to the machine even though
they are not paths: `filepaths.asset_libraries` and `script_directories` (a
collection written by position renamed the other machine's libraries), the
player preset and editor arguments that go with their skipped paths, the
online-access question, and `keymap.active_keyconfig` (the preset travels with
the shortcuts instead, file included: see "The keymap preset travels").

`_load_collection` leaves an unchanged add-on collection alone. Clearing and
re-adding fires every update callback: CocoPies re-registers all its pies,
644 times for the user's settings (5.6 s of a 20 s import; switching CocoPies
on took the other 14 s).

Import order is add-on settings, preferences, themes, the keymap preset
(`_run_settings`), then the keymap diff `KEYMAP_DELAY` (0.5 s) later from a
timer (`_finish_run`, which also opens the report). An add-on may rebuild its
shortcuts when its settings change, and the diff has to land after that work,
deferred work included. CocoPies rebuilding its pies (any change to them, and
an import from another machine always changes their script paths) first
switches its X suppressions back **on** in `keyconfigs.active` and `user`, and
off again from a 0.2 s timer. Diffed in between, the user's "X delete menu
off" was stored against a stock X that was on; when the timer switched the
base's X off, Blender re-applied that diff and, finding no exact match, took
the first item with the same operator, properties and on/off on *any* key
(`wm_keymap_patch` in `wm_keymap.cc`, read at v5.2.0), and deleted the
**Delete-key** menu instead. Measured on 5.2 with the user's MyPreset and with
stock; gone with the delay. Timers fire in order of when they are due, so
0.5 s after is after.

## Add-on settings from another machine

Measured by importing the user's real backup into an isolated profile whose
add-ons sit at other paths (2026-09-29): every path in add-on settings pointed
at the export machine. CocoPies' starter scripts
(`execute_script("C:/Users/<them>/.../CocoPies/scripts/...")`) failed;
MESHmachine's `assetspath` made its `register()` crash at the next start, so
its menu (Y) drew 18 unknown operators and its shortcuts (Alt+X symmetrize,
Alt+LMB select) were gone; Zen UV lost its checker images, Hard Ops its
folders.

- **Paths move.** Export records each add-on's folder (`dir`) and the
  machine's home, Blender user and install folders (`machine`).
  `path_moves()` pairs each with this machine's, and `relocate()` rewrites any
  string starting with one of them (quoted inside a command too), longest
  first, one regex pass, keeping the string's own slash style. Older backups
  have neither: the add-on's folder is guessed from a path in its own
  settings running through a folder named after it, the rest from the usual
  `Users\<name>\AppData\Roaming\Blender Foundation\Blender\<ver>` shapes.
- **A path still missing here is not written** (`load(keep_missing=True)`, a
  KEPT row): this machine's value stays. Only a setting that *is* a path;
  a missing path quoted inside a longer string (a CocoPies command) is
  written anyway, since there is nothing of this machine's to keep, and
  listed as MISSING.
- **Settings about the machine never travel** (`MACHINE_ADDON`, fnmatch
  patterns per add-on id, dropped both on export and from older backups):
  all of Cycles (its render devices, shown under System: the user's two
  GPUs arrived as the other machine's device list) and UV Packmaster's engine
  detection, feature flags, thread count and per-device settings (imported,
  they said "engine not detected" and its operators stayed off until a
  restart).

Switching an add-on off and on in Preferences drops its settings (Blender's
`addon_disable` passes `default_set=True`): the user did that after the broken
import and lost them. Say so if an add-on misbehaves after an import; a second
import is the fix.

## The keymap preset travels

`export_preset()` stores the active keyconfig's name and, when the preset
file is the user's own (in `scripts/presets/keyconfig`), its text. A restoring
import (`use_reset_shortcuts`, the default) runs `apply_preset()` before the
diff: it writes the file (a differing one first copied to
`<name>.old-<YYYY-MM-DD>.py`, the user's own convention for MyPreset), then
`bpy.utils.keyconfig_set()`. Blender's own presets travel by name. A merging
import keeps this machine's preset and says so. A backup from before 1.2
names no preset; its diff is against Blender's own keymap, so a restoring
import of one switches to "Blender" (measured: then it matches too, only
without the user's preset file).

Why: the diff is relative to stock + add-ons, but the target's own preset is
its base. With the user's other machine running an older MyPreset, the
restoring import left 17 live bindings that differ from the source (4.x
`object.subdivision_set` without `ensure_modifier`, Ctrl+S without its 5.x
option, a removed select brought back by the reset pass pairing it with the
stock item) and 65 to 94 dead ones, and could not tell that preset's baked
add-on copies from the add-ons' own. With the same preset on both, the result
matches item for item.

The file is run by Blender (now and at every start), so `_is_keymap_preset()`
only accepts the shape Blender's keymap export writes: `keyconfig_version` and
`keyconfig_data` as literals and the `if __name__ == "__main__":` loader
calling nothing but `keyconfig_import_from_data` and `os.path` helpers. The
user's 5.2 MyPreset and both older ones pass; Blender's own `Blender.py` does
not (it is code), which is fine, since those travel by name.

A revert row puts an item back to its state after the preset switch, not
before it; the switch itself is a report line, not revertable.

## Testing

Keymap tests need a real window: under `--background` the default keyconfig
holds 12 items instead of thousands. Run them in **isolated profiles**:
`BLENDER_USER_RESOURCES` pointed at a scratch folder, a local extension
repository added there pointing at this working tree, CocoBackup enabled for
real (`addon_utils.enable("bl_ext.<repo>.CocoBackup", default_set=True)`) and
preferences saved *in that profile*. That exercises the real registration and
add-on preferences, can save and restart, and never touches the user's own
config. Keep a clean copy of each profile and copy it back per scenario. Load
a home file from a step only with a persistent timer: `read_homefile` drops
the others and the script never quits.

What was checked on 5.2, 2026-09-27, with every kind of change (moved,
switched off, settings-only, removed, added, macro with nested settings,
`any`, `key_modifier`, drag direction, modal map, add-on items, keymap
setting):

- source export → restart → re-export identical;
- import into a target with its own conflicting changes: the keyconfig equals
  the source's, the report shows the target's own keys, the five target-only
  changes are reset, Node Wrangler (off there) is switched on first, and the
  result survives Save Preferences + restart;
- Revert Selected puts back exactly the target's previous state (moved,
  added, removed, brought-back and settings rows);
- a second import restores reverted rows, a third reports nothing;
- merge mode keeps the target's own five changes and applies the backup;
- the user's real 1.0 backup into a fresh profile: 40 applied, 5 skipped
  naming the missing add-on, no `bl_idname` written, asset library intact;
- the user's real setup (MyPreset, 37 add-ons), in memory with
  `use_preferences_save = False`: export 0.16 s (1.0: 0.48 s); keymap_restore
  all + import gives identical live items. Two switched-off MyPreset copies
  the user had deleted come back because the test restores to the preset;
  a stock-relative diff cannot remove what is not in stock.

Known interaction: CocoPies writes suppressions into `keyconfigs.active`,
which is `keyconfigs.default` when no preset is loaded, and on every rebuild
switches them back on and off again 0.2 s later. A user diff made in between
is re-applied by Blender onto the changed base with its fallback, and the
Delete-key menu went. The import now waits for it (`KEYMAP_DELAY`, above);
CocoPies writing into the base keyconfig at all is its own bug, still open.

Checked on 5.2, 2026-09-29, simulating the user's other machine: an isolated
profile with the user's 30 add-ons copied to other paths, their real backup
rewritten as if made under another Windows user, targets running stock, the
user's current MyPreset and two older ones (4.5 and 2023), each imported,
saved, restarted and compared binding by binding (command, settings, key,
on/off, live or dead) with the user's own live keyconfig:

- 1.1.0: MESHmachine failed at start (its menu full of unknown operators,
  Alt+X symmetrize gone), paths pointed at the other user's folders, Cycles
  got the other machine's GPUs, UV Packmaster read "engine not detected", the
  Delete-key menu went, and with an older MyPreset 17 live and up to 94 dead
  bindings differed.
- 1.2.0, new backup: every target (stock, current MyPreset, both older ones,
  and the 4.5 one with four hand edits of its own) ends with the same live
  bindings as the source; the one difference is CocoPies' Quick Tap command,
  whose script path is now this machine's. No duplicates, no dead items, all
  menus draw, MESHmachine registers, the Delete-key menu stays. The hand
  edits come back as four RESET rows.
- 1.2.0, the user's old (format 3) backup into the 4.5 target: paths guessed
  right, the preset switched to "Blender", same live bindings as the source.
- a second import changes no shortcut; Revert Selected undoes two added rows;
  a merging import keeps the target's MyPreset and says it differs.

The harness (profiles, dumps, the binding-by-binding comparison) lived in the
session's scratchpad; rebuild it from the description above if needed.

## The header button

Appended to `VIEW3D_MT_editor_menus`, the row that draws View / Select / Add /
Object, so it lands after those menus and after what other add-ons append
there (Machin3, Hard Ops, PowerSave...), where the user asked for it. It is a
`layout.popover`, so the panel opens anchored under the button like View /
Select, with a dropdown arrow the user decided they want. It was a
`wm.call_panel` icon button first (no arrow), but that opens the panel wherever
the mouse is. For no arrow, a row with `emboss = 'PULLDOWN_MENU'` draws the
popover without it. The panel's buttons force `INVOKE_DEFAULT`: under
`wm.call_panel` they ran with EXEC, which skipped the file browser and
exported to an empty path.

## Missing add-ons: switched on first, offered to switch off

`addons_resolve.classify()` sorts each add-on the backup names but this
machine is not running into disabled (installed, switched off), available
(listed by an online repository Blender has already synced) or unavailable.
The import operator enables or installs every disabled or available one
**before** anything else is applied. Done later, an add-on's tool shortcuts
(Bool Tool's Box Carve) had no operator yet, read as Blender's own, and the
reset pass removed them as "you had added it". As a second guard,
`keymap_diff._command_exists()` keeps the reset pass away from any shortcut
whose operator, or the menu or panel it opens, is not registered.

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
click, and reopening it stacked a second copy on top. They only redraw. The
last row has a Save Preferences button (`wm.save_userpref`).

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
and when nothing changes the popup says so in one line. SKIPPED rows say why
("MACHIN3tools is not enabled here").

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
row in the report, so nothing is overwritten unless the user says so. The
active theme's key in the overwrite set is `themes_io.ACTIVE` =
"<active theme>". It used to be "\0active", and a StringProperty truncates at
NUL, so a ticked "replace" arrived as "" and was silently kept.

## Autosave

`autosave.py`: a persistent `bpy.app.timers` tick every N minutes (addon
preferences, also in the header panel) writes
`<name>_autosave_<dd-mm-YYYY_HH.MM>.blend` in a `Backup` folder next to the
file (created on the first autosave) with `save_as_mainfile(copy=True)`, so
the open file keeps its path and dirty state, and deletes all but the newest
M. It writes only when `bpy.data.is_dirty` and a `depsgraph_update_post` since
the last autosave or save flagged a change: without `is_dirty`, the depsgraph
updates that follow opening a file made the first tick save an untouched file.
It skips unsaved files and renders. The name is day-first because the user
asked for it (`/` is not allowed in Windows names), so it does not sort by
date: rotation sorts by modification time. Two autosaves in the same minute
overwrite each other.

A modal operator in progress (a drag, a stroke) is waited for, retrying every
2 s, like Blender's own autosave. One running for over `LONG_MODAL` (60 s) is
a mode, not a drag, and is not waited for: CocoUVs' Draw mode stays running
while the user works (seen in their live session), and would otherwise stop
autosave for good. Operators are told apart by pointer + `bl_idname` from
`Window.modal_operators`.

Verified on 5.2 with simulated input (`--enable-event-simulate`): a clean
file and a never-saved file are skipped, one autosave follows a G-drag and
the file keeps its path and dirty state, nothing is written mid-drag and the
save follows right after, a modal older than `LONG_MODAL` no longer blocks,
rotation keeps the newest by time. The first simulated key after startup is
lost; send a warm-up hover and drag first.

## Import restores, it does not just add

A diff only touches what it names, so a shortcut changed after the export
(the user's test: Eyedropper Colorband E -> F, View2D Scroller Activate
switched off) survived the import and the report was silent about it.
`import_keymaps(reset_extra=True)` therefore re-diffs after applying and puts
back to stock every change the backup does not contain: a moved, switched-off
or re-set item back to its stock key and settings, a user-added item removed,
a removed stock item re-created. Each one is a RESET line in the report. The
import dialog's "Undo shortcut changes not in the backup" (on by default)
turns it off, for merging a backup into a machine's own customisations
instead; then an item the backup moves keeps this machine's own settings.

A re-created stock item goes at the end of its keymap: there is no API to put
an item back where it was, and position only matters against another item on
the very same event.

## Shortcut rows, and reverting one

`import_keymaps()` returns one dict per shortcut: word, owner, keymap, what
(`describe()`: the operator's or menu's title, the modal action's own name
from `km.modal_event_values`, or a generic operator with its data path),
event (`change_event()`: "Key changed", "Switched off", "Settings
changed"...), key before/after on this machine (`key_label()`: `any` reads
"Esc (any modifier)", a held key reads "Q+I", a drag "(Click Drag North)"),
and an `undo` recipe: the item paired with a stock item (or, for an added
one, the item in its after-state) goes back to its before-state, where no
state means it did not exist. `cocobackup.revert_selected` replays
`apply_undo()` for the ticked rows only ("Revert Selected Shortcuts"), and
refuses when the shortcut was changed again since. Shortcuts put back by the
reset pass sit under their own sub-heading.

`_set_key()` goes through `_set_type()`: an item's `type` only accepts events
of its current `map_type` (a mouse item refuses "F"), the keymap editor
switches map_type for you and RNA does not, and the refusal used to be
swallowed. Found testing Fill Tool Modal Map: moving its Middle Mouse item to F
and back silently did nothing.

## The save icon shows whether the file is saved

A floppy-disk save icon in three colours (`icons/`), chosen by
`ui.file_state()`. It replaced the user's coconut drawings. The PNGs are
generated (128 px, flat colour, shutter and label cut out); the colours are the
user's own choice:

| State | Condition | Icon |
| --- | --- | --- |
| unsaved | `bpy.data.filepath` empty: the file is nowhere on disk | `save_unsaved.png`, red `#C8575C` |
| saved | a path, `bpy.data.is_dirty` false | `save_saved.png`, green `#8ED67F` |
| modified | a path, `is_dirty` true | `save_modified.png`, grey `#6C6C6C` |

The panel's own title uses the grey one.

Red means only "never saved", not "has unsaved changes"; the user was explicit
about that. `is_dirty` flips
after an operator's undo push, which is after `depsgraph_update_post`, so every
depsgraph, save, load, undo and redo event schedules one check 0.1 s later.
That check redraws the 3D Viewport headers only if the state really flipped.
Nothing polls. Operators called from a script do not set `is_dirty`, so the
"grey after an edit" case can only be checked by hand, or with simulated
input.
