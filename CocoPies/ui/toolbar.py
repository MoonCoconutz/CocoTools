"""The toolbar above the Pie Menus list, and its Presets menu.

Everything that used to sit on each row (duplicate, delete) or under the list
(New Pie Menu, reorder, the Presets box, Refresh All Keymaps) is here instead,
so the rows carry only what differs between pies. The row buttons act on the
selected pie; the rest go into one menu.
"""

from bpy.types import Menu

from ..items import TWO_ICON_BUTTONS_UNITS
from ..utils import section_neighbour


class COCOPIE_MT_list_presets(Menu):
    """Export, import and the whole-list actions of the Pie Menus list"""
    bl_idname = "COCOPIE_MT_list_presets"
    bl_label = "Presets"

    def draw(self, context):
        layout = self.layout
        # Stated rather than left to the default: these all need invoke -- the
        # file browser for Export/Import, the confirmation for Restore and
        # Delete All.
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator("cocopie.save_preset", text="Export", icon='EXPORT')
        layout.operator("cocopie.load_preset", text="Import", icon='IMPORT')
        layout.separator()
        layout.operator("cocopie.restore_defaults", text="Restore Starter Pies",
                        icon='RECOVER_LAST')
        layout.operator("cocopie.refresh_menus", text="Refresh All Keymaps",
                        icon='FILE_REFRESH')
        layout.separator()
        layout.operator("cocopie.remove_all_pie_menus",
                        text="Delete All Pie Menus", icon='TRASH')


def draw_list_toolbar(layout, prefs):
    """New, duplicate, delete, move up/down and the Presets menu, on one line"""
    index = prefs.active_pie_index
    has_selection = 0 <= index < len(prefs.pie_menus)

    row = layout.row(align=True)
    row.scale_y = 1.2
    row.operator("cocopie.add_pie_menu", text="New", icon='ADD')

    selected = row.row(align=True)
    selected.enabled = has_selection
    selected.operator("cocopie.duplicate_pie_menu", text="",
                      icon='DUPLICATE').index = index
    selected.operator("cocopie.remove_pie_menu", text="",
                      icon='TRASH').index = index

    row.separator(factor=0.5)

    reorder = row.row(align=True)
    reorder.ui_units_x = TWO_ICON_BUTTONS_UNITS
    # The arrows move inside the selected pie's section, so each greys out at
    # the edge of that section -- both of them for a pie alone in its section
    up = reorder.row(align=True)
    up.enabled = (has_selection
                  and section_neighbour(prefs.pie_menus, index, -1) is not None)
    up.operator("cocopie.move_pie_menu", text="", icon='TRIA_UP').direction = 'UP'
    down = reorder.row(align=True)
    down.enabled = (has_selection
                    and section_neighbour(prefs.pie_menus, index, 1) is not None)
    down.operator("cocopie.move_pie_menu", text="", icon='TRIA_DOWN').direction = 'DOWN'

    row.separator(factor=0.5)

    presets = row.row(align=True)
    presets.ui_units_x = 5
    presets.menu("COCOPIE_MT_list_presets", text="Presets", icon='PRESET')
