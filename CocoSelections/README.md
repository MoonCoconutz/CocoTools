# CocoSelections

Blender add-on for storing named object selections and restoring them later,
with Windows-Explorer-style multi-row selection.

Tested on Blender **4.5 LTS** and **5.2 LTS**.

## Install

CocoSelections is a Blender **Extension**, published from the
[CocoTools](https://github.com/MoonCoconutz/CocoTools) repository.

`Edit > Preferences > Get Extensions > repositories ▾ > + > Add Remote
Repository`, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

The URL **must** end in `index.json`. A bare directory URL fails with
`invalid manifest (Expecting value: line 1 column 1 (char 0))`, because GitHub
Pages serves `index.html` there and Blender does not append `index.json` itself.

Then find **CocoSelections** in Get Extensions and install it.

It is no longer a legacy add-on: there is no `bl_info`, and dropping the folder
into `scripts/addons` will not work. If an older copy is still installed that
way - including as a `mklink /J` junction - remove it, or two copies will fight
over the same module name.

## Use

`3D Viewport > N > Coco > Selections`

| Control | Action |
| --- | --- |
| `+` | Store the current selection as a new set (the new row becomes the selection) |
| `-` | Delete every selected set |
| `▲` / `▼` | Reorder every selected set |
| **Click a checkbox** | Toggle that set in or out of the selection |
| **Drag down the checkboxes** | Toggle every row the mouse passes over |
| **Click a name** | Select that set alone — replaces the selection |
| **Double-click a name** | Rename it in place |
| **All** / **Invert** | Bulk row selection |
| Click empty space in the viewport | Deselect everything, rows included |
| **Change** | Replace the selected set with the current object selection |
| **Add** | Add the selected objects to the set |
| **Remove** | Remove the selected objects from the set |

There are no modifier keys to learn. Clicking a checkbox toggles one row,
dragging across them toggles a run, and clicking a name selects that row alone -
which is everything Ctrl-click, Shift-range and a plain click used to do.

There is no Select button either: selecting a row already selects its objects.
The `cocosel.select` operator is still registered and can be bound to a key if
you want its shift-to-extend behaviour.

The number on the right of each row is how many objects the set still holds.

### Row selection drives the viewport, and follows it back

Selecting rows immediately selects their objects in the viewport, and several
selected rows give the **union** of their objects with overlaps counted once.
Unticking the last row clears the viewport selection.

It also works the other way: clicking empty space in the viewport deselects the
objects, and a `depsgraph_update_post` handler unticks the rows to match, so the
panel never claims a set is active after its objects have been clicked away.
There is no **None** button because that handler replaced it.

The equivalent click *inside the list* is not available - `template_list` draws
the padding below its rows in C and exposes no click event to Python at all.

The handler has to avoid undoing the add-on's own work, and cannot do it with an
"in progress" flag: depsgraph handlers run after the operator has finished, so
any such flag would already be reset. Instead it leans on a fact - a set holding
objects can only end up with an empty viewport because something else cleared
it. When the selected rows hold nothing at all, the empty viewport is this
add-on's own doing, and the rows are left alone.

### A row is a checkbox, a name field, and a count

Each cell is a different kind of widget, because each one is the only thing
Blender will do that particular job with.

**The checkbox is a real `BoolProperty`.** That is what makes dragging down the
column toggle a run of rows: Blender toggles boolean checkboxes as the mouse
drags across them, and gives operator buttons no such behaviour. No operator
runs during a drag at all, so the viewport is kept in step by the property's own
`update` callback. Operators that set many flags at once switch that callback
off first (`suspend_use_sync`) and sync once at the end, so a bulk change is not
quadratic and never fires mid-way through an unfinished selection.

**The name is a real text field** - `layout.prop(item, "name", text="",
emboss=False)`, the idiom every native Blender list uses. It is the only widget
Blender will start editing on a double-click, and it opens focused with the text
selected. There is no operator to trigger that by hand (`ui.view_item_rename`
serves the newer grid/tree views, not `UIList`). A click on a text field inside a
`UIList` is routed to the list rather than to an operator, arriving in the setter
of `coco_selections_ui_index` - which treats it as a plain click and selects that
row alone.

**The count is an operator button drawn flat**, so it looks like a label but is
the row's one modifier-aware click surface. Neither a checkbox nor a text field
reports Ctrl or Shift state to Python, so range selection lives here.

Nothing paints a row background: a `UIList` cannot, and it highlights only its
one active row. The list is handed `coco_selections_ui_index`, whose getter is
always `-1`, so Blender never highlights anything and the checkboxes are the
only thing that marks a row.

### One selection, not two

Earlier versions had two competing notions of "selected": the `use` flags and
Blender's own active-row highlight. They could disagree, and they drove
different buttons - `-` and the arrows acted on the highlight while Select acted
on the flags. Now the `use` flags are the only selection. The list index is
demoted to **focus** (the row a click last landed on) and every row command -
delete, reorder, edit - reads the selection, falling back to the focused row
only when nothing is selected.

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
- `operators.py` — add / remove / move / select / update / check_all, plus
  `select_only()`,
  plus `apply_object_selection()` shared by everything that touches the viewport
- `ui.py` — the N-panel and the list rows; **replace this file alone** when the
  UI moves off the sidebar
- `__init__.py` — `bl_info` and registration

The N-panel is a temporary host. `properties.py` and `operators.py` are kept
host-agnostic — operators take an explicit `index` and never read UI state — so
the UI can be swapped for a popup, pie menu, or dedicated editor without
touching them.
