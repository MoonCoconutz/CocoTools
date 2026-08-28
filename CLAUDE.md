# CLAUDE.md — CocoSelections

Extension-specific notes. Shared conventions (target versions, headless
verification, the Local Repository dev install, releases) live in the repo
root `CLAUDE.md`.

## What it is

Named object selection sets on the Scene, listed in `3D Viewport > N > Coco >
Selections`. Sets store **object pointers, not names**, so renaming an object
does not break a set and a deleted object drops out on next use.

## Layout

- `properties.py` — `COCOSEL_Selection` / `COCOSEL_ObjectRef`, the scene
  properties, and the two callbacks that do real work: `_use_updated` (viewport
  sync when a checkbox is toggled or dragged over) and `_ui_index_set` (a click
  on a row's name field).
- `operators.py` — add / remove / move / select / update / check_all,
  `select_only()`, `apply_object_selection()`, and the
  `depsgraph_update_post` handler.
- `ui.py` — the N-panel and the list rows.

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

## The depsgraph handler cannot use an "in progress" flag

`_viewport_cleared` unticks rows when the viewport selection is emptied.
Handlers run **after** the operator has finished, so a flag set during
`apply_object_selection` is always reset by the time the handler runs. It
instead leans on a fact: a set holding objects can only reach an empty viewport
because something else cleared it, so when the selected rows hold nothing the
empty viewport is this add-on's own doing and the rows are left alone.

**Status: this handler passes headless tests but is reported as not working in
a live session, and is unresolved.** Prime suspect: a real viewport click may
tag only a redraw rather than a depsgraph update, so the handler never runs —
the headless test forces it with an explicit `view_layer.update()`, which
proves less than it appears to. If confirmed, use a different signal
(`msgbus`, or a check on panel redraw).

## Verifying

Selection rules, the add/remove/move commands and both callbacks are covered by
a headless script driving the real paths — name clicks through
`coco_selections_ui_index`, checkbox toggles through `use` (a drag is just a run
of those). Run it on **both** 4.5 and 5.2.

What headless testing cannot reach, and has produced wrong conclusions before:
anything needing real mouse or keyboard input — the drag itself, the
double-click rename gesture, and whether a widget is actually clickable. Verify
those in a live session.
