"""Operators driving the selection set list."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator


def _resolve(context, index):
    """Return the set at `index`, or the highlighted one when index < 0."""
    sets = context.scene.coco_selections
    if index < 0:
        index = context.scene.coco_selections_index
    if 0 <= index < len(sets):
        return sets[index]
    return None


def _selected_rows(context):
    """Rows in the current multi-row selection, in list order."""
    return [s for s in context.scene.coco_selections if s.use]


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


def _clamp_anchor(scene):
    count = len(scene.coco_selections)
    if count:
        scene.coco_selections_anchor = max(0, min(scene.coco_selections_anchor, count - 1))
    else:
        scene.coco_selections_anchor = 0


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

        index = len(scene.coco_selections) - 1
        scene.coco_selections_index = index

        # The new row becomes the selection, the way a new folder does in a file
        # browser - and it honestly reflects what is selected right now.
        for sel_set in scene.coco_selections:
            sel_set.use = False
        item.use = True
        scene.coco_selections_anchor = index

        self.report({'INFO'}, "'%s' stores %d object(s)" % (name, len(item.objects)))
        return {'FINISHED'}


class COCOSEL_OT_remove(Operator):
    """Remove the highlighted selection set"""

    bl_idname = "cocosel.remove"
    bl_label = "Remove Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.coco_selections) > 0

    def execute(self, context):
        scene = context.scene
        index = scene.coco_selections_index
        if not (0 <= index < len(scene.coco_selections)):
            return {'CANCELLED'}

        scene.coco_selections.remove(index)
        scene.coco_selections_index = max(0, min(index, len(scene.coco_selections) - 1))
        _clamp_anchor(scene)
        return {'FINISHED'}


class COCOSEL_OT_move(Operator):
    """Move the highlighted selection set up or down in the list"""

    bl_idname = "cocosel.move"
    bl_label = "Move Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction",
        items=(
            ('UP', "Up", "Move the set one slot up"),
            ('DOWN', "Down", "Move the set one slot down"),
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
        index = scene.coco_selections_index
        new_index = index - 1 if self.direction == 'UP' else index + 1

        if not (0 <= index < len(sets)) or not (0 <= new_index < len(sets)):
            return {'CANCELLED'}

        sets.move(index, new_index)
        scene.coco_selections_index = new_index

        # Keep the range anchor pinned to the row it was pointing at.
        anchor = scene.coco_selections_anchor
        if anchor == index:
            scene.coco_selections_anchor = new_index
        elif anchor == new_index:
            scene.coco_selections_anchor = index
        return {'FINISHED'}


class COCOSEL_OT_row_click(Operator):
    """Select this set. Shift-click for a range, Ctrl-click to add or remove"""

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
        self.use_toggle = event.ctrl
        self.use_range = event.shift
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        sets = scene.coco_selections
        index = self.index
        if not (0 <= index < len(sets)):
            return {'CANCELLED'}

        anchor = scene.coco_selections_anchor

        if self.use_range and 0 <= anchor < len(sets):
            low, high = (anchor, index) if anchor <= index else (index, anchor)
            if not self.use_toggle:
                # Plain Shift replaces the selection, Ctrl+Shift adds to it.
                for sel_set in sets:
                    sel_set.use = False
            for i in range(low, high + 1):
                sets[i].use = True
            # The anchor deliberately stays put, so the range can be resized by
            # shift-clicking somewhere else - exactly like a file browser.
        elif self.use_toggle:
            sets[index].use = not sets[index].use
            scene.coco_selections_anchor = index
        else:
            for sel_set in sets:
                sel_set.use = False
            sets[index].use = True
            scene.coco_selections_anchor = index

        scene.coco_selections_index = index

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
        row, falling back to the highlighted one when nothing is selected."""
        if self.index >= 0:
            sets = context.scene.coco_selections
            return [sets[self.index]] if 0 <= self.index < len(sets) else []

        rows = _selected_rows(context)
        if rows:
            return rows

        active = _resolve(context, -1)
        return [active] if active is not None else []


class COCOSEL_OT_update(Operator):
    """Replace the contents of the highlighted set with the current selection"""

    bl_idname = "cocosel.update"
    bl_label = "Update From Selection"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return len(context.scene.coco_selections) > 0

    def execute(self, context):
        sel_set = _resolve(context, self.index)
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
        for sel_set in context.scene.coco_selections:
            if self.action == 'ALL':
                sel_set.use = True
            elif self.action == 'NONE':
                sel_set.use = False
            else:
                sel_set.use = not sel_set.use

        # Keep the viewport in step with the rows, the way a row click does.
        if context.mode == 'OBJECT':
            apply_object_selection(context, _selected_rows(context))
        return {'FINISHED'}


classes = (
    COCOSEL_OT_add,
    COCOSEL_OT_remove,
    COCOSEL_OT_move,
    COCOSEL_OT_row_click,
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
