# CocoSelections

Blender add-on for storing named object selections and restoring them later,
with Windows-Explorer-style multi-row selection.

Tested on Blender **4.5 LTS** and **5.2 LTS**.

## Install

Blender needs the add-on as a folder inside its `addons` directory, or as a zip.

**Option A — junction / symlink (best for development, changes are live):**

```
mklink /J "%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\CocoSelections" "%USERPROFILE%\Documents\Claude\CocoSelections"
```

`mklink /J` makes a directory junction and does **not** require admin rights.
Adjust `5.2` to your Blender version.

**Option B — zip:** zip this folder so the archive contains a single
`CocoSelections/` folder with `__init__.py` inside, then
`Edit > Preferences > Add-ons > Install...` and pick the zip.

Then enable **Object: CocoSelections** in the add-ons list.

## Use

`3D Viewport > N > Coco > Selections`

| Control | Action |
| --- | --- |
| `+` | Store the current selection as a new set (the new row becomes the selection) |
| `-` | Delete every selected set |
| `▲` / `▼` | Reorder every selected set |
| **Click a row** | Select that set alone — replaces the selection |
| **Ctrl-click a row** | Add or remove that single row |
| **Shift-click a row** | Select the whole range from the anchor to that row |
| **Ctrl+Shift-click a row** | Add a whole range without clearing |
| Double-click a row | Rename that set (type straight away, Enter applies) |
| Pencil beside the list | Rename the focused set |
| **All** / **None** / **Invert** | Bulk row selection |
| **Update** | Overwrite the selected set with the current selection |

There is no Select button: selecting a row already selects its objects, so it
had nothing left to do. The `cocosel.select` operator is still registered and
can be bound to a key if you want the shift-to-extend behaviour.

The number in the left-hand column of each row is how many objects the set
still holds.

### Row selection behaves like a file browser

Selecting rows immediately selects their objects in the viewport, and multiple
selected rows give the **union** of their objects with overlaps counted once.
Ctrl-clicking away the last selected row clears the viewport selection.

The **anchor** is the row a plain or Ctrl click last landed on. Shift-click
deliberately leaves the anchor where it is, so you can shift-click again
somewhere else to resize the range rather than starting over — same as
Explorer. If the anchor is out of range, a shift-click degrades to a plain
click.

### Renaming

Double-clicking a row opens a small popup at the cursor: the current name greyed
out above, an empty field below with the cursor already in it. Type and press
Enter once - the name applies and the popup closes. The pencil beside the list
does the same for the focused row.

It is a **panel** opened with `wm.call_panel(keep_open=False)`, the same
mechanism as Blender's own F2 rename, not an operator popup. That is what makes
one Enter enough: an operator popup needs two, one to confirm the field and one
to dismiss the popup.

The field writes to `Scene.coco_rename_buffer`, whose update callback renames
the focused set and then clears itself. The buffer lives on the Scene for two
reasons that each broke an earlier attempt:

- `invoke_popup` never calls `execute()`, so the operator had nothing to apply
  the name from.
- A property update callback on an *operator* cannot see attributes set in its
  `invoke()` - Blender does not carry the Python instance across - so a guard
  stored there is always missing, and the rename silently did nothing.

A scene property has neither problem, and a test can drive it directly, which is
how the interactive path is covered rather than assumed.

Two more Blender limits shaped this:

- **A UI button fires on mouse release**, and both clicks of a double-click
  arrive as identical `RELEASE` events, so `event.value` is never
  `'DOUBLE_CLICK'` for a button. The gap between clicks is timed instead,
  against the user's own `mouse_double_click_time`. Ctrl- and Shift-clicks are
  excluded, since clicking a row twice with Ctrl to add then remove it is
  normal and must not open a rename.
- **`activate_init` only works inside a popup**, and only ever parks the cursor
  at the end of the field - there is no way to select its contents, and no way
  to focus a field drawn in place on a row. Opening the field *empty* gets the
  same result as a select-all: typing replaces the name outright, and leaving it
  empty keeps the old one.

### One selection, not two

Earlier versions had two competing notions of "selected": the `use` dots and
Blender's own active-row highlight. They could disagree, and they drove
different buttons — `-` and the arrows acted on the highlight while **Select**
acted on the dots. Now the `use` flags are the only selection. The list index is
demoted to **focus** (the row a click last landed on) and every row command —
delete, reorder, update — reads the selection, falling back to the focused row
only when nothing at all is selected.

### Why the whole row is a button

Blender's `UIList` gives Python no way to see modifier keys on a row click:
there is no click callback, and the active-index update fires without an event.
Modifier state only reaches an operator's `invoke`. So each row is drawn as a
single operator button spanning its full width — that is what makes clicking
anywhere on the row work, and Ctrl and Shift readable at all.

That costs two things. The name can no longer be an editable field, so renaming
moved to the pencil button beside the list, which acts on the focused row. And
because Blender centres the text in a wide button and offers no left-align for
one, the name is centred and the object count rides in the same label - the
count used to be a second button, but two buttons draw a hairline between them
and broke the selection bar in half.

### How a selected row looks

A `UIList` cannot paint its own row background and highlights only the one
active row, so multi-row selection has to be drawn by the row itself. Each row
is a single operator button given `depress=True` when selected, which paints it
in the theme's selection colour across the full width - so any number of rows
can read as selected at once. Unselected rows are drawn with `emboss=False` so
they stay flat text.

A row is three buttons: the object count in a fixed-width column, the name
hugging the left of what remains, and an empty filler taking the slack so the
whole row stays one click target and the bar runs full width.

The count leads because Blender draws a divider between aligned buttons and
offers no way to suppress it. A single button has no divider but centres its
text, and there is no left-align for the text of a wide button; `NONE_OR_STATUS`
emboss looks like the answer and is not, since `depress` does not count as a
"colouring status" and it paints no fill at all. So rather than let the divider
fall somewhere arbitrary in the middle of the bar, the layout puts a column
where a divider is wanted anyway. The fixed width keeps that divider in the same
place on every row whatever the count, and fits four digits.

The list is handed `coco_selections_ui_index`, a property that is permanently
`-1`. `template_list` paints its active row in the theme's selection colour -
the very colour a selected row paints itself with - so a focused-but-unselected
row used to look selected, and inverting the selection appeared to do nothing.
With nothing ever active, the `use` flags are the only thing that colours a row.
Focus still exists in `coco_selections_index`; it is simply not drawn.

Earlier versions drew a theme-coloured dot per row from a generated preview
(`icons.py`). That module is gone - the row highlight replaced it. It is still
in git history at commit `60014e7` if it is ever wanted back.

## Notes

- Sets live on the **Scene** and are saved in the `.blend` file. Each scene has
  its own list.
- Objects are stored as real pointers, not names, so **renaming an object does
  not break a set**. Deleted objects drop out of the set on the next use.
- Selecting is Object Mode only; the buttons grey out elsewhere.
- Objects in excluded or unlinked collections cannot be selected — the operator
  reports how many were skipped.

## Layout

- `properties.py` — data model (`COCOSEL_Selection`, `COCOSEL_ObjectRef`) + scene
  props, including the always-`-1` index the list is drawn with
- `operators.py` — add / remove / move / row_click / rename / select / update /
  check_all, plus `set_row_selection()` holding the Explorer rules in one place,
  plus `apply_object_selection()` shared by everything that touches the viewport
- `ui.py` — the N-panel and the list rows; **replace this file alone** when the
  UI moves off the sidebar
- `__init__.py` — `bl_info` and registration

The N-panel is a temporary host. `properties.py` and `operators.py` are kept
host-agnostic — operators take an explicit `index` and never read UI state — so
the UI can be swapped for a popup, pie menu, or dedicated editor without
touching them.
