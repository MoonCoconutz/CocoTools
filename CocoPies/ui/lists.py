"""The pie menu list widget."""

import bpy
import os
import json
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, FloatProperty,
)
from bpy.types import Operator, PropertyGroup, Menu, AddonPreferences
from ..items import (
    POSITION_ARROWS, POSITION_NAMES, POSITION_GRID,
    GRID_CELL_UNITS, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from ..utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
    pie_group_key, GROUP_KEYS,
)
from ..icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)


class COCOPIE_UL_pie_menus(bpy.types.UIList):
    """List of pie menus — native row highlight makes the active one clear"""
    bl_idname = "COCOPIE_UL_pie_menus"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        pie = item
        row = layout.row(align=False)
        row.scale_y = 1.2

        # Enabled checkbox
        row.prop(pie, "enabled", text="",
                  icon='CHECKBOX_HLT' if pie.enabled else 'CHECKBOX_DEHLT', emboss=False)

        # Split the row into fixed *percentage* columns so every row lines up
        # identically, regardless of how long the pie menu's name is.
        name_shortcut_split = row.split(factor=0.55, align=True)

        name_col = name_shortcut_split.row(align=True)
        name_col.alignment = 'LEFT'
        name_col.active = pie.enabled
        name_col.label(text=pie.name or "Untitled")

        shortcut_actions_split = name_shortcut_split.split(factor=0.58, align=True)

        # Keymap shortcut — its own fixed-percentage column
        shortcut_col = shortcut_actions_split.row(align=True)
        shortcut_col.alignment = 'RIGHT'
        shortcut_col.active = pie.enabled
        if find_shortcut_conflicts(data, pie, index):
            warn = shortcut_col.row(align=True)
            warn.label(text="", icon='ERROR')
        shortcut_col.label(text=format_shortcut(pie))

        # Action icons — own fixed-percentage column, always at the far right
        actions_col = shortcut_actions_split.row(align=True)
        actions_col.alignment = 'RIGHT'
        op = actions_col.operator("cocopie.duplicate_pie_menu", text="", icon='DUPLICATE', emboss=False)
        op.index = index
        op = actions_col.operator("cocopie.remove_pie_menu", text="", icon='TRASH', emboss=False)
        op.index = index

    # Which section this list draws. None on the base class, which then shows
    # everything; each registered subclass below pins it to one group.
    cocopie_group_key = None

    def filter_items(self, context, data, propname):
        # Order is never changed -- the stored order is the display order
        # within a section. The only thing filtered is *which* section's pies
        # this particular list shows, so the sections' headings can be drawn
        # as ordinary labels between the lists (see draw_left_column) rather
        # than inside a row, where a heading would swallow the first pie's
        # click and selection highlight.
        items = getattr(data, propname)
        key = self.cocopie_group_key

        if key is None:
            flt_flags = [self.bitflag_filter_item] * len(items)
        else:
            flt_flags = [
                self.bitflag_filter_item if pie_group_key(pie) == key else 0
                for pie in items
            ]

        return flt_flags, []


def _make_group_uilist(key):
    """One UIList subclass per section.

    template_list gives the list class no arguments, so a single shared class
    could not tell which section it was drawing. Blender does expose
    UIList.list_id, but what it holds at filter time is not something that can
    be checked headlessly -- a wrong guess there would show every pie in every
    section. One registered class per section needs no such assumption, and
    the set of sections is fixed and known up front (utils.GROUP_KEYS).
    """
    name = f"COCOPIE_UL_pie_menus_{key}"
    return type(name, (COCOPIE_UL_pie_menus,), {
        "bl_idname": name,
        "cocopie_group_key": key,
    })


# Keyed by section so draw_left_column can look up the class for a section
GROUP_UILISTS = {key: _make_group_uilist(key) for key in GROUP_KEYS}
