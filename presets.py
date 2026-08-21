"""Reading preset dictionaries back into pie menus, and resolving name
collisions when a preset overlaps what is already configured."""

import bpy
import os
import json
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, FloatProperty,
)
from bpy.types import Operator, PropertyGroup, Menu, AddonPreferences
from .items import (
    POSITION_ARROWS, POSITION_NAMES, POSITION_GRID,
    GRID_CELL_SCALE_Y, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
)
from .keymaps import register_pie_menus, unregister_pie_menus


# Carries a preset across the gap between loading the file and asking what to
# do about name collisions. This module owns it: everything else mutates it in
# place, because rebinding the name elsewhere would leave this module -- which
# is what draws the popup -- still looking at the old dict.
_pending_preset_data = {"pie_menus": [], "conflicts": [], "window": None}


def _apply_pie_dict(pie, pie_dict):
    """Copy a preset dict's fields onto an existing/new COCOPIE_PieMenuData item"""
    # A "label" key in older presets is ignored -- that field no longer exists
    pie.idname = pie_dict.get("idname", "COCOPIE_MT_custom_pie")
    pie.keymap_type = pie_dict.get("keymap_type", "WINDOW")
    pie.key = pie_dict.get("key", "Q")
    pie.ctrl = pie_dict.get("ctrl", False)
    pie.shift = pie_dict.get("shift", False)
    pie.alt = pie_dict.get("alt", False)
    pie.enabled = pie_dict.get("enabled", True)
    pie.items.clear()
    for item_dict in pie_dict.get("items", []):
        item = pie.items.add()
        item.label = item_dict.get("label", "Item")
        item.command = item_dict.get("command", "")
        item.icon = item_dict.get("icon", "NONE")
        item.enabled = item_dict.get("enabled", True)
        item.position = item_dict.get("position", 0)


def _merge_preset_menus(prefs, incoming, mode):
    """Merge incoming pie menu dicts into prefs.pie_menus without wiping existing ones.

    mode == 'REPLACE': menus whose name matches an existing one are overwritten.
    mode == 'SKIP' (or any other value): existing menus are left untouched;
        only menus with new names are added.
    Returns (added_count, replaced_count).
    """
    unregister_pie_menus()

    existing_by_name = {pie.name: i for i, pie in enumerate(prefs.pie_menus)}
    added = 0
    replaced = 0

    for pie_dict in incoming:
        name = pie_dict.get("name", "Pie Menu")

        if name in existing_by_name:
            if mode == 'REPLACE':
                pie = prefs.pie_menus[existing_by_name[name]]
                _apply_pie_dict(pie, pie_dict)
                replaced += 1
            # SKIP: leave the existing menu untouched
            continue

        pie = prefs.pie_menus.add()
        pie.name = name
        _apply_pie_dict(pie, pie_dict)
        existing_by_name[name] = len(prefs.pie_menus) - 1
        added += 1

    register_pie_menus()
    return added, replaced


def _draw_preset_conflict_popup(popup_self, popup_context):
    conflicts = _pending_preset_data.get("conflicts", [])
    conflict_names = ", ".join(conflicts[:5])
    if len(conflicts) > 5:
        conflict_names += f" (+{len(conflicts) - 5} more)"

    layout = popup_self.layout
    layout.label(text=f"{len(conflicts)} menu(s) already exist:", icon='ERROR')
    layout.label(text=conflict_names)
    layout.separator()
    # Safe/non-destructive option listed first, so an accidental click
    # never silently overwrites anything
    op = layout.operator("cocopie.resolve_preset_conflict", text="Keep existing, add only new", icon='ADD')
    op.mode = 'SKIP'
    op = layout.operator("cocopie.resolve_preset_conflict", text="Replace existing", icon='FILE_REFRESH')
    op.mode = 'REPLACE'
    op = layout.operator("cocopie.resolve_preset_conflict", text="Cancel", icon='X')
    op.mode = 'CANCEL'


def _deferred_show_preset_conflict_popup():
    """Runs on the next event-loop tick. Calling popup_menu() directly inside
    execute() of an operator that was just invoked via the file browser (a modal
    operation) gets silently swallowed by Blender in the same event, so we defer
    it with a zero-delay timer instead — this reliably shows the popup.

    The Preferences editor is its own floating OS window, so we also need to
    explicitly target that window with temp_override — otherwise the popup can
    render into whichever window last had focus (e.g. the main viewport),
    landing it behind the Preferences window instead of in front of it."""
    try:
        wm = bpy.context.window_manager
        target_window = _pending_preset_data.get("window")

        if target_window is not None and target_window in wm.windows[:]:
            with bpy.context.temp_override(window=target_window):
                wm.popup_menu(
                    _draw_preset_conflict_popup,
                    title="Duplicate Pie Menus Found",
                    icon='QUESTION',
                )
        else:
            # Fallback: window may have closed, just use whatever's current
            wm.popup_menu(
                _draw_preset_conflict_popup,
                title="Duplicate Pie Menus Found",
                icon='QUESTION',
            )
    except Exception as e:
        print(f"CocoPie: failed to show conflict popup: {e}")
    return None  # don't repeat the timer
