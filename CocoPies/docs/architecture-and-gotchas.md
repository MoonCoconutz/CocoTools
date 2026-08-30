# Architecture, and the traps around it

`CLAUDE.md` carries the full account of both. This is the short map plus the
things most likely to bite an agent who has not read it end to end. Where the
two disagree, `CLAUDE.md` is right.

## Entry points worth not re-grepping for

| File | What lives there |
|---|---|
| `menus.py` | `create_pie_menu_class(pie_data)` (note: *create_*, not build_), `execute_script()`, `_parse_bpy_ops_call()` |
| `keymaps.py` | `register_pie_menus()` / `unregister_pie_menus()` |
| `defaults.py` | `default_pie_definitions(script_paths)`, `bundled_script_paths()`, `sync_starter_pies()`, `ensure_default_pies()` |
| `presets.py` | `_apply_pie_dict(pie, definition)` — the shared "dict → stored pie" writer used by starters, presets and imports alike |
| `utils.py` | `get_prefs()`, `pie_scope_types()`, `keymap_names_for_pie()`, `pie_menu_groups()`, `ensure_slot_items()`, `slot_is_used()`, `normalized_scope()` |
| `previews.py` | all three kinds of loaded icon; `icon_args()` is what every caller uses |
| `ui/lists.py` | `draw_pie_row()` — the Pie Menus list rows |
| `preferences.py` | the whole editor: `draw_left_column`, `draw_pie_settings`, `draw_pie_items`, `draw_single_item` |

## The invariants

**A pie always has exactly eight items**, one per compass direction, indexed by
`position` 0–7 in Blender's own slot order. `ensure_slot_items()` guarantees
that 1:1 mapping and is idempotent — call it defensively before indexing by
position. Nothing ever adds or removes item rows, only fills or clears them;
`slot_is_used()` (a label or a command present) is what distinguishes a
configured direction from an empty one.

**Registration is a full rebuild.** Any settings change calls
`update_pie_menu()` → `register_pie_menus()`, which unregisters everything and
rebuilds every `Menu` class and keymap item from scratch. Simple, but it makes
`unregister_pie_menus()` load-bearing.

**Keymap items must be swept by content, not trusted from a Python list.**
`registered_keymaps` only reflects items made by *this* module instance, and is
empty again after any disable/enable cycle — while real items from a previous
load are still sitting in the keyconfig. `keymap_items.new()` always appends,
so orphans compound silently. The sweep walks every keymap CocoPies could have
touched for any `wm.call_menu_pie` whose `properties.name` starts with
`COCOPIE_MT_`, or any `cocopie.hold_or_tap`. **Any new CocoPies-owned keymap
idname must be added to that sweep** or it will orphan the same way.

**`KEYMAP_TYPE_ITEMS` numbers are frozen on-disk data.** Blender saves an
`EnumProperty` as its integer, so those numbers are the stored format of every
scope the user has ever set. Inserting an item mid-list renumbers everything
after it and repoints stored pies at the wrong editor — which is exactly what
happened once: `3D_VIEW` moved 13 → 14, a stored pie holding 13 landed on a
heading, resolved to `""`, registered no keymap, and vanished from the list.
Every item now carries an explicit number; a new scope takes the next unused
one and may sit anywhere for display. Never renumber, never reuse a retired
number. The same applies to any other stored enum — a pie's `event_value`, an
item's icon choice. `normalized_scope()` is the seatbelt: anything not a
`KEYMAP_CONFIG` key resolves to `'WINDOW'`.

**The addon's identity is its folder name.** `ADDON_ID = __package__`, because
Blender keys `AddonPreferences` by module name — renaming the `CocoPies/`
folder orphans every saved pie (it has happened twice). Derive identity from
`__package__`, never `__name__` (that is the *submodule's* dotted path and
matches nothing).

**Starter seeding is by record, not by absence.** Startup calls
`sync_starter_pies()`, which adds only starters whose name is not already in
`prefs.seeded_starters`. That is what lets a new version's starter appear on
its own while a starter the user deleted stays deleted.
`ensure_default_pies()` is the deliberate restore behind the button, and adds
anything missing regardless of the record. Do not "simplify" startup back to
it; that resurrects deleted starters forever. `register()` also guards seeding
behind a module-level session flag — keep it, or a user who unticks and
returns loses their pies to starters.

**Commands are `exec()`'d Python**, not a restricted DSL. A pie item is exactly
as trusted as any script the user would run. Prefer a real `bpy.ops` command
over a bundled script whenever one exists; scripts are a last resort.

**The Pie Menus list is grouped by editor, display-only.** The stored
collection is **never** reordered to match the display (doing it with `.move()`
corrupted stored pies), and a section heading is **never** drawn inside a
`UIList.draw_item` (it becomes part of the first pie's row and steals its click
and highlight). Storage order and display order are independent by design,
which is also why the ▲/▼ buttons look odd near a section boundary.

## Blender UI layout gotchas

The expensive ones. `CLAUDE.md` has the full list.

**Icons, and how big they are drawn.** An icon is only drawn at icon size if it
is an icon. Measured in a real window at UI scale 1.0:

| Kind | Drawn size | Position |
|---|---|---|
| built-in (font glyph) | ~18px | centred in the button |
| `bpy.utils.previews` image | ~18px | centred in the button |
| `bpy.app.icons` triangle geometry | **31px** | overflows the 23px button |

The button does not grow to fit its icon. Since the button *is* the click
target and the selection highlight, an overflowing icon means only a corner is
clickable, the highlight hides behind the artwork, and grid neighbours touch
whatever spacing the layout asks for. The sculpt brush icons were geometry for
exactly this reason and are now PNGs (`icons/brushes/`, see its README for the
`.dat` format and how to re-render). **Keep every icon on the
preview-collection path.**

**Sizing.** An icon-only button collapses to its content, and `ui_units_x` does
**not** change that — it sizes the *cell*, and the button sits at its natural
one unit inside however wide a cell it is given. `scale_x` is the only thing
that resizes the button. The button is exactly one widget_unit square before
scaling and `scale_x`/`scale_y` multiply that same unit, so equal numbers give
a square button. Set both: `ui_units_x` on the cell so table headers line up
with rows, `scale_x` on the button so it fills the cell.

**Other dead ends, each learned by hitting it:**

- `alignment = 'CENTER'` on a container makes the container shrink to its
  content. Centring something inside a fixed-width cell needs an inner row.
- `separator(type='LINE')` only renders as a divider stacked in a **column**;
  in a row it is a stray dash. A row separator adds height and no width — which
  alone makes a square popup and a row separator mutually exclusive.
- A label insets its icon differently from a button. To align with neighbouring
  buttons, use a disabled button, not a label.
- There is no diagonal arrow anywhere in Blender's ~1000 built-ins. The eight
  slot arrows are custom PNGs for that reason; rotating a built-in gives a
  blurred diagonal against sharp cardinals.
- `UIList`/`template_list` has no drag/drop/reorder hook from Python at all,
  and a `UIList` cannot carry section headings inside itself. Stashing state on
  `self` in `filter_items` for `draw_item` to read back does not work either —
  Blender does not guarantee the same Python instance serves both in one
  redraw.
- `emboss='NONE_OR_STATUS'` exists on 4.5 and 5.2 but is for animation-state
  colouring on property fields. It does **not** mark a `depress`ed operator
  button — tried, and the selected cell came back unmarked. (Also: `RADIAL_MENU`
  was renamed `PIE_MENU` in 5.2, so do not hard-code that identifier.)
