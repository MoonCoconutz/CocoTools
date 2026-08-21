"""Small shared helpers: locating the preferences, describing shortcuts,
and working out which pies would collide."""

import bpy
import sys
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

# The key this addon is registered under, and the key its preferences are
# stored against. Taken from the package rather than __name__, which inside a
# submodule would be "CocoPie.utils" and match no registered addon.
ADDON_ID = __package__


def addon_version_string():
    """The addon's version as "v1.8.0", read from bl_info when it is needed.

    bl_info lives in the package __init__, which imports this module -- so it
    cannot be imported from here. Looking it up at call time sidesteps that:
    by the time anything draws, the package is fully loaded.
    """
    module = sys.modules.get(ADDON_ID)
    info = getattr(module, "bl_info", None) if module else None
    version = info.get("version") if info else None
    return "v" + ".".join(str(v) for v in version) if version else ""


def get_prefs(context=None):
    """Return the addon preferences, or None if the addon isn't registered yet"""
    try:
        return (context or bpy.context).preferences.addons[ADDON_ID].preferences
    except (KeyError, AttributeError):
        return None


def get_pie(context, pie_index):
    """Return the pie menu at pie_index, or None if it's gone"""
    prefs = get_prefs(context)
    if prefs and 0 <= pie_index < len(prefs.pie_menus):
        return prefs.pie_menus[pie_index]
    return None


def get_pie_item(context, pie_index, item_index):
    """Return the item at item_index inside pie_index, or None if it's gone"""
    pie = get_pie(context, pie_index)
    if pie and 0 <= item_index < len(pie.items):
        return pie.items[item_index]
    return None


def format_shortcut(pie):
    """Human-readable shortcut, e.g. 'Ctrl + Shift + Q'"""
    parts = []
    if pie.ctrl:
        parts.append("Ctrl")
    if pie.shift:
        parts.append("Shift")
    if pie.alt:
        parts.append("Alt")
    parts.append(pie.key or "?")
    return " + ".join(parts)

def keymap_names_for(keymap_type):
    """The keymap names a pie with this scope actually ends up registered in"""
    if keymap_type == 'WINDOW':
        return set(WINDOW_MODE_KEYMAPS)
    name, _space = KEYMAP_CONFIG.get(keymap_type, ('Window', 'EMPTY'))
    return {name}


def _keymaps_overlap(a, b):
    """Two pie menus can only collide if they land in a keymap they share.

    Compared by the keymaps they actually register into rather than by scope
    name, so a global pie no longer reports a conflict against one scoped to an
    editor it never reaches.
    """
    return bool(keymap_names_for(a) & keymap_names_for(b))


def find_shortcut_conflicts(prefs, pie, index):
    """Names of other *enabled* pie menus that would fight over the same shortcut"""
    if not pie.enabled:
        return []

    conflicts = []
    for i, other in enumerate(prefs.pie_menus):
        if i == index or not other.enabled:
            continue
        if (other.key.upper() == pie.key.upper()
                and other.ctrl == pie.ctrl
                and other.shift == pie.shift
                and other.alt == pie.alt
                and other.event_value == pie.event_value
                and _keymaps_overlap(other.keymap_type, pie.keymap_type)):
            conflicts.append(other.name)
    return conflicts


def find_duplicate_positions(pie):
    """Set of slots claimed by more than one item — the later one wins in the pie"""
    seen = set()
    dupes = set()
    for item in pie.items:
        if item.position in seen:
            dupes.add(item.position)
        seen.add(item.position)
    return dupes

# Flip to True to trace menu and keymap registration in the system console.
# Registration is rebuilt from scratch on every change to a pie's settings, so
# leaving this on floods the console while typing — roughly ten lines per
# keystroke with a handful of pies configured.
DEBUG = False


def _debug(message):
    """Print registration tracing, but only when DEBUG is on"""
    if DEBUG:
        print(f"CocoPie: {message}")
