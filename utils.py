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
    GRID_CELL_UNITS, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
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


def oskey_label():
    """What Blender itself calls the OS-key modifier on this platform"""
    if sys.platform == "darwin":
        return "Cmd"
    if sys.platform == "win32":
        return "Win"
    return "OS"


def format_shortcut(pie):
    """Human-readable shortcut, e.g. 'Ctrl + Shift + Q'"""
    parts = []
    if pie.any_modifier:
        # Passing any=True makes Blender itself force shift/ctrl/alt/oskey to
        # -1 (verified against a live KeyMapItem) -- whatever those toggles
        # show becomes moot once Any is on, so the label should not claim they
        # still apply
        parts.append("Any")
    else:
        if pie.shift:
            parts.append("Shift")
        if pie.ctrl:
            parts.append("Ctrl")
        if pie.alt:
            parts.append("Alt")
        if pie.oskey:
            parts.append(oskey_label())
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

        # Any modifier held on either side matches every modifier state on
        # the other, since that is what Blender itself does once any=True is
        # passed to keymap_items.new() -- it forces shift/ctrl/alt/oskey to
        # -1 regardless of what those toggles show, so the specific states
        # are not meaningful to compare while either pie has Any set
        if pie.any_modifier or other.any_modifier:
            modifiers_match = True
        else:
            modifiers_match = (other.ctrl == pie.ctrl
                               and other.shift == pie.shift
                               and other.alt == pie.alt
                               and other.oskey == pie.oskey)

        if (other.key.upper() == pie.key.upper()
                and modifiers_match
                and other.event_value == pie.event_value
                and _keymaps_overlap(other.keymap_type, pie.keymap_type)):
            conflicts.append(other.name)
    return conflicts


def ensure_slot_items(pie):
    """Give the pie exactly one item per slot, ordered 0..7.

    A pie has eight directions and always did; the editor now shows them as
    eight fixed rows, so the stored items are made to match one-to-one. Items
    are only added and reordered, never dropped -- if two ever claimed the same
    slot, the later one is moved to the first free slot rather than discarded.

    Idempotent, so it is safe to call on every draw.
    """
    if len(pie.items) == 8 and all(item.position == i for i, item in enumerate(pie.items)):
        return

    claimed = {}
    homeless = []
    for item in pie.items:
        if 0 <= item.position <= 7 and item.position not in claimed:
            claimed[item.position] = item
        else:
            homeless.append(item)

    for position in range(8):
        if position not in claimed and homeless:
            claimed[position] = homeless.pop(0)

    # Snapshot, because the collection is about to be rebuilt underneath us
    snapshot = {
        position: {
            "label": item.label, "command": item.command,
            "icon": item.icon, "enabled": item.enabled,
        }
        for position, item in claimed.items()
    }

    pie.items.clear()
    for position in range(8):
        item = pie.items.add()
        item.position = position
        stored = snapshot.get(position)
        if stored:
            item.label = stored["label"]
            item.command = stored["command"]
            item.icon = stored["icon"]
            item.enabled = stored["enabled"]
        else:
            # An unused direction: present in the table, absent from the pie
            item.label = ""
            item.command = ""
            item.icon = 'NONE'
            item.enabled = True


def slot_is_used(item):
    """An item fills its slot once it has something to run or something to say"""
    return bool(item.command.strip() or item.label.strip())


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
