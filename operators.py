"""Operators driving the selection set list.

There is exactly one selection: the `use` flag on each row. `coco_selections_index`
is only the focus (the row a click last landed on) and `coco_selections_anchor` is
only where a Shift range starts from. Every row command reads the selection, so
the list can never show one thing and act on another.
"""

import time

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator


def _resolve(context, index):
    """Return the set at `index`, or the focused one when index < 0."""
    sets = context.scene.coco_selections
    if index < 0:
        index = context.scene.coco_selections_index
    if 0 <= index < len(sets):
        return sets[index]
    return None


def _selected_rows(context):
    """Rows in the current selection, in list order."""
    return [s for s in context.scene.coco_selections if s.use]


def _selected_indices(scene):
    """Indices of the rows in the current selection, ascending."""
    return [i for i, sel_set in enumerate(scene.coco_selections) if sel_set.use]


def _acting_indices(scene):
    """What a row command acts on.

    Explorer applies Delete to everything selected, so the selection wins. The
    focused row is a fallback for when nothing is selected at all.
    """
    indices = _selected_indices(scene)
    if indices:
        return indices

    index = scene.coco_selections_index
    if 0 <= index < len(scene.coco_selections):
        return [index]
    return []


def _unique_name(sets, base="Selection"):
    used = {s.name for s in sets}
    i = 1
    while "%s %d" % (base, i) in used:
        i += 1
    return "%s %d" % (base, i)


def _redraw_viewports(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def apply_object_selection(context, targets, extend=False):
    """Select the union of `targets` in the viewport, list order preserved.

    An empty `targets` with extend off clears the selection - which is what a
    Ctrl-click that unselects the last row should do.

    Returns (found, unreachable).
    """
    objects = []
    seen = set()
    for sel_set in targets:
        sel_set.purge()
        for obj in sel_set.valid_objects():
            key = obj.as_pointer()
            if key not in seen:
                seen.add(key)
                objects.append(obj)

    view_objects = context.view_layer.objects

    if not extend:
        for obj in view_objects:
            # A stale view layer can hand back empty bases.
            if obj is None:
                continue
            try:
                obj.select_set(False)
            except RuntimeError:
                pass

    found = 0
    unreachable = 0
    last = None
    for obj in objects:
        if obj.name not in view_objects:
            # Excluded collection, other scene, or linked out of this view layer.
            unreachable += 1
            continue
        try:
            obj.select_set(True)
        except RuntimeError:
            unreachable += 1
            continue
        found += 1
        last = obj

    if last is not None:
        view_objects.active = last

    _redraw_viewports(context)
    return found, unreachable


def _clamp_focus(scene):
    count = len(scene.coco_selections)
    high = count - 1 if count else 0
    scene.coco_selections_index = max(0, min(scene.coco_selections_index, high))
    scene.coco_selections_anchor = max(0, min(scene.coco_selections_anchor, high))


def _focus_only(scene, index):
    """Collapse the selection onto one row, with focus and anchor on it."""
    for sel_set in scene.coco_selections:
        sel_set.use = False
    if 0 <= index < len(scene.coco_selections):
        scene.coco_selections[index].use = True
        scene.coco_selections_index = index
        scene.coco_selections_anchor = index


def set_row_selection(scene, index, toggle=False, extend_range=False):
    """Explorer row rules, in one place.

    Plain       - the clicked row becomes the whole selection.
    Ctrl        - the clicked row flips, everything else stays put.
    Shift       - anchor..clicked replaces the selection.
    Ctrl+Shift  - anchor..clicked is added to the selection.

    Focus always lands on the clicked row. The anchor only moves on a plain or
    Ctrl click, so a second Shift-click resizes the range instead of starting a
    new one - the detail that makes Explorer ranges feel right. A Shift-click
    with the anchor out of range degrades to a plain click.
    """
    sets = scene.coco_selections
    if not (0 <= index < len(sets)):
        return False

    anchor = scene.coco_selections_anchor

    if extend_range and 0 <= anchor < len(sets):
        low, high = (anchor, index) if anchor <= index else (index, anchor)
        if not toggle:
            # Plain Shift replaces the selection, Ctrl+Shift adds to it.
            for sel_set in sets:
                sel_set.use = False
        for i in range(low, high + 1):
            sets[i].use = True
        # The anchor deliberately stays put.
    elif toggle:
        sets[index].use = not sets[index].use
        scene.coco_selections_anchor = index
    else:
        for sel_set in sets:
            sel_set.use = False
        sets[index].use = True
        scene.coco_selections_anchor = index

    scene.coco_selections_index = index
    return True


# Last row click, for double-click detection. A UI button fires on mouse
# RELEASE, and both clicks of a double-click arrive as identical RELEASE events,
# so `event.value` is never 'DOUBLE_CLICK' here - the gap has to be timed.
_last_click = {"index": -1, "time": 0.0}


def double_click_check(index, now, threshold, state=None):
    """True when this click closes a double-click on the same row.

    Pure so it can be tested without a window: `now` and `threshold` are passed
    in, and `state` defaults to the module-level record.

    Recording the click always happens, and a hit clears the record so a third
    rapid click starts over instead of renaming again.
    """
    if state is None:
        state = _last_click

    hit = index == state["index"] and 0.0 <= (now - state["time"]) <= threshold

    if hit:
        state["index"] = -1
        state["time"] = 0.0
    else:
        state["index"] = index
        state["time"] = now

    return hit


def _reorder_map(count, indices, direction):
    """Where every row lands after moving `indices` one slot.

    Mirrors the collection.move() calls exactly, so focus and anchor can be
    carried across the move by identity rather than by guesswork.

    Returns (moves, new_position_of_old_index), or (None, None) when the move is
    blocked by the top or the bottom of the list.
    """
    if not indices:
        return None, None

    if direction == 'UP':
        if indices[0] == 0:
            return None, None
        moves = [(i, i - 1) for i in indices]
    else:
        if indices[-1] == count - 1:
            return None, None
        moves = [(i, i + 1) for i in reversed(indices)]

    order = list(range(count))
    for src, dst in moves:
        order.insert(dst, order.pop(src))

    return moves, {old: new for new, old in enumerate(order)}


class COCOSEL_OT_add(Operator):
    """Store the current selection as a new set"""

    bl_idname = "cocosel.add"
    bl_label = "Add Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        name = _unique_name(scene.coco_selections)
        item = scene.coco_selections.add()
        item.name = name
        item.store(context.selected_objects)

        # The new row becomes the selection, the way a new folder does in a file
        # browser - and it honestly reflects what is selected right now.
        _focus_only(scene, len(scene.coco_selections) - 1)

        self.report({'INFO'}, "'%s' stores %d object(s)" % (name, len(item.objects)))
        return {'FINISHED'}


class COCOSEL_OT_remove(Operator):
    """Remove every selected set"""

    bl_idname = "cocosel.remove"
    bl_label = "Remove Selection Sets"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.coco_selections) > 0

    def execute(self, context):
        scene = context.scene
        indices = _acting_indices(scene)
        if not indices:
            return {'CANCELLED'}

        for i in reversed(indices):
            scene.coco_selections.remove(i)

        count = len(scene.coco_selections)
        if count:
            # Explorer lands on whatever slid into the gap.
            _focus_only(scene, min(indices[0], count - 1))
        else:
            scene.coco_selections_index = 0
            scene.coco_selections_anchor = 0

        if context.mode == 'OBJECT':
            apply_object_selection(context, _selected_rows(context))

        self.report({'INFO'}, "Removed %d set(s)" % len(indices))
        return {'FINISHED'}


class COCOSEL_OT_move(Operator):
    """Move every selected set up or down in the list"""

    bl_idname = "cocosel.move"
    bl_label = "Move Selection Sets"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction",
        items=(
            ('UP', "Up", "Move the sets one slot up"),
            ('DOWN', "Down", "Move the sets one slot down"),
        ),
        default='UP',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.coco_selections) > 1

    def execute(self, context):
        scene = context.scene
        sets = scene.coco_selections
        indices = _acting_indices(scene)

        moves, new_pos = _reorder_map(len(sets), indices, self.direction)
        if moves is None:
            # Already against the top or the bottom.
            return {'CANCELLED'}

        for src, dst in moves:
            sets.move(src, dst)

        # Carry focus and anchor with the rows they were pointing at.
        scene.coco_selections_index = new_pos.get(
            scene.coco_selections_index, scene.coco_selections_index
        )
        scene.coco_selections_anchor = new_pos.get(
            scene.coco_selections_anchor, scene.coco_selections_anchor
        )
        _clamp_focus(scene)
        return {'FINISHED'}


class COCOSEL_OT_row_click(Operator):
    """Select this set. Ctrl-click to add or remove, Shift-click for a range"""

    bl_idname = "cocosel.row_click"
    bl_label = "Select Set"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    use_toggle: BoolProperty(default=False, options={'SKIP_SAVE'})
    use_range: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            cls.poll_message_set("Only available in Object Mode")
            return False
        return True

    def invoke(self, context, event):
        # The first click of a double-click has already selected the row, so the
        # second one renames instead of re-selecting - the file browser habit.
        # Modified clicks are excluded: Ctrl-clicking a row twice to add then
        # remove it is a normal thing to do, and must not open a rename.
        if not event.ctrl and not event.shift:
            threshold = context.preferences.inputs.mouse_double_click_time / 1000.0
            if double_click_check(self.index, time.monotonic(), threshold):
                return bpy.ops.cocosel.rename('INVOKE_DEFAULT', index=self.index)

        self.use_toggle = event.ctrl
        self.use_range = event.shift
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        if not set_row_selection(scene, self.index, self.use_toggle, self.use_range):
            return {'CANCELLED'}

        rows = _selected_rows(context)
        found, unreachable = apply_object_selection(context, rows)

        if rows and found == 0:
            label = rows[0].name if len(rows) == 1 else "%d sets" % len(rows)
            self.report({'WARNING'}, "'%s' has no selectable objects" % label)
        elif unreachable:
            self.report(
                {'WARNING'},
                "Selected %d object(s), %d not reachable in this view layer"
                % (found, unreachable),
            )
        return {'FINISHED'}


class COCOSEL_OT_rename(Operator):
    """Rename this set"""

    bl_idname = "cocosel.rename"
    bl_label = "Rename Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    # Used by the scripted path only; the popup types into the scene's
    # coco_rename_buffer, which applies the name itself.
    new_name: StringProperty(name="Name", default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return len(context.scene.coco_selections) > 0

    def invoke(self, context, event):
        scene = context.scene
        if 0 <= self.index < len(scene.coco_selections):
            # The popup renames whatever row has focus, so point focus at the
            # row that was actually clicked.
            scene.coco_selections_index = self.index
        elif not (0 <= scene.coco_selections_index < len(scene.coco_selections)):
            return {'CANCELLED'}

        scene.coco_rename_buffer = ""
        return bpy.ops.wm.call_panel(name="COCOSEL_PT_rename", keep_open=False)

    def execute(self, context):
        sel_set = _resolve(context, self.index)
        if sel_set is None:
            return {'CANCELLED'}

        name = self.new_name.strip()
        if not name:
            return {'CANCELLED'}

        sel_set.name = name
        return {'FINISHED'}


class COCOSEL_OT_select(Operator):
    """Select the objects in every selected row. Shift-click to add to the current selection"""

    bl_idname = "cocosel.select"
    bl_label = "Select Stored Objects"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    extend: BoolProperty(name="Extend", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            cls.poll_message_set("Only available in Object Mode")
            return False
        return len(context.scene.coco_selections) > 0

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        targets = self.targets(context)
        if not targets:
            return {'CANCELLED'}

        found, unreachable = apply_object_selection(context, targets, self.extend)

        label = targets[0].name if len(targets) == 1 else "%d sets" % len(targets)
        if found == 0:
            self.report({'WARNING'}, "'%s' has no selectable objects" % label)
        elif unreachable:
            self.report(
                {'WARNING'},
                "Selected %d object(s) from %s, %d not reachable in this view layer"
                % (found, label, unreachable),
            )
        elif len(targets) > 1:
            self.report({'INFO'}, "Selected %d object(s) from %s" % (found, label))
        return {'FINISHED'}

    def targets(self, context):
        """An explicit index acts on that row alone, otherwise every selected
        row, falling back to the focused one when nothing is selected."""
        if self.index >= 0:
            sets = context.scene.coco_selections
            return [sets[self.index]] if 0 <= self.index < len(sets) else []

        rows = _selected_rows(context)
        if rows:
            return rows

        active = _resolve(context, -1)
        return [active] if active is not None else []


class COCOSEL_OT_update(Operator):
    """Replace the contents of the selected set with the current selection"""

    bl_idname = "cocosel.update"
    bl_label = "Update From Selection"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if len(context.scene.coco_selections) == 0:
            return False
        if len(_acting_indices(context.scene)) > 1:
            cls.poll_message_set("Select a single set to update")
            return False
        return True

    def execute(self, context):
        scene = context.scene
        if self.index >= 0:
            sel_set = _resolve(context, self.index)
        else:
            indices = _acting_indices(scene)
            sel_set = scene.coco_selections[indices[0]] if len(indices) == 1 else None

        if sel_set is None:
            return {'CANCELLED'}

        sel_set.store(context.selected_objects)
        self.report(
            {'INFO'},
            "'%s' now stores %d object(s)" % (sel_set.name, len(sel_set.objects)),
        )
        return {'FINISHED'}


class COCOSEL_OT_check_all(Operator):
    """Select or unselect every row at once"""

    bl_idname = "cocosel.check_all"
    bl_label = "Select All Rows"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(
        name="Action",
        items=(
            ('ALL', "All", "Select every row"),
            ('NONE', "None", "Unselect every row"),
            ('INVERT', "Invert", "Invert the row selection"),
        ),
        default='ALL',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.coco_selections) > 0

    def execute(self, context):
        scene = context.scene
        for sel_set in scene.coco_selections:
            if self.action == 'ALL':
                sel_set.use = True
            elif self.action == 'NONE':
                sel_set.use = False
            else:
                sel_set.use = not sel_set.use

        _clamp_focus(scene)

        # Keep the viewport in step with the rows, the way a row click does.
        if context.mode == 'OBJECT':
            apply_object_selection(context, _selected_rows(context))
        return {'FINISHED'}


classes = (
    COCOSEL_OT_add,
    COCOSEL_OT_remove,
    COCOSEL_OT_move,
    COCOSEL_OT_row_click,
    COCOSEL_OT_rename,
    COCOSEL_OT_select,
    COCOSEL_OT_update,
    COCOSEL_OT_check_all,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
