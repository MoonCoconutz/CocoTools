"""Add-on preferences: the name of the sidebar tab the panels live in."""

import bpy
from bpy.props import StringProperty
from bpy.types import AddonPreferences, Operator

DEFAULT_TAB = "CocoUVs"


def _tab_changed(self, context):
    from . import ui

    ui.update_tab()


class COCOUVS_OT_tab_reset(Operator):
    bl_idname = "cocouvs.tab_reset"
    bl_label = "Reset Sidebar Tab"
    bl_description = "Put the default tab name back"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.preferences.addons[__package__].preferences.tab_name = DEFAULT_TAB
        return {'FINISHED'}


class COCOUVS_Preferences(AddonPreferences):
    bl_idname = __package__

    tab_name: StringProperty(
        name="Sidebar Tab",
        description="Name of the UV Editor sidebar tab showing CocoUVs. "
        "Clear it to remove the panels from the sidebar",
        default=DEFAULT_TAB,
        update=_tab_changed,
    )

    def draw(self, context):
        row = self.layout.row(align=True)
        row.prop(self, "tab_name")
        row.operator("cocouvs.tab_reset", text="", icon='LOOP_BACK')
        if not self.tab_name.strip():
            self.layout.label(text="The CocoUVs panels are hidden while the name is empty", icon='INFO')


_classes = (COCOUVS_OT_tab_reset, COCOUVS_Preferences)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
