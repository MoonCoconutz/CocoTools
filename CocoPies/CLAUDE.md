# CLAUDE.md (CocoPies)

Extension-specific notes for CocoPies. Shared conventions (target Blender
versions, the headless verification pattern, the release pipeline) live in
the repo root's `CLAUDE.md` — this file only covers what's specific to
CocoPies.

**Procedures live in `CocoPies/docs/`** — start at
[docs/agents-start-here.md](docs/agents-start-here.md). This file is the
reference; those are the task-shaped versions (verifying a change,
publishing, architecture map, what is unfinished). The repo root's
`.claude/agents/` holds subagents for the three recurring jobs.

## What this is

CocoPies is a Blender addon (Python, `bpy`) that lets a user build custom pie
menus entirely from the addon's own Preferences panel — no code required for
day-to-day use. See `README.md` for the user-facing feature set (slot model,
command forms, presets, icons); this file covers what's needed to develop and
verify changes safely.

CocoPies is packaged as a **Blender Extension** (`CocoPies/blender_manifest.toml`),
not a legacy add-on — there is no `bl_info` dict, and Blender will actively
strip one and print a deprecation warning if it ever reappears in
`__init__.py`. `id`/`name`/`version`/`blender_version_min` all come from the
manifest now; `utils.py`'s `addon_version_string()` reads it lazily via
`addon_utils.module_bl_info()` (works for either format, but only actually
parses the manifest when the loaded module's name starts with `bl_ext.` —
see the root `CLAUDE.md`'s headless-verification note).

## Target versions

**Must work on both Blender 4.5 and 5.2** (LTS releases the user actually
runs — installed under `C:\Program Files\Blender Foundation\`). An API that
exists on one and not the other is a real bug, not an edge case. Confirm any
non-trivial `bpy` API actually exists on both before relying on it — read
`bpy.types.X.bl_rna.functions[...]` / check via a headless run rather than
trusting memory of the API.

## Verifying a change

There's no Python on `PATH`; use Blender's own interpreter, headless:

```bash
"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" --background --python <script>
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <script>
```

Run against **both** versions before considering a change verified. Expect
noisy, unrelated `SystemError: GPU functions...` tracebacks from other addons
in the user's stack (they run headless-unfriendly code at import) — grep for
your own marker output rather than treating any traceback as failure.

Load the addon package under a **unique module name** in the verification
script, not `import CocoPies` — that resolves to the already-installed copy
and double-registers every class, which surfaces as a misleading
`ValueError: already registered as a subclass`:

```python
import sys, importlib
for name in list(sys.modules):
    if name == "CocoPies" or name.startswith("CocoPies."):
        del sys.modules[name]
spec = importlib.util.spec_from_file_location(
    "CocoPies_verify", r"<repo>\CocoPies\__init__.py",
    submodule_search_locations=[r"<repo>\CocoPies"])
mod = importlib.util.module_from_spec(spec)
sys.modules["CocoPies_verify"] = mod
spec.loader.exec_module(mod)
mod.register()
# ... assertions ...
mod.unregister()
```

`context.preferences.addons["CocoPies_verify"]` will **not** exist under this
loading method — `context.preferences.addons[name]` is only populated by
Blender's real `addon_enable` machinery, not by calling `register()`
directly. For anything that needs real `AddonPreferences` data (keymap
registration counts, a pie's stored items), either drive it through a
scratch `PointerProperty` on `bpy.types.Scene`, or verify live against the
actually-installed copy instead (see below).

`Operator.__subclasses__()` under `--background` under-reports registered
operators; treat an empty result as inconclusive, not proof of absence.
Preview icons (`bpy.utils.previews`) need a GPU, so `icon_id` is `0` headless
— that's a false negative, not a real bug; check those in a live session.


## This extension's git history predates this monorepo

CocoPies used to be its own repository (`MoonCoconutz/CocoPies`, deleted on
2026-08-31) and was folded into CocoTools via `git subtree`, with its full
commit history preserved — including two folder renames before this repo
even existed (`cocopie/` → `CocoPie/` → `CocoPies/`). A plain
`git log -- CocoPies/keymaps.py` from the CocoTools root will **not** show
that pre-merge history — git's path-based log traversal doesn't cross a
subtree merge's prefix boundary automatically. To see it, go through the
merge commit's second parent explicitly:
```bash
git log --oneline <subtree-add-merge-commit>^2 -- keymaps.py
```
(paths are relative to the old repo's root, i.e. without the `CocoPies/`
prefix, on that side of the merge). The commits are genuinely there and
reachable — this is just a log-traversal quirk, not lost history.

## Verifying live, and the dev install

CocoPies is developed through the repo-wide **Local extension repository**
described in the root `CLAUDE.md` — it points at the CocoTools working
directory root, and `CocoPies/` (this folder, containing
`blender_manifest.toml`) is one of the extensions it lists. Editing a file
here *is* editing the live install; no copy step. `icons/custom/` lives
directly in `CocoPies/icons/custom/` (still not committed — it's the user's
own icons).

When a Blender MCP connection is available, prefer verifying directly
against the live, running instance over guessing from a headless run — it
catches things headless can't (real popups, real keymap dispatch, real
preferences persistence).

To load new code into the running session you must clear this extension's
modules from `sys.modules` and re-register — copying files alone does
nothing (Blender caches the loaded modules, and this dev setup has no copy
step anyway), and `importlib.reload()` is not enough for a package since it
does not reload submodules. Use the `addon_utils` form below, **not**
`addon_disable` / `script.reload`.

**Reload with `addon_utils`, not `bpy.ops.preferences.addon_disable`.**
`bpy.ops.preferences.addon_disable` passes `default_set=True`, which makes
Blender drop the addon's whole entry from `preferences.addons` — every stored
pie menu with it. Re-enabling builds a blank entry, `register()` then sees an
empty collection, concludes "fresh install" and seeds the starter pies into
it. The user's pies come back looking *reverted* because they have been
replaced by same-named starters. Five sessions read that as Blender corrupting
data across a reload; it was CocoPies overwriting its own data. Use (with the
real module name substituted for `<addon_id>`, e.g.
`bl_ext.CocoTools.CocoPies` on this machine):

```python
import addon_utils, sys
addon_utils.disable("<addon_id>", default_set=False)
for n in [m for m in sys.modules if m == "<addon_id>" or m.startswith("<addon_id>.")]:
    del sys.modules[n]
addon_utils.enable("<addon_id>", default_set=False, persistent=True)
```

`default_set=False` leaves `preferences.addons` untouched, so the stored data
survives. Confirmed under the current `bl_ext.CocoTools.CocoPies` name on
2026-08-31, snapshotting every pie's name, items, commands and icons to JSON
either side of a dozen reloads: zero differences each time. Don't use
`bpy.ops.script.reload()` either: it reloads every other addon in the user's
stack for nothing.

`register()` also guards the starter-pie seeding behind a module-level
session flag, so only the first `register()` of a session may ever seed.
Keep that guard — without it a user who unticks and reticks CocoPies in the
Add-ons list loses their pies to starters.

**Any reinstall that changes where this package physically lives** (a
machine move, a repo rename, moving to yet another monorepo) orphans the
saved `AddonPreferences`, since it's keyed by `ADDON_ID = __package__` —
there is no automatic carry-over. The safe path is always: **Save Preset**
(exports the *entire* `pie_menus` collection to plain JSON) before the
change, **Load Preset** after. `presets.py`'s `_apply_pie_dict` already
repoints a bundled starter-pie script's `execute_script(...)` path to
wherever `CocoPies/scripts/workspaces/` currently resolves to if the
original path is missing, so this round-trip is safe across a location
change, not just a same-machine backup.

The Preferences window, when open as a **second** OS window, cannot be
screenshotted (the screenshot tool only reaches window 0) and popups are
transient — never switch a `VIEW_3D` area to `'PREFERENCES'` to work around
this, it silently becomes `'PROPERTIES'` instead and costs the user their
viewport. A UI change needs the user's own eyes; ask for a screenshot rather
than trying to force a capture.

**Starter seeding is by record, not by absence** (`defaults.py`). Startup
calls `sync_starter_pies()`, which adds only starters whose name is not in
`prefs.seeded_starters` (a JSON list of every starter this config has ever
been given), then records them. That is what makes a starter added in a new
version appear on its own, while a starter the user deleted on purpose stays
deleted instead of returning at every startup. `ensure_default_pies()` is the
*deliberate* restore behind the Restore Starter Pies button — it adds anything
missing regardless of the record. Do not "simplify" startup back to
`ensure_default_pies()`: that resurrects deleted starters forever.

Snapshotting `prefs.pie_menus` to JSON around a reload is still worth doing as
a check, but it should now come back with zero differences. If it ever differs
again, something new is wrong — diagnose it rather than reaching for the
rebuild and moving on.

The Preferences window, when open as a **second** OS window, cannot be
screenshotted (the screenshot tool only reaches window 0) and popups are
transient — never switch a `VIEW_3D` area to `'PREFERENCES'` to work around
this, it silently becomes `'PROPERTIES'` instead and costs the user their
viewport. A UI change needs the user's own eyes; ask for a screenshot rather
than trying to force a capture.


## Architecture

**The data model.** A pie menu (`COCOPIE_PieMenuData`) always has exactly
eight items (`COCOPIE_PieMenuItem`), one per compass direction, indexed by
`position` 0–7 in Blender's own pie slot order (`items.py`: `POSITION_NAMES`,
`POSITION_ARROWS`). `ensure_slot_items()` (`utils.py`) guarantees this
1:1 mapping and is idempotent — called defensively before anything indexes
by position. `slot_is_used(item)` (a label or a command present) is what
distinguishes a configured direction from an empty one; nothing ever adds or
removes item rows, only fills or clears them.

**Registration is a full rebuild, not incremental.** Any settings change
(name, shortcut, an item's command...) calls `update_pie_menu()` →
`register_pie_menus()` (`keymaps.py`), which unregisters everything and
rebuilds every pie's `Menu` class and keymap items from scratch. This is
simple but means `unregister_pie_menus()` must be genuinely thorough —
see the next point.

**The Pie Menus list is grouped into sections by editor, display-only.**
`pie_menu_groups()` (`utils.py`) buckets pies by scope — one section per
editor, plus a "Multiple Editors" section for any pie with more than one
scope — and `draw_left_column()` (`preferences.py`) draws each section as a
heading label followed by its *own* `template_list`. Each section's list is a
generated `UIList` subclass (`GROUP_UILISTS` in `ui/lists.py`, one per key in
`utils.GROUP_KEYS`) whose `filter_items` shows only that section's pies and
never permutes order. Two things here are non-negotiable, both learned by
breaking them: the stored collection is **never** reordered to match the
display (doing it with `.move()` corrupted stored pies), and a section
heading is **never** drawn inside `draw_item` (it becomes part of the first
pie's row, stealing that row's click and selection highlight). Storage order
and display order are independent by design, which is also why the ▲/▼
reorder buttons can look off near a section boundary.


**Keymap items must be swept by content, not trusted from a Python list.**
`registered_keymaps` (module-level in `keymaps.py`) only reflects items
created by *this* module instance, which is empty again after every
disable/enable cycle or "Reload Scripts" — even though real keymap items
from a *previous* load can still be sitting in Blender's keyconfig.
`keymap_items.new()` always appends, never replaces, so orphans compound
silently across reloads. `unregister_pie_menus()` therefore sweeps every
keymap CocoPies could have touched (`KEYMAP_CONFIG` scopes ∪
`WINDOW_MODE_KEYMAPS`) for any `wm.call_menu_pie` item whose `properties.name`
starts with `COCOPIE_MT_`, or any `cocopie.hold_or_tap` item, and removes
them directly — regardless of what `registered_keymaps` says. Any *new*
CocoPies-owned keymap idname added in the future must be added to this sweep,
or it will orphan the exact same way.

**Hold vs. tap on one keyboard key** (`COCOPIE_OT_hold_or_tap` in
`operators/pies.py`) is hand-timed with a modal operator + `event_timer_add`,
not a native Blender event value. `CLICK_DRAG` requires the mouse to actually
move (it's built for mouse-button drags); `RELEASE` fires identically
regardless of hold duration. Neither can distinguish "held the key" from
"tapped it" on its own. When a pie's `tap_toggle` is on, this operator
replaces the pie's own `wm.call_menu_pie` keymap item entirely (bound to
`PRESS`); the pie's `event_value` field becomes cosmetic (forced to
`CLICK_DRAG`/"Drag" for UI honesty, but unused by the actual dispatch).

**The addon's identity is its module name, not a constant.** `ADDON_ID =
__package__` (`utils.py`) — Blender stores `AddonPreferences` keyed by the
addon's module name, so renaming/moving the `CocoPies/` folder orphans every
saved pie menu (this has happened more than once in this addon's history).
As an extension, that module name is `bl_ext.<repo_module>.CocoPies` rather
than a bare `"CocoPies"` — installing to a different repo, or renaming the
repo, changes it exactly the same way a folder rename used to. Any code
that needs the addon's own identity must derive it from `__package__`,
never `__name__` (which is the *submodule's* dotted path, e.g.
`CocoPies.utils`, and matches nothing).

**`KEYMAP_TYPE_ITEMS` numbers are frozen on-disk data** (`items.py`). Blender
saves an `EnumProperty` as its *integer* value, not the identifier string, so
those numbers are the stored format of every scope the user has ever set.
Without explicit numbers Blender assigns them by position — and the
`("", "Modes", "")` headings each consume one — so **inserting an item in the
middle renumbers everything after it and repoints stored pies at the wrong
editor**. Adding `OBJECT_NONMODAL` mid-list did exactly that: `3D_VIEW` moved
13 → 14, a stored pie holding 13 landed on the "Editors" heading, resolved to
`""`, registered no keymap, and vanished from the Pie Menus list entirely.
Every item now carries an explicit number. A new scope takes the next unused
number (see the "Next free number" comment at the end of the list) and may go
anywhere in the list for display; never renumber an existing one, and never
reuse a retired one. The same applies to any other user-facing enum whose
value gets stored — a pie's `event_value`, an item's icon choice.

`normalized_scope()` (`utils.py`) is the seatbelt for when it goes wrong
anyway: any scope that is not a `KEYMAP_CONFIG` key — `""` from an orphaned
integer, or a value from a newer version — resolves to `'WINDOW'`, and
`pie_scope_types()` never returns empty. It is applied in that one place so
the section list, the keymap registration and the conflict check cannot
disagree. There is deliberately no section for "no editor": a pie whose group
key matched no section was drawn by no section at all, which made it invisible
in Preferences and so impossible to repair.


**Entry points worth not re-grepping for.** `menus.py`:
`create_pie_menu_class(pie_data)` (note: *create_*, not build_),
`execute_script()`, `_parse_bpy_ops_call()`. `keymaps.py`:
`register_pie_menus()` / `unregister_pie_menus()`. `defaults.py`:
`default_pie_definitions(script_paths)`, `bundled_script_paths()`,
`sync_starter_pies()`, `ensure_default_pies()`. `presets.py`:
`_apply_pie_dict(pie, definition)` — the shared "dict → stored pie" writer
used by starters, presets and imports alike. `utils.py`: `get_prefs()`,
`pie_scope_types()`, `keymap_names_for_pie()`, `pie_menu_groups()`,
`ensure_slot_items()`, `slot_is_used()`. `ui/lists.py`:
`COCOPIE_UL_pie_menus`, `GROUP_UILISTS`.

**Headless stand-in for `AddonPreferences`.** Anything taking `prefs` only
touches `pie_menus`, `active_pie_index` and `seeded_starters`, so a scratch
`bpy.types.Scene` carrying those three properties under those exact names can
be passed straight into `sync_starter_pies()`, `pie_menu_groups()`,
`filter_items()` and friends — no `addon_enable` needed. Combined with the
unique-module-name loader above, that covers most verification without a live
session. A `UIList` method can be called as
`SomeUIList.filter_items(fake_self, context, data, "pie_menus")` where
`fake_self` is a `types.SimpleNamespace` carrying `bitflag_filter_item` and
whatever class attributes the method reads.


**Commands are `exec()`'d Python**, not a restricted DSL
(`operators/context_menu.py`, `operators/pies.py`). A pie item is exactly as
trusted as any script the user would run in Blender. `execute_script(path)`
resolves relative to nothing in particular — bundled scripts resolve their
own path from the addon's install location at creation time, since an
absolute path baked into a starter pie does not survive moving between
machines or Blender versions.

**Bundled scripts vs. inline commands**: `CocoPies/scripts/workspaces/` are a
worked example of the `execute_script()` slot form; `CocoPies/scripts/uv/`
exists only for the few operations Blender genuinely has no operator for.
Prefer a real `bpy.ops` command over a bundled script whenever one exists —
scripts are a last resort, not the default, and a script that turns out to
duplicate a real operator (this has happened) should be deleted along with
its starter-pie reference, not kept "just in case."

**Right-click "Add to CocoPies"** (`operators/context_menu.py`) is built from
real nested `Menu` classes (`COCOPIE_MT_add_to_cocopie`, and a pre-registered
pool of `COCOPIE_MT_cocopie_dirs_N` submenus, one per pie slot in the pool,
capped at `MAX_PIE_SUBMENUS`), not chained `popup_menu()` calls. Clicking an
entry in a `popup_menu()` tears that popup down, and a second `popup_menu()`
opened during the same click is destroyed along with it — silently, with no
error. A submenu is drawn by the menu system itself rather than spawned from
a click, so it isn't subject to that teardown. The button under the cursor is
captured once, at the *top-level* context menu's draw time (where
`context.button_operator` / `button_prop` are actually available), and
stashed module-level (`_CAPTURED`) for the submenus — which get no draw
arguments — to read.

## Keymap gotchas (learned the expensive way, 2026-09-02)

**A `PRESS` binding beats `CLICK`/`CLICK_DRAG` at any keymap position.** They
are different events at different times: on key-down Blender emits `PRESS` and
walks the keymap, a `CLICK` item cannot match it, and the walk continues to
whatever `PRESS` item exists further down. Measured: CocoPies at `Mesh[9]` and
`Mesh[10]`, Blender's native X delete at `Mesh[112]`, and Blender still won.
Position is irrelevant; the only fix is switching the other item off. This is
why Quick Tap's `CLICK_DRAG`/`CLICK` pair needs `suppressed_bindings` at all.

**`keyconfigs.user` is the dispatch keyconfig, even when a preset is active.**
Selecting a keymap preset makes it `keyconfigs.active`, but Blender builds
`user` by merging that preset with `addon` and the user's own edits, and `user`
is what fires. On this machine `active` is "MyPreset" and has *zero* CocoPies
items in it, while `user` has 38. Read and write `user`; reading `active` was a
wrong turn that cost an hour.

The conflict *scan* went on reading `active` anyway until 2026-09-04, and it
failed three ways at once, all measured live under "MyPreset" (16 keymaps /
936 items against `user`'s 293 / 3682). It **missed** live conflicts, since
277 keymaps were never looked at — Blender's Delete in "User Interface" never
showed against the Mesh Delete pie. It **invented** dead ones, reporting a
"Sticky UV Editor" binding that exists only inside the saved preset file,
with a checkbox offering to switch off something that was not running. And it
**mislabelled** what it did find, calling a stock Object Mode binding a custom
3D View one, because the preset's copy is what got compared against `default`.
Reading now goes through `merged_keyconfig()` and writing still through
`live_keyconfigs()` — those two are separate functions on purpose.

**The two conflict checks must share their rules.** `find_external_conflicts`
(pie vs everyone else) and `find_shortcut_conflicts` (pie vs pie) drifted
apart, and the weaker one was the one covering the pies the user can actually
fix: it compared keymap names without `_ancestor_keymaps` and event values by
equality. So a CocoPies pie on W in "3D View" drew no warning against one on W
in Sculpt, while *Blender's* W in "3D View" was reported against that same
Sculpt pie; and a PRESS pie silently ate a CLICK_DRAG pie's key. Both now go
through `_ancestor_keymaps()` and `_values_contend()`. The ancestor test is
two-sided — a "3D View" binding is live in Sculpt, a Sculpt one is not live
elsewhere in the 3D View, and either way round they fight while sculpting.

**Which addon a binding belongs to is recoverable, but not from the keymap.**
A `KeyMapItem` records nothing about who created it and `keyconfigs.addon` is
one undifferentiated pile, so "Add-on" was as much as the panel could say. A
registered Python class does remember its defining module, though, so
`_binding_owner()` reads `bpy.types.<OP>.__module__` and maps it back through
`preferences.addons` to the addon's display name. The operator alone is not
enough — a large share of an addon's shortcuts run through Blender's own
`wm.call_menu`/`call_menu_pie`, whose class is C code belonging to nobody, so
the menu/panel id from `_kmi_detail()` is tried second and is what actually
finds Node Wrangler and HardOps. Measured on this machine: 376 of 396 add-on
bindings named. The remainder are `wm.context_set_enum`-style bindings (the
detail is a data path, not a class) and operators whose addon is not currently
registered; both fall back to the plain "Add-on".

**`binding_identity()` is stored data.** It is what `suppressed_bindings`
entries are matched by, so widening it makes every suppression the user has
already ticked stop matching — silently, the row just returns unticked with
the setting gone. That is why `_kmi_detail()` (which tool/panel/property a
generic binding points at, so a row reads "Set Tool by Name:
builtin.select_box" instead of naming the operator every tool shortcut
shares) is display-only and deliberately not part of the identity.

**A user keymap is a diff, and a removal in it is permanent.** Blender stores
`keyconfigs.user` as a diff against default+addon. Remove an addon item from
the *user* keyconfig while its addon twin still exists, and the diff records
"the user deleted this" — after which the merge re-applies that deletion
forever. Re-adding the addon item and calling `keyconfigs.update()` does not
bring it back, and neither does restarting: the entry lives in
`userpref.blend`. This is what left the user's Mesh Flatten pie on Shift+X
doing nothing while every other pie in the same keymap worked, with the panel
showing it as bound and no conflict to explain it — the `keyconfigs.update()`
call in `register_pie_menus` was not enough on its own. Reproduced from
scratch 2026-09-04 (`_mirror_missing_items`' comment block has the sequence).
Two rules come out of it:

- A binding that did not survive the merge must be written into
  `keyconfigs.user` directly (`_mirror_missing_items`) — the only route left,
  and it holds across later updates.
- CocoPies must **never** remove one of its merged copies while the addon item
  still exists, or it creates that ghost against itself next session.
  `_sweep_user_keyconfig` therefore runs only after the addon sweep *and* a
  `keyconfigs.update()`; the same experiment confirms that order leaves no diff
  entry behind. Do not reorder those two steps.

**The mirror has to be deferred, like suppression.** At Blender's own startup
the user keyconfig has no keymaps yet when `register()` runs, so the check
found nothing to compare against, repaired nothing, and the ghosted shortcut
stayed dead for the whole session — while the identical code repaired it
perfectly on any later rebuild. It now runs from
`_apply_suppressions_deferred` alongside the suppression pass. Verified
end-to-end against a real ghosted binding: repaired at startup, no duplicates
across rebuilds, nothing left in the dispatch keyconfig after unregister, and
a clean re-register afterwards.

**Never write `kmi.active` during `register()`.** Blender merges addon keymaps
into `user` on its own schedule, after `register()` returns. Setting `active`
on a keymap before that merge lands makes Blender skip the merge for that
keymap *permanently* -- Mesh and Curve ended up with 0 of their 11 and 7 addon
items while Weight Paint, which nothing suppressed, took all 4 of its own.
Un-suppressing does not undo it and neither does `keyconfigs.update()`; the
keymap stays stuck until Blender restarts. `keymaps.py` defers the suppression
pass to a `bpy.app.timers` callback for exactly this reason -- do not "simplify"
it back into `register_pie_menus`.

**"Was it on before we touched it" can only be asked once.** Suppression turns
an item off, Save Preferences writes that into `userpref.blend`, and from the
next launch every check sees an already-off item. Recomputing the restore flag
per register therefore concludes the user disabled it by hand and declines to
restore -- leaving the key dead after CocoPies is removed. `record_prior_state`
runs at ticking time only; `apply_suppressions` must never touch that flag.

## Blender UI layout gotchas (learned the expensive way)

- An icon-only button **collapses to its content** instead of filling its
  share of a row, and `ui_units_x` on the row does **not** change that — the
  cell gets the width, the button stays one unit wide inside it. `scale_x` is
  the only thing that resizes the button itself. Measured in a real window:
  the button is exactly one widget_unit square before scaling, and `scale_x` /
  `scale_y` multiply that same unit, so equal numbers give a square button.
  Set both: `ui_units_x` on the cell so the table header lines up with the
  rows, `scale_x` on the button so it fills the cell.
- **An icon is only drawn at icon size if it is an icon.** A built-in icon or a
  `bpy.utils.previews` image draws ~18px centred inside its button. Triangle
  geometry loaded with `bpy.app.icons.new_triangles_from_file()` draws ~31px —
  bigger than the 23px button, which does not grow to fit it. That is not
  cosmetic: the button is the click target and the selection highlight, so an
  overflowing icon means only a corner of it is clickable, the highlight hides
  underneath it, and neighbours in a grid touch whatever spacing the layout
  asks for. The sculpt brush icons therefore ship **both** ways in
  `CocoPies/icons/brushes/` — a `.png` and a `.dat` per brush — and which one
  is used depends on the button. Everywhere a button is icon-sized (the icon
  picker, the Preferences list) the PNG is right, and `icon_args()` returns
  it. In a pie slot the button is a wide bar with nothing to overflow, and the
  extra size is the point, so `pie_icon_args()` returns the geometry instead.
  Do not "unify" these back onto one path: going all-PNG makes pie icons tiny
  again, and going all-geometry brings back the picker bug above.
- **Never wrap a pie slot in a box or a column.** Blender only draws its
  number shortcuts on a slot that is a direct child of the `menu_pie()`
  layout, so a wrapped slot silently loses the keyboard number that picks it,
  and the bar splits into a clickable half and a dead half. Confirmed in a
  real window, wrapped and plain slots side by side in one pie. This is what
  makes `template_icon()` unusable for enlarging a pie slot's artwork, and why
  the geometry path above exists.
- `separator(type='LINE')` only renders as a visible divider stacked in a
  **column**; inside a row it's just a stray dash. A row separator adds
  height and no width, which is why a square popup and a row separator are
  mutually exclusive.
- Centering something *inside* a fixed-width cell needs an inner row —
  `alignment='CENTER'` on the container itself makes the container shrink to
  its content instead.
- A label insets its icon differently from a button; use a disabled button,
  not a label, to align with neighboring buttons.
- There is no diagonal arrow icon anywhere in Blender's ~1000 built-ins (all
  `TRIA_*` / `EVENT_*_ARROW` are cardinal only) — the eight-direction slot
  arrows are custom PNGs in `CocoPies/icons/` for exactly this reason.
- `UIList`/`template_list` has no drag/drop/reorder hook from Python at all
  — `sort_reverse`/`sort_lock` only affect display order, not the underlying
  collection.
- A `UIList` **cannot carry section headings inside itself**. Drawing one in
  `draw_item` makes it part of that item's row (it takes the row's click, and
  the selection highlight lands on the heading instead of the name).
  Stashing state on `self` in `filter_items` for `draw_item` to read back
  does not work either — Blender does not guarantee the same Python instance
  serves both calls in one redraw, so the stash comes back empty. Use one
  `template_list` per section with headings as plain labels between them.
- `UIList.list_id` exists on 4.5 and 5.2, but what it holds at filter time
  can't be confirmed headlessly — prefer a registered subclass per list over
  branching on it.
