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

# Guards the buffer's update callback against re-entering when it clears itself.
_applying_rename = False


def _apply_rename(self, context):
    """Rename the focused set to whatever was typed, then clear the buffer.

    The buffer lives on the Scene rather than on the rename operator because a
    property update callback on an operator cannot see attributes set in its
    invoke() - Blender does not carry the Python instance across - and an
    operator popup never calls execute(). A scene property has neither problem,
    and can be driven directly from a test.
    """
    global _applying_rename
    if _applying_rename:
        return

    name = self.coco_rename_buffer.strip()
    if not name:
        return

    index = self.coco_selections_index
    if 0 <= index < len(self.coco_selections):
        self.coco_selections[index].name = name

    _applying_rename = True
    try:
        self.coco_rename_buffer = ""
    finally:
        _applying_rename = False


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
    # Explorer-style range anchor: the row a plain or Ctrl click last landed on.
    bpy.types.Scene.coco_selections_anchor = IntProperty(
        name="Range Anchor",
        default=0,
        min=0,
    )
    # template_list always paints its active row in the theme's selection
    # colour - the same colour a selected row paints itself with. That made a
    # focused-but-unselected row look selected, so the list is handed an index
    # that is permanently -1 (nothing active) and the `use` flags are left as
    # the only thing that colours a row.
    # What the rename popup types into. Empty between renames.
    bpy.types.Scene.coco_rename_buffer = StringProperty(
        name="Name",
        default="",
        options={'SKIP_SAVE'},
        update=_apply_rename,
    )
    bpy.types.Scene.coco_selections_ui_index = IntProperty(
        name="Unused List Index",
        get=lambda self: -1,
        set=lambda self, value: None,
    )


def unregister():
    del bpy.types.Scene.coco_selections_ui_index
    del bpy.types.Scene.coco_rename_buffer
    del bpy.types.Scene.coco_selections_anchor
    del bpy.types.Scene.coco_selections_index
    del bpy.types.Scene.coco_selections

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
