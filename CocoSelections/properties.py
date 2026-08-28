"""Data model: a named set of object references, stored on the Scene."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

# Bulk operators set many `use` flags in a row; syncing the viewport on every
# one of them would be quadratic and would fight the operator's own final sync.
_suspend_use_sync = False


def suspend_use_sync(state):
    """Turn the per-checkbox viewport sync off while an operator does the work."""
    global _suspend_use_sync
    _suspend_use_sync = state


def _use_updated(self, context):
    """Keep the viewport in step when a checkbox is clicked or dragged over.

    Blender toggles boolean checkboxes as the mouse drags across them, which is
    where the drag-to-select behaviour comes from - it is native, and only works
    because this is a real BoolProperty rather than an operator button.
    """
    if _suspend_use_sync:
        return

    scene = getattr(context, "scene", None)
    if scene is None or getattr(context, "mode", None) != 'OBJECT':
        return

    from . import operators

    operators.apply_object_selection(
        context, [s for s in scene.coco_selections if s.use]
    )


def _ui_index_set(self, value):
    """Turn a click on a row's name field into a selection.

    The name has to be a real text field for Blender's native double-click
    rename to work, and a click on a text field inside a UIList is routed to the
    list rather than to our row operator - so it arrives here instead. No
    modifier state reaches a property setter, so this is always a plain click;
    Ctrl and Shift only work on the count cell, which is a real button.
    """
    from . import operators

    if not (0 <= value < len(self.coco_selections)):
        return

    operators.select_only(self, value)

    context = bpy.context
    if getattr(context, "mode", None) == 'OBJECT':
        rows = [s for s in self.coco_selections if s.use]
        operators.apply_object_selection(context, rows)


class COCOSEL_ObjectRef(PropertyGroup):
    """One object slot inside a selection set.

    A real object pointer (not a name) so the set survives object renames,
    and goes to None on its own when the object is deleted.
    """

    obj: PointerProperty(type=bpy.types.Object)


class COCOSEL_Selection(PropertyGroup):
    """A named group of objects the user can restore later."""

    name: StringProperty(name="Name", default="Selection")
    objects: CollectionProperty(type=COCOSEL_ObjectRef)
    use: BoolProperty(
        name="Selected",
        description="This row is part of the current multi-row selection",
        default=False,
        update=_use_updated,
    )

    def valid_objects(self):
        """Objects still alive in the file, in stored order."""
        return [ref.obj for ref in self.objects if ref.obj is not None]

    def purge(self):
        """Drop slots whose object has been deleted."""
        for i in range(len(self.objects) - 1, -1, -1):
            if self.objects[i].obj is None:
                self.objects.remove(i)

    def store(self, objects):
        """Replace the contents of this set."""
        self.objects.clear()
        for obj in objects:
            self.objects.add().obj = obj

    def add_objects(self, objects):
        """Add objects the set does not already hold. Returns how many landed."""
        held = {ref.obj.as_pointer() for ref in self.objects if ref.obj is not None}
        added = 0
        for obj in objects:
            key = obj.as_pointer()
            if key in held:
                continue
            self.objects.add().obj = obj
            held.add(key)
            added += 1
        return added

    def remove_objects(self, objects):
        """Drop the given objects from the set. Returns how many went."""
        drop = {obj.as_pointer() for obj in objects}
        removed = 0
        for i in range(len(self.objects) - 1, -1, -1):
            ref = self.objects[i]
            if ref.obj is not None and ref.obj.as_pointer() in drop:
                self.objects.remove(i)
                removed += 1
        return removed


classes = (
    COCOSEL_ObjectRef,
    COCOSEL_Selection,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.coco_selections = CollectionProperty(type=COCOSEL_Selection)
    bpy.types.Scene.coco_selections_index = IntProperty(
        name="Active Selection Set",
        default=0,
        min=0,
    )
    # template_list always paints its active row in the theme's selection
    # colour - the same colour a selected row paints itself with. That made a
    # focused-but-unselected row look selected, so the list is handed an index
    # that is permanently -1 (nothing active) and the `use` flags are left as
    # the only thing that colours a row.
    bpy.types.Scene.coco_selections_ui_index = IntProperty(
        name="Clicked List Row",
        get=lambda self: -1,
        set=_ui_index_set,
    )


def unregister():
    del bpy.types.Scene.coco_selections_ui_index
    del bpy.types.Scene.coco_selections_index
    del bpy.types.Scene.coco_selections

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
