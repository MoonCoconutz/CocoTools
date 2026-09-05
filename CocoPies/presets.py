"""Reading preset dictionaries back into pie menus, and resolving name
collisions when a preset overlaps what is already configured."""

import bpy
import os
import json
import re
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
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
    ensure_slot_items, slot_is_used,
)
from .keymaps import register_pie_menus, unregister_pie_menus


# Carries a preset across the gap between loading the file and asking what to
# do about name collisions. This module owns it: everything else mutates it in
# place, because rebinding the name elsewhere would leave this module -- which
# is what draws the popup -- still looking at the old dict.
_pending_preset_data = {"pie_menus": [], "conflicts": [], "window": None}

# Trailing keyword arguments are optional and preserved verbatim: a slot
# may say execute_script("...", axis='X'), and rewriting only the path must
# not drop what comes after it.
_EXECUTE_SCRIPT_RE = re.compile(
    r"""^execute_script\((["'])(.*?)\1\s*(,\s*.*?)?\)$""", re.DOTALL)


def _repoint_missing_bundled_script(command):
    """If `command` is execute_script("<path>") and that path no longer
    exists, but a bundled script with the same filename exists at the addon's
    current install location, repoint it there.

    Without this, a preset saved before a reinstall that moved the addon's
    folder (e.g. legacy add-on -> extension, or just a new machine) would
    load starter-pie commands still pointing at the old location -- the
    slot would look configured but silently fail. Only touches commands
    whose path is actually missing, and only when a same-named bundled
    script is found, so a command that already resolves fine, or one
    pointing at a user's own script elsewhere, is never rewritten.
    """
    match = _EXECUTE_SCRIPT_RE.match(command.strip())
    if not match:
        return command
    old_path = match.group(2)
    if os.path.exists(old_path):
        return command
    # Deferred import: defaults.py imports from this module at load time, so
    # importing it back at module level here would be circular.
    from .defaults import bundled_scripts_root
    # Searched across the whole scripts/ tree, not just the workspace folder it
    # started in. Bundled scripts now live in per-feature subfolders
    # (scripts/delete, scripts/flatten), and looking only in one of them meant
    # the others were quietly unrepointable -- the exact silent failure this
    # function exists to prevent.
    candidate = None
    wanted = os.path.basename(old_path)
    for folder, _dirs, files in os.walk(bundled_scripts_root()):
        if wanted in files:
            candidate = os.path.join(folder, wanted)
            break
    if candidate is None:
        return command
    fixed = candidate.replace("\\", "/")
    extra = match.group(3) or ""
    print(f"CocoPies: repointed missing bundled script {old_path!r} -> {fixed!r}")
    return 'execute_script("%s"%s)' % (fixed, extra)


def _apply_pie_dict(pie, pie_dict):
    """Copy a preset dict's fields onto an existing/new COCOPIE_PieMenuData item"""
    # A "label" key in older presets is ignored -- that field no longer exists
    pie.idname = pie_dict.get("idname", "COCOPIE_MT_custom_pie")
    pie.keymap_type = pie_dict.get("keymap_type", "WINDOW")
    # Multi-scope pies carry the full list; a preset from before that existed
    # has only keymap_type, and is migrated by ensure_keymap_scopes() the
    # first time anything reads the scopes. Unknown scope values are dropped
    # rather than raising -- a hand-edited or newer-version preset should not
    # take the whole import down with it.
    pie.keymap_scopes.clear()
    for scope_type in pie_dict.get("keymap_scopes", []):
        try:
            pie.keymap_scopes.add().keymap_type = scope_type
        except TypeError:
            pie.keymap_scopes.remove(len(pie.keymap_scopes) - 1)
            print(f"CocoPies: preset names an unknown editor {scope_type!r}, skipped")
    pie.key = pie_dict.get("key", "Q")
    # any_modifier and oskey are absent from presets saved before this pair
    # existed; .get() defaults them to False, same as a freshly created pie
    pie.any_modifier = pie_dict.get("any_modifier", False)
    pie.shift = pie_dict.get("shift", False)
    pie.ctrl = pie_dict.get("ctrl", False)
    pie.alt = pie_dict.get("alt", False)
    # Not read back from the preset: a pie saved while the Win/Cmd toggle
    # existed would otherwise come back bound to a shortcut the OS eats
    pie.oskey = False
    pie.enabled = pie_dict.get("enabled", True)
    # Trigger before tap_toggle, never after: turning Tap to Toggle on forces
    # the Trigger to Drag (see _update_tap_toggle), so applying them the other
    # way round would let an inconsistent preset leave the pie claiming a
    # Trigger its own dispatch does not use.
    pie.event_value = pie_dict.get("event_value", "PRESS")
    # Absent from presets written before list menus existed; a pie is the
    # only thing those could have been.
    try:
        pie.menu_style = pie_dict.get("menu_style", "PIE")
    except TypeError:
        pie.menu_style = "PIE"
    pie.items.clear()
    for item_dict in pie_dict.get("items", []):
        item = pie.items.add()
        item.label = item_dict.get("label", "Item")
        item.command = _repoint_missing_bundled_script(item_dict.get("command", ""))
        item.icon = item_dict.get("icon", "NONE")
        item.enabled = item_dict.get("enabled", True)
        item.position = item_dict.get("position", 0)

    # After the items: the two direction pickers are dynamic enums built from
    # whatever currently sits in each slot, so they are only meaningful once
    # the slots are filled.
    pie.tap_toggle = pie_dict.get("tap_toggle", False)
    pie.tap_toggle_a = pie_dict.get("tap_toggle_a", "0")
    pie.tap_toggle_b = pie_dict.get("tap_toggle_b", "0")
    pie.tap_action = pie_dict.get("tap_action", 'TOGGLE')
    # Through the same repointer as an item's command: a tap command can be an
    # execute_script() call with an absolute path baked in, which is exactly
    # what does not survive being carried to another machine or install.
    pie.tap_command = _repoint_missing_bundled_script(
        pie_dict.get("tap_command", ""))


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
        print(f"CocoPies: failed to show conflict popup: {e}")
    return None  # don't repeat the timer
