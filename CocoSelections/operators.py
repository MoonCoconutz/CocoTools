"""Operators driving the selection set list.

There is exactly one selection: the `use` flag on each row. `coco_selections_index`
is only the focus (the row a click last landed on). Every row command reads the
selection, so the list can never show one thing and act on another.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

from .properties import suspend_use_sync


def selected_rows(scene):
    """Rows in the current selection, in list order."""
    return [s for s in scene.coco_selections if s.use]


def _acting_indices(scene):
    """What a row command acts on.

    Explorer applies Delete to everything selected, so the selection wins. The
    focused row is a fallback for when nothing is selected at all.
    """
    indices = [i for i, sel_set in enumerate(scene.coco_selections) if sel_set.use]
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


def apply_object_selection(context, targets, extend=False):
    """Select the union of `targets` in the viewport, list order preserved.

    An empty `targets` with extend off clears the selection - which is what
    unticking the last row should do. The last object selected becomes active.

    Returns (found, unreachable): unreachable objects are hidden, unselectable,
    or not in this view layer (excluded collection, another scene).
    """
    objects = []
    for sel_set in targets:
        sel_set.purge()
        objects.extend(sel_set.valid_objects())
    objects = list(dict.fromkeys(objects))

    view_objects = context.view_layer.objects

    if not extend:
        keep = set(objects)
        for obj in list(view_objects.selected):
            # An object deleted a moment ago reads None until the view layer
            # is synced again.
            if obj is not None and obj not in keep:
                obj.select_set(False)

    found = 0
    last = None
    for obj in objects:
        try:
            obj.select_set(True)
        except RuntimeError:
            # Not in this view layer.
            continue
        # Hidden or unselectable objects are refused without an error.
        if obj.select_get():
            found += 1
            last = obj

    if last is not None:
        view_objects.active = last

    return found, len(objects) - found


def _clamp_focus(scene):
    count = len(scene.coco_selections)
    high = count - 1 if count else 0
    scene.coco_selections_index = max(0, min(scene.coco_selections_index, high))


def select_only(scene, index):
    """Make `index` the whole selection, and the focused row.

    The only selection rule left that needs code: a checkbox toggles its own row
    and a drag toggles a run, both handled by Blender itself. The viewport is
    left to the caller, so it is synced once.
    """
    sets = scene.coco_selections
    if not (0 <= index < len(sets)):
        return False

    suspend_use_sync(True)
    try:
        for i, sel_set in enumerate(sets):
            if sel_set.use != (i == index):
                sel_set.use = i == index
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
        # browser - and it honestly reflects what is selected right now, so the
        # viewport needs no sync.
        select_only(scene, len(scene.coco_selections) - 1)

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
            select_only(scene, min(indices[0], count - 1))
        else:
            scene.coco_selections_index = 0

        if context.mode == 'OBJECT':
            apply_object_selection(context, selected_rows(scene))

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
        targets = self.targets(context.scene)
        if not targets:
            return {'CANCELLED'}

        found, unreachable = apply_object_selection(context, targets, self.extend)

        label = targets[0].name if len(targets) == 1 else "%d sets" % len(targets)
        if found == 0:
            self.report({'WARNING'}, "'%s' has no selectable objects" % label)
        elif unreachable:
            self.report(
                {'WARNING'},
                "Selected %d object(s) from %s, %d hidden or not in this view layer"
                % (found, label, unreachable),
            )
        elif len(targets) > 1:
            self.report({'INFO'}, "Selected %d object(s) from %s" % (found, label))
        return {'FINISHED'}

    def targets(self, scene):
        """An explicit index acts on that row alone, otherwise every selected
        row, falling back to the focused one when nothing is selected."""
        sets = scene.coco_selections
        if self.index >= 0:
            return [sets[self.index]] if self.index < len(sets) else []
        return [sets[i] for i in _acting_indices(scene)]


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
        indices = _acting_indices(context.scene)
        if len(indices) > 1:
            cls.poll_message_set("Select a single set to edit")
        return len(indices) == 1

    def execute(self, context):
        sets = context.scene.coco_selections
        if self.index >= 0:
            index = self.index
        else:
            indices = _acting_indices(context.scene)
            index = indices[0] if len(indices) == 1 else -1
        if not (0 <= index < len(sets)):
            return {'CANCELLED'}
        sel_set = sets[index]

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
                    use = True
                elif self.action == 'NONE':
                    use = False
                else:
                    use = not sel_set.use
                if sel_set.use != use:
                    sel_set.use = use
        finally:
            suspend_use_sync(False)

        # Keep the viewport in step with the rows, the way a row click does.
        if context.mode == 'OBJECT':
            apply_object_selection(context, selected_rows(scene))
        return {'FINISHED'}


@bpy.app.handlers.persistent
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

    Runs on every depsgraph update (each step of a drag, each frame of
    playback), so the cheap tests come first, and only the scene on screen is
    compared with the viewport's own view layer. Persistent, or opening any
    file would drop it.
    """
    rows = selected_rows(scene)
    if not rows:
        return

    context = bpy.context
    if (
        scene != context.scene
        or context.mode != 'OBJECT'
        or context.view_layer.objects.selected
    ):
        return

    if not any(ref.obj is not None for s in rows for ref in s.objects):
        return

    suspend_use_sync(True)
    try:
        for sel_set in rows:
            sel_set.use = False
    finally:
        suspend_use_sync(False)


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

    bpy.app.handlers.depsgraph_update_post.append(_viewport_cleared)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_viewport_cleared)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
