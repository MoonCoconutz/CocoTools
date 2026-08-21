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
    GRID_CELL_SCALE_Y, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
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
                            ctrl=pie_data.ctrl,
                            shift=pie_data.shift,
                            alt=pie_data.alt
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
                    ctrl=pie_data.ctrl,
                    shift=pie_data.shift,
                    alt=pie_data.alt
                )
                kmi.properties.name = pie_data.idname
                registered_keymaps.append((km, kmi))
            
            keymap_str = ""
            if pie_data.ctrl: keymap_str += "Ctrl+"
            if pie_data.shift: keymap_str += "Shift+"
            if pie_data.alt: keymap_str += "Alt+"
            keymap_str += pie_data.key
            _debug(f"Registered keymap: {keymap_str} in '{keymap_name}' for {pie_data.idname}")
        
        except Exception as e:
            print(f"CocoPie: Error registering pie menu {pie_data.idname}: {e}")
            import traceback
            traceback.print_exc()


def unregister_pie_menus():
    """Unregister all pie menus and keymaps"""
    global registered_pie_classes, registered_keymaps
    
    for km, kmi in registered_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except:
            pass
    registered_keymaps.clear()
    
    for cls in registered_pie_classes:
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
    registered_pie_classes.clear()
