"""The CocoAttributes panel in the Properties editor's Data tab, with two
sub-panels: Vertex Groups, and Attributes (UV maps, color attributes and every
other attribute in one list). It is a panel of its own, beside Blender's
panels, not a change to them: those keep working on the active object only,
these on every selected mesh."""

import bpy
from bpy.types import Panel

from . import common, lists, operators


class _DataTab:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        # The Data tab follows the active object: it only shows mesh panels
        # while the active object is a mesh.
        obj = context.object
        return obj is not None and obj.type == 'MESH'


class COCOATTRS_PT_main(_DataTab, Panel):
    bl_idname = "COCOATTRS_PT_main"
    bl_label = "CocoAttributes"

    def draw(self, context):
        snap = common.snapshot(context)
        text = f"Every selected mesh: {snap.total}"
        if snap.objects != snap.total:
            # Linked duplicates share one mesh, so they count once.
            text += f" ({snap.objects} objects)"
        self.layout.label(text=text, icon='MESH_DATA')


def draw_list(layout, context, list_id, rows=4):
    """One list and its side buttons. Hands the rows to the sync and the
    total to the list before template_list() draws them."""
    snap = common.snapshot(context)
    lists.request_sync(list_id, snap.rows[list_id], context)
    lists.set_total(snap.total)

    wm = context.window_manager
    row = layout.row()
    row.template_list("COCOATTRS_UL_items", list_id, wm, lists.COLLECTIONS[list_id],
                      wm, lists.INDEX_PROPS[list_id], rows=rows)

    add, remove, fill, check_all = operators.BUTTONS[list_id]
    side = row.column(align=True)
    side.operator(add.bl_idname, text="", icon='ADD')
    side.operator(remove.bl_idname, text="", icon='REMOVE')
    side.separator()
    side.operator(fill.bl_idname, text="", icon='PASTEDOWN')
    side.separator()
    any_ticked = any(item.use for item in lists.items(list_id, context))
    side.operator(check_all.bl_idname, text="",
                  icon='CHECKBOX_HLT' if any_ticked else 'CHECKBOX_DEHLT')

    note = lists.rename_notes.get(list_id)
    if note:
        layout.label(text=note, icon='ERROR')


class COCOATTRS_PT_vertex_groups(_DataTab, Panel):
    bl_idname = "COCOATTRS_PT_vertex_groups"
    bl_label = "Vertex Groups"
    bl_parent_id = "COCOATTRS_PT_main"

    def draw(self, context):
        layout = self.layout
        draw_list(layout, context, 'VGROUP')
        if context.mode != 'EDIT_MESH':
            return
        row = layout.row()
        sub = row.row(align=True)
        sub.operator(operators.COCOATTRS_OT_assign_to_groups.bl_idname, text="Assign")
        sub.operator(operators.COCOATTRS_OT_remove_from_groups.bl_idname, text="Remove")
        sub = row.row(align=True)
        sub.operator(operators.COCOATTRS_OT_select_group_vertices.bl_idname, text="Select")
        sub.operator(operators.COCOATTRS_OT_deselect_group_vertices.bl_idname, text="Deselect")
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        # Blender's own Weight, the one its Assign uses too.
        col.prop(context.scene.tool_settings, "vertex_group_weight", text="Weight")


class COCOATTRS_PT_attributes(_DataTab, Panel):
    bl_idname = "COCOATTRS_PT_attributes"
    bl_label = "Attributes"
    bl_parent_id = "COCOATTRS_PT_main"

    def draw(self, context):
        layout = self.layout
        draw_list(layout, context, 'DATA', rows=6)
        snap = common.snapshot(context)
        row = layout.row()
        row.operator(operators.COCOATTRS_OT_add_custom_normals.bl_idname,
                     text="Add Custom Normals", icon='ADD')
        info = row.row()
        info.alignment = 'RIGHT'
        info.active = False
        info.label(text=f"{snap.custom_normals}/{snap.total} have them")


classes = (
    COCOATTRS_PT_main,
    COCOATTRS_PT_vertex_groups,
    COCOATTRS_PT_attributes,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
