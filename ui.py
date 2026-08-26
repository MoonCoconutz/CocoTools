"""UI layer. Everything view-facing lives here so the N-panel can be swapped
for another host (popup, pie, dedicated editor) without touching the data or
the operators."""

import bpy
from bpy.types import Panel, UIList

from . import icons


class COCOSEL_UL_selections(UIList):
    """One row per stored selection set.

    The state dot on the left is the click surface. A UIList row click cannot
    report modifier keys to Python, but an operator button can, so the dot is
    what carries the click / Shift-click / Ctrl-click behaviour.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            scene = context.scene
            row = layout.row(align=True)

            if item.use:
                state = "active" if index == scene.coco_selections_anchor else "selected"
            else:
                state = "empty"

            icon_value = icons.icon_id(state)
            if icon_value:
                click = row.operator(
                    "cocosel.row_click", text="", emboss=False, icon_value=icon_value
                )
            else:
                # Theme icons unavailable - fall back to built-ins.
                click = row.operator(
                    "cocosel.row_click",
                    text="",
                    emboss=False,
                    icon='LAYER_ACTIVE' if item.use else 'LAYER_USED',
                )
            click.index = index

            # Double-click to rename in place.
            row.prop(item, "name", text="", emboss=False)

            count = row.row(align=True)
            count.alignment = 'RIGHT'
            count.active = False
            count.label(text=str(len(item.valid_objects())))

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='RESTRICT_SELECT_OFF')


class COCOSEL_PT_selections(Panel):
    """Sidebar (N) panel hosting the selection set list."""

    bl_idname = "COCOSEL_PT_selections"
    bl_label = "Selections"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Coco"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row()
        row.template_list(
            "COCOSEL_UL_selections",
            "",
            scene,
            "coco_selections",
            scene,
            "coco_selections_index",
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
            return

        if len(scene.coco_selections) > 1:
            bulk = layout.row(align=True)
            bulk.operator("cocosel.check_all", text="All").action = 'ALL'
            bulk.operator("cocosel.check_all", text="None").action = 'NONE'
            bulk.operator("cocosel.check_all", text="Invert").action = 'INVERT'

        selected = sum(1 for s in scene.coco_selections if s.use)

        actions = layout.row(align=True)
        actions.operator(
            "cocosel.select",
            text="Select (%d)" % selected if selected else "Select",
            icon='RESTRICT_SELECT_OFF',
        ).index = -1
        actions.operator(
            "cocosel.update", text="Update", icon='FILE_REFRESH'
        ).index = -1


classes = (
    COCOSEL_UL_selections,
    COCOSEL_PT_selections,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
