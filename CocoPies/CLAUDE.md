# CLAUDE.md (CocoPies)

Extension-specific notes for CocoPies. Shared conventions (target Blender
versions, the headless verification pattern, the release pipeline) live in
the repo root's `CLAUDE.md` — this file only covers what's specific to
CocoPies.

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

CocoPies used to be its own repository (`MoonCoconutz/CocoPies`, now
archived) and was folded into CocoTools via `git subtree`, with its full
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
`bl_ext.cocotools_dev.CocoPies`):

```python
import addon_utils, sys
addon_utils.disable("<addon_id>", default_set=False)
for n in [m for m in sys.modules if m == "<addon_id>" or m.startswith("<addon_id>.")]:
    del sys.modules[n]
addon_utils.enable("<addon_id>", default_set=False, persistent=True)
```

`default_set=False` leaves `preferences.addons` untouched, so the stored data
survives. Verified field-by-field across a reload under the old bare
`"CocoPies"` module name; re-confirm this again the first time it's
exercised under the current `bl_ext.*` name in this repo, don't assume it
carries over untested. Don't use `bpy.ops.script.reload()` either: it
reloads every other addon in the user's stack for nothing.

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

## Blender UI layout gotchas (learned the expensive way)

- An icon-only button **collapses to its content** instead of filling its
  share of a row. Pin the width explicitly on any row of icon-only buttons.
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
