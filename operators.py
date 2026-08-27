"""Operators driving the selection set list.

There is exactly one selection: the `use` flag on each row. `coco_selections_index`
is only the focus (the row a click last landed on). Every row command reads the
selection, so the list can never show one thing and act on another.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

from .properties import suspend_use_sync


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


def _focus_only(scene, index):
    """Collapse the selection onto one row, with focus on it."""
    suspend_use_sync(True)
    try:
        for sel_set in scene.coco_selections:
            sel_set.use = False
    finally:
        suspend_use_sync(False)
    if 0 <= index < len(scene.coco_selections):
        scene.coco_selections[index].use = True
        scene.coco_selections_index = index


def select_only(scene, index):
    """Make `index` the whole selection, and the focused row.

    The only selection rule left that needs code: a checkbox toggles its own row
    and a drag toggles a run, both handled by Blender itself.
    """
    sets = scene.coco_selections
    if not (0 <= index < len(sets)):
        return False

    suspend_use_sync(True)
    try:
        for sel_set in sets:
            sel_set.use = False
        sets[index].use = True
    finally:
        suspend_use_sync(False)

    scene.coco_selections_index = index
    return True


def _reorder_map(count, indices, direction):
    """Where every row lands after moving `indices` one slot.

    Mirrors the collection.move() calls exactly, so focus can be carried across
    the move by identity rather than by guesswork.

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

        # Carry focus with the row it was pointing at.
        scene.coco_selections_index = new_pos.get(
            scene.coco_selections_index, scene.coco_selections_index
        )
        _clamp_focus(scene)
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
    """Change what the selected set holds, using the current object selection"""

    bl_idname = "cocosel.update"
    bl_label = "Update Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})
    mode: EnumProperty(
        name="Mode",
        items=(
            ('REPLACE', "Change", "Replace the set with the selected objects"),
            ('ADD', "Add", "Add the selected objects to the set"),
            ('REMOVE', "Remove", "Remove the selected objects from the set"),
        ),
        default='REPLACE',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        if len(context.scene.coco_selections) == 0:
            return False
        if len(_acting_indices(context.scene)) > 1:
            cls.poll_message_set("Select a single set to edit")
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

        objects = context.selected_objects
        if not objects and self.mode != 'REPLACE':
            self.report({'WARNING'}, "Nothing selected in the viewport")
            return {'CANCELLED'}

        if self.mode == 'REPLACE':
            sel_set.store(objects)
            self.report(
                {'INFO'},
                "'%s' now holds %d object(s)" % (sel_set.name, len(sel_set.objects)),
            )
        elif self.mode == 'ADD':
            added = sel_set.add_objects(objects)
            self.report(
                {'INFO'},
                "Added %d object(s) to '%s'%s"
                % (
                    added,
                    sel_set.name,
                    "" if added == len(objects) else " (the rest were already in it)",
                ),
            )
        else:
            removed = sel_set.remove_objects(objects)
            if not removed:
                self.report({'WARNING'}, "None of those are in '%s'" % sel_set.name)
                return {'CANCELLED'}
            self.report(
                {'INFO'}, "Removed %d object(s) from '%s'" % (removed, sel_set.name)
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
        suspend_use_sync(True)
        try:
            for sel_set in scene.coco_selections:
                if self.action == 'ALL':
                    sel_set.use = True
                elif self.action == 'NONE':
                    sel_set.use = False
                else:
                    sel_set.use = not sel_set.use
        finally:
            suspend_use_sync(False)

        _clamp_focus(scene)

        # Keep the viewport in step with the rows, the way a row click does.
        if context.mode == 'OBJECT':
            apply_object_selection(context, _selected_rows(context))
        return {'FINISHED'}


def _viewport_cleared(scene, depsgraph):
    """Untick every row once the viewport selection is emptied.

    Clicking empty space in the 3D viewport deselects the objects, and this
    makes the rows follow, so the panel never claims a set is active after its
    objects have been clicked away. (The equivalent click inside the list itself
    is not available: `template_list` draws the padding below its rows in C and
    exposes no click event to Python.)

    The guard against undoing our own work is that a set holding objects can
    only end up with an empty viewport because something else cleared it. When
    the selected rows hold nothing at all, the empty viewport is this add-on's
    own doing and the rows are left alone - which matters because the handler
    runs after the operator has finished, so a simple in-progress flag would
    always have been reset by the time we got here.
    """
    sets = getattr(scene, "coco_selections", None)
    if not sets:
        return

    rows = [s for s in sets if s.use]
    if not rows:
        return

    context = bpy.context
    if getattr(context, "mode", None) != 'OBJECT':
        return

    try:
        if context.selected_objects:
            return
    except AttributeError:
        return

    if not any(s.valid_objects() for s in rows):
        return

    suspend_use_sync(True)
    try:
        for sel_set in sets:
            sel_set.use = False
    finally:
        suspend_use_sync(False)

    _redraw_viewports(context)


classes = (
    COCOSEL_OT_add,
    COCOSEL_OT_remove,
    COCOSEL_OT_move,
    COCOSEL_OT_select,
    COCOSEL_OT_update,
    COCOSEL_OT_check_all,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if _viewport_cleared not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_viewport_cleared)


def unregister():
    if _viewport_cleared in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_viewport_cleared)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
