# Coco Selections

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

Then enable **Object: Coco Selections** in the add-ons list.

## Use

`3D Viewport > N > Coco > Selections`

| Control | Action |
| --- | --- |
| `+` | Store the current selection as a new set (the new row becomes selected) |
| `-` | Delete the highlighted set |
| `▲` / `▼` | Reorder the highlighted set |
| **Click a row's dot** | Select that set — replaces the row selection |
| **Shift-click a dot** | Select the whole range from the anchor to that row |
| **Ctrl-click a dot** | Add or remove that single row |
| **Ctrl+Shift-click a dot** | Add a whole range without clearing |
| Double-click a name | Rename in place |
| **All** / **None** / **Invert** | Bulk row selection |
| **Select** | Re-apply the current row selection (shift-click to extend) |
| **Update** | Overwrite the highlighted set with the current selection |

The number on the right of each row is how many objects the set still holds.

### Row selection behaves like a file browser

Selecting rows immediately selects their objects in the viewport, and multiple
selected rows give the **union** of their objects with overlaps counted once.
Ctrl-clicking away the last selected row clears the viewport selection.

The **anchor** is the row a plain or Ctrl click last landed on. Shift-click
deliberately leaves the anchor where it is, so you can shift-click again
somewhere else to resize the range rather than starting over — same as
Explorer. If the anchor is out of range, a shift-click degrades to a plain
click.

### Why the dot, and not the whole row

Blender's `UIList` gives Python no way to see modifier keys on a row click:
there is no click callback, and the active-index update fires without an event.
Modifier state only reaches an operator's `invoke`. So the click/Shift/Ctrl
behaviour lives on the **state dot** at the left of each row, which is an
operator button. That keeps the name field a real text field, so double-click
renaming still works.

### The state dot colour

`UIList` cannot paint a row background either, so "this row is selected" is
shown by the dot. Blender ships no icon in the theme's selection colour, so the
dots are generated at register time from your theme:

- **filled, selected colour** — `Themes > Outliner > Selected Object`
- **filled, active colour** — `Themes > Outliner > Active Object` (the anchor row)
- **hollow grey** — not selected

Change your theme and the dots regenerate automatically (the rebuild is
deferred to a timer, never done mid-draw). In `--background` there is no icon
system, so `icon_id` returns 0 and the UI falls back to built-in icons.

## Notes

- Sets live on the **Scene** and are saved in the `.blend` file. Each scene has
  its own list.
- Objects are stored as real pointers, not names, so **renaming an object does
  not break a set**. Deleted objects drop out of the set on the next use.
- Selecting is Object Mode only; the buttons grey out elsewhere.
- Objects in excluded or unlinked collections cannot be selected — the operator
  reports how many were skipped.

## Layout

- `properties.py` — data model (`COCOSEL_Selection`, `COCOSEL_ObjectRef`) + scene props
- `operators.py` — add / remove / move / row_click / select / update / check_all,
  plus `apply_object_selection()` shared by everything that touches the viewport
- `icons.py` — theme-coloured state dots
- `ui.py` — the N-panel and the list rows; **replace this file alone** when the
  UI moves off the sidebar
- `__init__.py` — `bl_info` and registration

The N-panel is a temporary host. `properties.py` and `operators.py` are kept
host-agnostic — operators take an explicit `index` and never read UI state — so
the UI can be swapped for a popup, pie menu, or dedicated editor without
touching them.
