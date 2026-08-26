"""UI layer. Everything view-facing lives here so the N-panel can be swapped
for another host (popup, pie, dedicated editor) without touching the data or
the operators."""

import bpy
from bpy.types import Panel, UIList


class COCOSEL_UL_selections(UIList):
    """One row per stored selection set.

    The whole row is one click target, so clicking anywhere on it selects the
    set the way clicking a file selects it in Explorer. A UIList row click
    cannot report modifier keys to Python, but an operator button can, which is
    what makes Ctrl and Shift work at all.

    Selected rows paint themselves with `depress`, which picks up the theme's
    selection colour across the full width. A UIList cannot paint a row
    background and only ever highlights the one active row, so this is the only
    way to show several selected rows at once - and it keeps the selection cue
    to a single thing rather than a highlight plus an icon.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            selected = item.use

            # One button for the whole row, so a selected row is a single
            # unbroken bar. Blender centres text in a wide button and offers no
            # left-align for one, so the count rides in the label rather than
            # sitting in a second button - which is what used to seam the bar.
            row.operator(
                "cocosel.row_click",
                text="%s   %d" % (item.name, len(item.valid_objects())),
                emboss=selected,
                depress=selected,
            ).index = index

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='RESTRICT_SELECT_OFF')


class COCOSEL_PT_rename(Panel):
    """Popup shown by a double-click or the pencil.

    Opened with `wm.call_panel(keep_open=False)` - the same mechanism as
    Blender's own F2 rename - so confirming the field applies the name and
    closes the popup in one Enter. An operator popup needs two: one to confirm
    the field, one to dismiss the popup.
    """

    bl_idname = "COCOSEL_PT_rename"
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Rename Selection Set"

    def draw(self, context):
        scene = context.scene
        layout = self.layout

        index = scene.coco_selections_index
        if 0 <= index < len(scene.coco_selections):
            current = layout.row()
            current.active = False
            current.label(text=scene.coco_selections[index].name, icon='GREASEPENCIL')

        # Focused, and empty: typing replaces the name outright. Blender can
        # focus a popup field but never select its contents, so starting empty
        # is the only way to get select-all behaviour.
        layout.activate_init = True
        layout.prop(scene, "coco_rename_buffer", text="")


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
            "coco_selections_ui_index",
            rows=4,
        )

        side = row.column(align=True)
        side.operator("cocosel.add", text="", icon='ADD')
        side.operator("cocosel.remove", text="", icon='REMOVE')
        side.separator()
        side.operator("cocosel.move", text="", icon='TRIA_UP').direction = 'UP'
        side.operator("cocosel.move", text="", icon='TRIA_DOWN').direction = 'DOWN'
        side.separator()
        side.operator("cocosel.rename", text="", icon='GREASEPENCIL').index = -1

        if not scene.coco_selections:
            layout.label(text="Select objects, then press +", icon='INFO')
            return

        if len(scene.coco_selections) > 1:
            bulk = layout.row(align=True)
            bulk.operator("cocosel.check_all", text="All").action = 'ALL'
            bulk.operator("cocosel.check_all", text="None").action = 'NONE'
            bulk.operator("cocosel.check_all", text="Invert").action = 'INVERT'

        layout.operator(
            "cocosel.update", text="Update", icon='FILE_REFRESH'
        ).index = -1


classes = (
    COCOSEL_UL_selections,
    COCOSEL_PT_rename,
    COCOSEL_PT_selections,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
