"""Saving and loading preset files."""

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
)
from ..keymaps import register_pie_menus, unregister_pie_menus
from ..presets import (
    _apply_pie_dict, _merge_preset_menus, _pending_preset_data,
    _draw_preset_conflict_popup, _deferred_show_preset_conflict_popup,
)


class COCOPIE_OT_save_preset(Operator):
    """Save pie menus to a preset file"""
    bl_idname = "cocopie.save_preset"
    bl_label = "Save Preset"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(subtype='FILE_PATH', default="pie_menus.json")
    filename: StringProperty(default="pie_menus.json")
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            # Convert to dictionary
            data = {"pie_menus": []}
            
            for pie in prefs.pie_menus:
                pie_dict = {
                    "name": pie.name,
                    "idname": pie.idname,
                    "keymap_type": pie.keymap_type,
                    "key": pie.key,
                    "ctrl": pie.ctrl,
                    "shift": pie.shift,
                    "alt": pie.alt,
                    "enabled": pie.enabled,
                    "items": []
                }
                
                for item in pie.items:
                    item_dict = {
                        "label": item.label,
                        "command": item.command,
                        "icon": item.icon,
                        "enabled": item.enabled,
                        "position": item.position
                    }
                    pie_dict["items"].append(item_dict)
                
                data["pie_menus"].append(pie_dict)
            
            # Save to file
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.report({'INFO'}, f"Saved preset to {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save: {str(e)}")
        
        return {'FINISHED'}



class COCOPIE_OT_resolve_preset_conflict(Operator):
    """Resolve how to handle pie menus whose name already exists"""
    bl_idname = "cocopie.resolve_preset_conflict"
    bl_label = "Resolve Preset Conflict"
    bl_options = {'REGISTER', 'INTERNAL'}

    mode: EnumProperty(
        items=[
            ('REPLACE', "Replace", "Overwrite existing menus with the ones from the file"),
            ('SKIP', "Keep Existing", "Keep existing menus, only add the new ones"),
            ('CANCEL', "Cancel", "Cancel the load, don't change anything"),
        ],
        default='SKIP',
    )

    def execute(self, context):
        # Mutated in place rather than rebound: presets.py owns this dict and a
        # rebinding here would leave that module still holding the old one

        if self.mode == 'CANCEL':
            _pending_preset_data.update({"pie_menus": [], "conflicts": [], "window": None})
            self.report({'INFO'}, "Load cancelled")
            return {'CANCELLED'}

        prefs = context.preferences.addons[ADDON_ID].preferences
        incoming = _pending_preset_data.get("pie_menus", [])
        added, replaced = _merge_preset_menus(prefs, incoming, mode=self.mode)

        msg = f"Added {added} new pie menu(s)"
        if replaced:
            msg += f", replaced {replaced} existing"
        self.report({'INFO'}, msg)

        _pending_preset_data.update({"pie_menus": [], "conflicts": [], "window": None})
        return {'FINISHED'}


class COCOPIE_OT_load_preset(Operator):
    """Load pie menus from a preset file — merges into existing menus instead of replacing them"""
    bl_idname = "cocopie.load_preset"
    bl_label = "Load Preset"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(subtype='FILE_PATH')
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        # Mutated in place rather than rebound: presets.py owns this dict and a
        # rebinding here would leave that module still holding the old one
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences

            with open(self.filepath, 'r') as f:
                data = json.load(f)

            incoming = data.get("pie_menus", [])
            existing_names = {pie.name for pie in prefs.pie_menus}
            conflicts = [
                pd.get("name", "Pie Menu") for pd in incoming
                if pd.get("name", "Pie Menu") in existing_names
            ]

            if not conflicts:
                # Nothing overlaps — just add every menu from the file
                added, _ = _merge_preset_menus(prefs, incoming, mode='SKIP')
                self.report({'INFO'}, f"Added {added} new pie menu(s)")
                return {'FINISHED'}

            # Some names already exist — defer the choice popup to the next
            # tick so it isn't swallowed by the file browser's modal teardown,
            # and remember which window (e.g. the Preferences window) to show it in
            _pending_preset_data.update({
                "pie_menus": incoming,
                "conflicts": conflicts,
                "window": context.window,
            })
            bpy.app.timers.register(_deferred_show_preset_conflict_popup, first_interval=0.35)

        except Exception as e:
            self.report({'ERROR'}, f"Failed to load: {str(e)}")
        
        return {'FINISHED'}
