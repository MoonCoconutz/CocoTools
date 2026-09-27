# CLAUDE.md — CocoSelections

Extension-specific notes. Shared conventions (target versions, headless
verification, the Local Repository dev install, releases) live in the repo
root `CLAUDE.md`.

**Blender 5.2+ only** (`blender_version_min = "5.2.0"`), the user's decision
of 2026-09-28, same as CocoBackup. Use 5.2 APIs directly; do not test on 4.5.

## What it is

Named object selection sets on the Scene, listed in a **Selections** popover in the 3D Viewport tool
header, right of Options. Sets store **object pointers, not names**, so renaming an object
does not break a set and a deleted object drops out on next use.

## Layout

- `properties.py` — `COCOSEL_Selection` / `COCOSEL_ObjectRef`, the scene
  properties, and the two callbacks that do real work: `_use_updated` (viewport
  sync when a checkbox is toggled or dragged over) and `_ui_index_set` (a click
  on a row's name field).
- `operators.py` — add / remove / move / select / update / check_all,
  `selected_rows()`, `select_only()`, `apply_object_selection()`, and the
  `depsgraph_update_post` handler.
- `ui.py` — the popover panel, its tool-header button, and the list rows.

## The row is three different widgets, deliberately

Each cell is the only thing Blender will do that job with. Changing any one of
them back to something else silently breaks a feature:

- **checkbox** — a real `BoolProperty`. This is the *only* reason dragging down
  the column toggles a run of rows: Blender drags across boolean checkboxes
  natively, and gives operator buttons no such behaviour. No operator runs
  during a drag, so `_use_updated` is what keeps the viewport in step.
- **name** — a real text field (`layout.prop(item, "name", text="",
  emboss=False)`, the idiom every native Blender list uses). It is the only
  widget Blender starts editing on a double-click. There is no operator to
  trigger that by hand — `ui.view_item_rename` serves the newer grid/tree
  views, not `UIList`.
- **count** — a plain label.

Consequence: **nothing in the row can read modifier keys.** Neither a checkbox
nor a text field reports Ctrl/Shift to Python, and a click on a text field
inside a `UIList` is routed to the list, arriving in the setter of
`coco_selections_ui_index` with no event. That is why there are no modifier
gestures — checkbox click, drag, and name click cover what Ctrl-click,
Shift-range and a plain click used to.

## UIList constraints worth not rediscovering

- A `UIList` **cannot paint a row background**, and highlights only its one
  active row. Any multi-row selection cue has to be drawn by the row itself.
- `template_list` exposes **no click event for the padding below its rows** —
  it is drawn in C. "Click the empty area to deselect" is not implementable
  there; the viewport handler is the substitute.
- The list is handed `coco_selections_ui_index`, whose **getter is always -1**,
  so Blender never highlights anything. Feeding it a real index paints the
  focused row in the theme's selection colour — indistinguishable from a
  selected row, which made Invert look like it did nothing.
- `activate_init` only works **inside a popup**, and only ever parks the cursor
  at the end of a field — it cannot select the contents, and does nothing at
  all in a panel layout.
- A UI button fires on **mouse release**, so both clicks of a double-click
  arrive as identical `RELEASE` events. `event.value` is never `'DOUBLE_CLICK'`
  for a button.
- `NONE_OR_STATUS` emboss does *not* treat `depress` as a "colouring status" —
  it paints nothing at all.

## Bulk writes must suspend the viewport sync

`_use_updated` fires per `use` flag. Any operator setting several at once wraps
them in `suspend_use_sync(True/False)` and syncs once at the end — otherwise a
bulk change is quadratic and fires part-way through an unfinished selection.
Write a flag only when it changes: every RNA write of a custom property tags
the scene for a depsgraph update, changed or not.

## `apply_object_selection()` is the one viewport sync

It deselects only what is selected (`view_layer.objects.selected`), not every
object in the view layer, then calls `select_set(True)` per object. That call
raises for an object outside the view layer (excluded collection) but silently
does nothing for a hidden or unselectable one, so success is read back with
`select_get()`; the last object that really got selected becomes active.
`view_layer.objects.selected` yields `None` for an object deleted a moment ago,
until the view layer syncs again, hence the `None` guard. No redraw tagging:
`select_set` sends the selection notifier itself.

## The depsgraph handler cannot use an "in progress" flag

`_viewport_cleared` unticks rows when the viewport selection is emptied.
Handlers run **after** the operator has finished, so a flag set during
`apply_object_selection` is always reset by the time the handler runs. It
instead leans on a fact: a set holding objects can only reach an empty viewport
because something else cleared it, so when the selected rows hold nothing the
empty viewport is this add-on's own doing and the rows are left alone.

It must be `@bpy.app.handlers.persistent`. Up to 1.3.0 it was not, so Blender
dropped it at the first File > Open or File > New and the rows stopped
following the viewport: the "passes headless, fails live" report. Confirmed on
5.2 by running the same event-simulated scenario on 1.3.0 and on 1.4.0.

It runs on every depsgraph update (each step of a drag, each frame of
playback). The order of its tests is the cost: no ticked row on the handler's
scene returns at once; then the scene must be the one on screen, Object Mode,
and `view_layer.objects.selected` empty (its truth test stops at the first
selected object, unlike `context.selected_objects`, which builds the full
list). Measured with 3000 of 5000 objects selected and a row ticked: 85 µs per
call in 1.3.0, 5 µs now.

## Verifying

Two scripts, both run in an isolated 5.2 profile (see the root `CLAUDE.md`)
with CocoSelections enabled from this working tree:

- **Headless**: selection rules, add/remove/move/update/check_all, both
  callbacks (name clicks through `coco_selections_ui_index`, checkbox toggles
  through `use`), the handler, hidden / excluded / deleted objects, another
  scene, disable and enable, save and reopen, and the handler still present
  after `open_mainfile` and `read_homefile`.
- **Real window** (`--enable-event-simulate`): open the popover from its header
  button, click a name, click a checkbox, drag down the checkboxes both ways,
  rename, close the popover, click empty viewport, click an object, Ctrl+Z,
  then File > Open and the empty click again. Also run once with the user's own
  preferences (the installed copy disabled in memory, the working tree loaded
  under another module name, `use_preferences_save = False` first): passes
  with their add-ons and MyPreset.

What the window test taught:

- Simulated events accept only PRESS / RELEASE / NOTHING, so a double-click
  cannot be sent. Ctrl-click on the name opens the same text field.
- Once something inside the popover was clicked it stays open until a click
  outside it, and that click is swallowed. The first viewport click after
  using the popover only closes it; that is Blender, not the add-on.
- The handler can run one event loop later than the click that emptied the
  viewport. A check on a fixed delay can see "viewport empty, row ticked";
  send another event (a mouse move) before checking.
