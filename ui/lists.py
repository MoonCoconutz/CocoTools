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
    GRID_CELL_SCALE_Y, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from ..utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
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

    def filter_items(self, context, data, propname):
        # No filtering — keep original order
        items = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = []
        return flt_flags, flt_neworder
