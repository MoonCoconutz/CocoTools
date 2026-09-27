"""Add-on preferences: the name of the sidebar tab the panels live in."""

import bpy
from bpy.props import StringProperty
from bpy.types import AddonPreferences


def _tab_changed(self, context):
    from . import ui

    ui.update_tab()


class COCOUVS_Preferences(AddonPreferences):
    bl_idname = __package__

    tab_name: StringProperty(
        name="Sidebar Tab",
        description="Name of the UV Editor sidebar tab showing CocoUVs. "
        "Clear it to remove the panels from the sidebar",
        default="CocoUVs",
        update=_tab_changed,
    )

    def draw(self, context):
        self.layout.prop(self, "tab_name")
        if not self.tab_name.strip():
            self.layout.label(text="The CocoUVs panels are hidden while the name is empty", icon='INFO')


def register():
    bpy.utils.register_class(COCOUVS_Preferences)


def unregister():
    bpy.utils.unregister_class(COCOUVS_Preferences)
