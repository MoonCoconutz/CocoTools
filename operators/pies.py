"""Operators for creating pies and arranging the items inside them."""

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
    ensure_slot_items, slot_is_used,
)
from ..icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from ..menus import execute_script, create_pie_menu_class
from ..keymaps import register_pie_menus, unregister_pie_menus
from ..previews import slot_button_args


class COCOPIE_OT_execute_command(Operator):
    """Execute a Python command"""
    bl_idname = "cocopie.execute_command"
    bl_label = "Execute Command"
    bl_options = {'INTERNAL'}
    
    command: StringProperty()
    
    def execute(self, context):
        if not self.command:
            return {'CANCELLED'}
        
        try:
            exec(self.command, {"bpy": bpy, "context": context, "execute_script": execute_script})
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Command failed: {str(e)}")
            return {'CANCELLED'}


class COCOPIE_OT_select_pie(Operator):
    """Select a pie menu for editing"""
    bl_idname = "cocopie.select_pie"
    bl_label = "Select Pie Menu"
    bl_options = {'INTERNAL'}
    
    index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            prefs.active_pie_index = self.index
        except Exception as e:
            self.report({'ERROR'}, f"Failed to select: {str(e)}")
        return {'FINISHED'}


class COCOPIE_OT_add_pie_menu(Operator):
    """Add a new pie menu"""
    bl_idname = "cocopie.add_pie_menu"
    bl_label = "Add Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            # Create new pie menu
            new_pie = prefs.pie_menus.add()
            count = len(prefs.pie_menus)
            new_pie.name = f"Pie Menu {count}"
            new_pie.idname = f"COCOPIE_MT_custom_pie_{count}"
            
            # Add default item
            item = new_pie.items.add()
            item.label = "Example Item"
            item.command = "bpy.ops.mesh.primitive_cube_add()"
            item.icon = "MESH_CUBE"
            item.position = 0
            
            prefs.active_pie_index = len(prefs.pie_menus) - 1
            
            # Register the new menu
            register_pie_menus()
            
            self.report({'INFO'}, f"Created {new_pie.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to add pie menu: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return {'FINISHED'}


class COCOPIE_OT_remove_pie_menu(Operator):
    """Remove the selected pie menu"""
    bl_idname = "cocopie.remove_pie_menu"
    bl_label = "Remove Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.index < len(prefs.pie_menus):
                # Unregister before removing
                unregister_pie_menus()
                
                prefs.pie_menus.remove(self.index)
                prefs.active_pie_index = max(0, min(prefs.active_pie_index, len(prefs.pie_menus) - 1))
                
                # Re-register remaining menus
                register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove: {str(e)}")
        
        return {'FINISHED'}


class COCOPIE_OT_duplicate_pie_menu(Operator):
    """Duplicate the selected pie menu"""
    bl_idname = "cocopie.duplicate_pie_menu"
    bl_label = "Duplicate Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.index < len(prefs.pie_menus):
                source = prefs.pie_menus[self.index]
                
                # Unregister before modifying
                unregister_pie_menus()
                
                # Create duplicate
                new_pie = prefs.pie_menus.add()
                new_pie.name = f"{source.name} Copy"
                new_pie.idname = f"{source.idname}_copy"
                new_pie.keymap_type = source.keymap_type
                new_pie.key = source.key
                new_pie.ctrl = source.ctrl
                new_pie.shift = source.shift
                new_pie.alt = source.alt
                new_pie.enabled = False
                
                # Copy items
                for item in source.items:
                    new_item = new_pie.items.add()
                    new_item.label = item.label
                    new_item.command = item.command
                    new_item.icon = item.icon
                    new_item.enabled = item.enabled
                    new_item.position = item.position
                
                # Re-register
                register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to duplicate: {str(e)}")
        
        return {'FINISHED'}


class COCOPIE_OT_remove_item(Operator):
    """Clear this direction, leaving the slot empty"""
    bl_idname = "cocopie.remove_item"
    bl_label = "Clear Direction"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()
    item_index: IntProperty()

    def execute(self, context):
        try:
            pie = get_pie(context, self.pie_index)
            if not pie or not (0 <= self.item_index < len(pie.items)):
                return {'CANCELLED'}

            # Emptied rather than removed. The eight directions are fixed, so
            # dropping the row would shift every direction below it up one.
            item = pie.items[self.item_index]
            item.label = ""
            item.command = ""
            item.icon = 'NONE'
            item.enabled = True

            register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear direction: {str(e)}")

        return {'FINISHED'}


class COCOPIE_OT_move_pie_menu(Operator):
    """Move this pie menu up or down the list.

    Ordering here is cosmetic -- it changes nothing about shortcuts or
    registration, only the order the menus are listed in"""
    bl_idname = "cocopie.move_pie_menu"
    bl_label = "Move Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}

    direction: EnumProperty(
        items=[('UP', 'Up', ''), ('DOWN', 'Down', '')]
    )

    @classmethod
    def poll(cls, context):
        # Greyed out at the end it cannot travel any further towards
        prefs = get_prefs(context)
        if not prefs or len(prefs.pie_menus) < 2:
            return False
        return True

    def execute(self, context):
        try:
            prefs = get_prefs(context)
            if not prefs:
                return {'CANCELLED'}

            index = prefs.active_pie_index
            new_index = index + (-1 if self.direction == 'UP' else 1)

            if not (0 <= index < len(prefs.pie_menus)) or not (0 <= new_index < len(prefs.pie_menus)):
                return {'CANCELLED'}

            prefs.pie_menus.move(index, new_index)
            # Keep the selection on the menu that moved, not on the row index
            prefs.active_pie_index = new_index
        except Exception as e:
            self.report({'ERROR'}, f"Failed to move pie menu: {str(e)}")

        return {'FINISHED'}

