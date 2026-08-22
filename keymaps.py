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
)
from .menus import execute_script, create_pie_menu_class


registered_pie_classes = []
registered_keymaps = []


def register_pie_menus():
    """Register all pie menus and their keymaps"""
    global registered_pie_classes, registered_keymaps
    
    unregister_pie_menus()
    
    try:
        prefs = bpy.context.preferences.addons[ADDON_ID].preferences
    except:
        return
    
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    
    if not kc:
        print("CocoPie: No addon keyconfig found")
        return
    
    for pie_data in prefs.pie_menus:
        if not pie_data.enabled:
            continue
        
        menu_class = create_pie_menu_class(pie_data)
        
        try:
            bpy.utils.register_class(menu_class)
            registered_pie_classes.append(menu_class)
            _debug(f"Registered menu class: {pie_data.idname}")
            
            # Keymap registration -- KEYMAP_CONFIG is shared with the scope
            # dropdown and the conflict check so the three cannot disagree
            keymap_name, space_type = KEYMAP_CONFIG.get(
                pie_data.keymap_type, ('Window', 'EMPTY'))
            
            # Map common key names to Blender's key identifiers
            key = pie_data.key
            key_mapping = {
                '0': 'ZERO', '1': 'ONE', '2': 'TWO', '3': 'THREE', '4': 'FOUR',
                '5': 'FIVE', '6': 'SIX', '7': 'SEVEN', '8': 'EIGHT', '9': 'NINE',
            }
            
            # Convert number keys to their Blender names
            if key in key_mapping:
                key = key_mapping[key]
            
            # For Window (Global), register in all major 3D view modes
            if pie_data.keymap_type == 'WINDOW':
                for km_name in WINDOW_MODE_KEYMAPS:
                    try:
                        km = kc.keymaps.new(name=km_name, space_type='EMPTY')
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
                        registered_keymaps.append((km, kmi))
                    except Exception as e:
                        print(f"CocoPie: Could not register keymap for {km_name}: {e}")
            else:
                km = kc.keymaps.new(name=keymap_name, space_type=space_type)
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
                registered_keymaps.append((km, kmi))
            
            _debug(f"Registered keymap: {format_shortcut(pie_data)} in "
                  f"'{keymap_name}' for {pie_data.idname}")
        
        except Exception as e:
            print(f"CocoPie: Error registering pie menu {pie_data.idname}: {e}")
            import traceback
            traceback.print_exc()


def unregister_pie_menus():
    """Unregister all pie menus and keymaps.

    Sweeps every keymap CocoPie could have touched for any wm.call_menu_pie
    item that points at one of our menus, rather than trusting only
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
                    if kmi.idname == 'wm.call_menu_pie'
                    and kmi.properties.name.startswith('COCOPIE_MT_')]
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
