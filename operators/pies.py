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
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS, KEYMAP_TYPE_ITEMS,
)
from ..utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
    ensure_slot_items, slot_is_used, ensure_keymap_scopes,
)
from ..icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from ..menus import execute_script, create_pie_menu_class
from ..keymaps import register_pie_menus, unregister_pie_menus
from ..previews import slot_button_args, icon_args


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


class COCOPIE_OT_tap_toggle_direction(Operator):
    """Quick-tap alternative to a Drag pie: run one of two chosen directions
    directly, alternating between them, without opening the pie at all"""
    bl_idname = "cocopie.tap_toggle_direction"
    bl_label = "Toggle Pie Direction"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    pie_index: IntProperty()

    def execute(self, context):
        pie = get_pie(context, self.pie_index)
        if pie is None:
            return {'CANCELLED'}

        try:
            pos_a, pos_b = int(pie.tap_toggle_a), int(pie.tap_toggle_b)
        except (TypeError, ValueError):
            return {'CANCELLED'}

        item_a = next((it for it in pie.items if it.position == pos_a), None)
        item_b = next((it for it in pie.items if it.position == pos_b), None)
        if item_a is None or item_b is None:
            return {'CANCELLED'}

        target = item_b if pie.tap_toggle_last_ran_a else item_a
        pie.tap_toggle_last_ran_a = not pie.tap_toggle_last_ran_a

        if not target.command:
            return {'CANCELLED'}
        try:
            exec(target.command, {"bpy": bpy, "context": context, "execute_script": execute_script})
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Command failed: {str(e)}")
            return {'CANCELLED'}


class COCOPIE_OT_hold_or_tap(Operator):
    """Bound to PRESS: opens the pie on a hold, runs the tap-toggle on a quick
    release. Keyboard keys have no native "held vs tapped" event value --
    CLICK_DRAG needs the mouse to actually move, and RELEASE fires the same
    way regardless of how long the key was down -- so this times it by hand."""
    bl_idname = "cocopie.hold_or_tap"
    bl_label = "Pie (Hold) / Toggle (Tap)"
    bl_options = {'INTERNAL'}

    pie_index: IntProperty()
    # The already Blender-mapped key identifier (e.g. "T", or "ZERO" for the
    # "0" key) -- matched against event.type, which uses the same names.
    key: StringProperty()

    HOLD_THRESHOLD = 0.2  # seconds

    _timer = None

    def modal(self, context, event):
        if event.type == self.key and event.value == 'RELEASE':
            self._cancel_timer(context)
            bpy.ops.cocopie.tap_toggle_direction(pie_index=self.pie_index)
            return {'FINISHED'}

        if event.type == 'TIMER':
            self._cancel_timer(context)
            pie = get_pie(context, self.pie_index)
            if pie is not None:
                # The pie's own modal takes it from here; this operator's job
                # -- deciding hold vs tap -- is done either way.
                bpy.ops.wm.call_menu_pie('INVOKE_DEFAULT', name=pie.idname)
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        wm = context.window_manager
        self._timer = wm.event_timer_add(self.HOLD_THRESHOLD, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _cancel_timer(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


class COCOPIE_OT_add_keymap_scope(Operator):
    """Register this pie in another editor as well"""
    bl_idname = "cocopie.add_keymap_scope"
    bl_label = "Add Editor"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()

    def execute(self, context):
        pie = get_pie(context, self.pie_index)
        if pie is None:
            return {'CANCELLED'}

        existing = ensure_keymap_scopes(pie)
        # Land on something the pie is not already scoped to, so the new row is
        # useful immediately instead of duplicating the row above it. The short
        # list is only a preference for the editors most pies want; it falls
        # through to every remaining scope rather than stopping there, because
        # stopping there is what produced runs of identical "Window (Global)"
        # rows once those few were all taken.
        taken = {scope.keymap_type for scope in existing}
        preferred = ('3D_VIEW', 'UV_EDITOR', 'IMAGE_EDITOR', 'NODE_EDITOR', 'WINDOW')
        rest = tuple(ident for ident, _label, _desc in KEYMAP_TYPE_ITEMS if ident)
        new_scope = existing.add()
        for candidate in preferred + rest:
            if candidate not in taken:
                new_scope.keymap_type = candidate
                break
        else:
            # Every scope CocoPie knows is already on this pie; nothing left to
            # add, so do not leave a duplicate row behind
            existing.remove(len(existing) - 1)
            self.report({'INFO'}, "This pie is already registered in every editor")
            return {'CANCELLED'}

        register_pie_menus()
        return {'FINISHED'}


class COCOPIE_OT_remove_keymap_scope(Operator):
    """Stop registering this pie in this editor"""
    bl_idname = "cocopie.remove_keymap_scope"
    bl_label = "Remove Editor"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()
    scope_index: IntProperty()

    def execute(self, context):
        pie = get_pie(context, self.pie_index)
        if pie is None:
            return {'CANCELLED'}

        # A pie with no scope at all would be registered nowhere and look
        # broken with no way back, so the last row is never removable -- the
        # UI hides its button too, this is the backstop
        if len(pie.keymap_scopes) <= 1:
            return {'CANCELLED'}
        if not (0 <= self.scope_index < len(pie.keymap_scopes)):
            return {'CANCELLED'}

        pie.keymap_scopes.remove(self.scope_index)
        register_pie_menus()
        return {'FINISHED'}


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
                # Every editor the source was live in, not just the legacy
                # single one -- otherwise a duplicate of a multi-scope pie
                # silently comes back scoped to one editor
                for scope in ensure_keymap_scopes(source):
                    new_pie.keymap_scopes.add().keymap_type = scope.keymap_type
                new_pie.key = source.key
                new_pie.any_modifier = source.any_modifier
                new_pie.shift = source.shift
                new_pie.ctrl = source.ctrl
                new_pie.alt = source.alt
                new_pie.oskey = source.oskey
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

