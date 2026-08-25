"""Registering the pie menu classes and their keyboard shortcuts."""

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
    GRID_CELL_UNITS, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
    COCOPIE_KEYMAP_IDNAMES, invalidate_external_shortcut_index,
    pie_scope_types,
)
from .menus import execute_script, create_pie_menu_class


registered_pie_classes = []
registered_keymaps = []


# A key like "0" is stored as-is, but Blender's key identifiers spell number
# keys out ("ZERO".."NINE"); resolving it once here keeps register_pie_menus
# and the tap/hold keymap item in agreement about what event.type to expect.
_KEY_NAME_MAPPING = {
    '0': 'ZERO', '1': 'ONE', '2': 'TWO', '3': 'THREE', '4': 'FOUR',
    '5': 'FIVE', '6': 'SIX', '7': 'SEVEN', '8': 'EIGHT', '9': 'NINE',
}


def _resolve_key(key):
    return _KEY_NAME_MAPPING.get(key, key)


def _add_keymap_item(km, key, pie_data, pie_index):
    """The pie's own keymap item -- unchanged behaviour when Tap to Toggle
    is off. cocopie.hold_or_tap replaces this entirely when it is on: a
    keyboard key has no native "held vs tapped" event value (CLICK_DRAG
    needs the mouse to actually move, RELEASE fires the same regardless of
    hold duration), so that distinction is timed by hand instead -- see
    COCOPIE_OT_hold_or_tap. Bound on PRESS either way, since the modal makes
    the pie's own Trigger setting moot once it is driving things."""
    if pie_data.tap_toggle:
        kmi = km.keymap_items.new(
            'cocopie.hold_or_tap',
            key,
            'PRESS',
            any=pie_data.any_modifier,
            shift=pie_data.shift,
            ctrl=pie_data.ctrl,
            alt=pie_data.alt,
            oskey=pie_data.oskey,
        )
        kmi.properties.pie_index = pie_index
        kmi.properties.key = key
    else:
        kmi = km.keymap_items.new(
            'wm.call_menu_pie',
            key,
            pie_data.event_value,
            any=pie_data.any_modifier,
            shift=pie_data.shift,
            ctrl=pie_data.ctrl,
            alt=pie_data.alt,
            oskey=pie_data.oskey,
        )
        kmi.properties.name = pie_data.idname
    return (km, kmi)


def register_pie_menus():
    """Register all pie menus and their keymaps"""
    global registered_pie_classes, registered_keymaps

    unregister_pie_menus()

    # Everyone else's shortcuts are cached for the conflict warning; a
    # re-register is the one moment we know the keyconfig has just churned,
    # and is also when another addon has most likely been toggled behind us.
    invalidate_external_shortcut_index()

    try:
        prefs = bpy.context.preferences.addons[ADDON_ID].preferences
    except:
        return
    
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    
    if not kc:
        print("CocoPie: No addon keyconfig found")
        return
    
    for pie_index, pie_data in enumerate(prefs.pie_menus):
        if not pie_data.enabled:
            continue
        
        menu_class = create_pie_menu_class(pie_data)
        
        try:
            bpy.utils.register_class(menu_class)
            registered_pie_classes.append(menu_class)
            _debug(f"Registered menu class: {pie_data.idname}")
            
            key = _resolve_key(pie_data.key)

            # A pie can be scoped to several editors at once, so this walks
            # every scope and collects the (keymap name, space type) pairs
            # first. Deduplicated before anything is created: scopes overlap
            # freely -- "Window (Global)" already covers Mesh, so picking both
            # names the same keymap twice -- and keymap_items.new() appends
            # rather than replacing, which would leave the pie bound twice on
            # one key and firing twice per press.
            targets = []
            for scope_type in pie_scope_types(pie_data):
                # KEYMAP_CONFIG is shared with the scope dropdown and the
                # conflict check so the three cannot disagree
                keymap_name, space_type = KEYMAP_CONFIG.get(
                    scope_type, ('Window', 'EMPTY'))
                if scope_type == 'WINDOW':
                    # "Window (Global)" is not one keymap -- it is every 3D
                    # viewport mode keymap
                    for km_name in WINDOW_MODE_KEYMAPS:
                        if (km_name, 'EMPTY') not in targets:
                            targets.append((km_name, 'EMPTY'))
                elif (keymap_name, space_type) not in targets:
                    targets.append((keymap_name, space_type))

            for km_name, space_type in targets:
                try:
                    km = kc.keymaps.new(name=km_name, space_type=space_type)
                    registered_keymaps.append(
                        _add_keymap_item(km, key, pie_data, pie_index))
                except Exception as e:
                    print(f"CocoPie: Could not register keymap for {km_name}: {e}")

            _debug(f"Registered keymap: {format_shortcut(pie_data)} in "
                  f"{[n for n, _s in targets]} for {pie_data.idname}")
        
        except Exception as e:
            print(f"CocoPie: Error registering pie menu {pie_data.idname}: {e}")
            import traceback
            traceback.print_exc()


def unregister_pie_menus():
    """Unregister all pie menus and keymaps.

    Sweeps every keymap CocoPie could have touched for any wm.call_menu_pie
    item that points at one of our menus, or any cocopie.hold_or_tap item
    (Tap to Toggle's keymap item, which would orphan exactly the same way if
    left out of this sweep), rather than trusting only
    registered_keymaps. That list lives at module level, so it is empty again
    every time this module gets freshly re-imported -- which happens on a
    disable/enable cycle that does not reuse the cached module, and on
    Blender's own "Reload Scripts". A fresh-but-empty list makes this function
    believe there is nothing to remove, when a *previous* import may have left
    real keymap items behind. keymap_items.new() always appends; it never
    replaces an existing match, so those orphans do not go away on their own
    -- they keep firing under whatever Trigger and modifiers they were
    created with, stacked underneath whatever the pie is set to now. That is
    what made changing the Trigger look like it was not doing anything: an
    old PRESS entry from an earlier reload was still there, alongside the new
    one, both matching the same key.
    """
    global registered_pie_classes, registered_keymaps

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        target_names = {name for name, _space in KEYMAP_CONFIG.values()} | set(WINDOW_MODE_KEYMAPS)
        for km in list(kc.keymaps):
            if km.name not in target_names:
                continue
            stale = [kmi for kmi in km.keymap_items
                    if (kmi.idname == 'wm.call_menu_pie'
                        and kmi.properties.name.startswith('COCOPIE_MT_'))
                    or kmi.idname in COCOPIE_KEYMAP_IDNAMES]
            for kmi in stale:
                try:
                    km.keymap_items.remove(kmi)
                except Exception:
                    pass

    # Still drained for cleanliness; the sweep above is what actually
    # guarantees nothing real is left behind
    for km, kmi in registered_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    registered_keymaps.clear()

    for cls in registered_pie_classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    registered_pie_classes.clear()
