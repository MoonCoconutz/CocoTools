"""UI layer. Everything view-facing lives here so the popover can be swapped
for another host (popup, pie, dedicated editor) without touching the data or
the operators."""

import bpy
from bpy.types import Panel, UIList


class COCOSEL_UL_selections(UIList):
    """One row per stored selection set: checkbox, name, count.

    Each cell is a different widget because each one is the only thing Blender
    will do that job with:

    - the **checkbox** is a real BoolProperty, which is what makes dragging down
      the column toggle a run of rows - native behaviour that operator buttons
      do not get;
    - the **name** is a real text field, the only widget Blender starts editing
      on a double-click, so renaming happens in place;
    - the **count** is just a label.

    Nothing in the row reads modifier keys, because nothing needs to: clicking a
    checkbox toggles one row, dragging across them toggles a run, and clicking a
    name selects that row alone. Those cover what Ctrl-click, Shift-range and a
    plain click used to do, with no modifiers to remember.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Left: a real BoolProperty checkbox, not an operator button. That
            # is what makes click-and-drag down the column work - Blender
            # toggles boolean checkboxes as the mouse drags across them, and
            # gives operator buttons no such behaviour. The viewport is kept in
            # step by the property's update callback.
            toggle = row.row(align=True)
            toggle.ui_units_x = 1.3
            toggle.prop(item, "use", text="")

            # Middle: a real text field, the only widget Blender will start
            # editing on a double-click.
            row.prop(item, "name", text="", emboss=False)

            # Right: how many objects the set still holds. A plain label - it
            # is not a click target, so dimming it cannot break anything.
            count = row.row(align=True)
            count.alignment = 'RIGHT'
            count.active = False
            count.label(text=str(len(item.valid_objects())))

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='RESTRICT_SELECT_OFF')


class COCOSEL_PT_selections(Panel):
    """Popover hosting the selection set list, opened from the viewport's tool
    header next to Options (see draw_tool_header)."""

    bl_idname = "COCOSEL_PT_selections"
    bl_label = "Selections"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Always drawn, not just when there is something to act on: poll()
        # already greys each button out correctly (check_all needs at least one
        # set, update needs exactly one selected), so hiding the row on top of
        # that only made the panel jump around as rows were added and selected.
        bulk = layout.row(align=True)
        bulk.operator("cocosel.check_all", text="All").action = 'ALL'
        bulk.operator("cocosel.check_all", text="Invert").action = 'INVERT'

        edit = layout.row(align=True)
        change = edit.operator("cocosel.update", text="Change")
        change.index = -1
        change.mode = 'REPLACE'
        add = edit.operator("cocosel.update", text="Add")
        add.index = -1
        add.mode = 'ADD'
        remove = edit.operator("cocosel.update", text="Remove")
        remove.index = -1
        remove.mode = 'REMOVE'

        row = layout.row()
        row.template_list(
            "COCOSEL_UL_selections",
            "",
            scene,
            "coco_selections",
            scene,
            "coco_selections_ui_index",
            rows=4,
        )

        side = row.column(align=True)
        side.operator("cocosel.add", text="", icon='ADD')
        side.operator("cocosel.remove", text="", icon='REMOVE')
        side.separator()
        side.operator("cocosel.move", text="", icon='TRIA_UP').direction = 'UP'
        side.operator("cocosel.move", text="", icon='TRIA_DOWN').direction = 'DOWN'

        if not scene.coco_selections:
            layout.label(text="Select objects, then press +", icon='INFO')


def draw_tool_header(self, context):
    # Appended to VIEW3D_HT_tool_header, whose draw() ends with the mode's
    # settings (Options), so this lands immediately to its right.
    self.layout.popover(panel=COCOSEL_PT_selections.bl_idname, text="Selections")


classes = (
    COCOSEL_UL_selections,
    COCOSEL_PT_selections,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_HT_tool_header.append(draw_tool_header)


def unregister():
    bpy.types.VIEW3D_HT_tool_header.remove(draw_tool_header)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
