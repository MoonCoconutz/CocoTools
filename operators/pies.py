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
    GRID_CELL_SCALE_Y, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from ..utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
)
from ..icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from ..menus import execute_script, create_pie_menu_class
from ..keymaps import register_pie_menus, unregister_pie_menus


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


class COCOPIE_OT_set_item_position(Operator):
    """Set the position of a menu item"""
    bl_idname = "cocopie.set_item_position"
    bl_label = "Set Position"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()
    item_index: IntProperty()
    position: IntProperty()

    @classmethod
    def description(cls, context, properties):
        pie = get_pie(context, properties.pie_index)
        if pie:
            for i, other in enumerate(pie.items):
                if i != properties.item_index and other.position == properties.position:
                    return f"Swap with \"{other.label or 'Item'}\""
        return f"Move this item to the {POSITION_NAMES.get(properties.position, 'chosen')} slot"

    def execute(self, context):
        try:
            pie = get_pie(context, self.pie_index)
            if not pie or not (0 <= self.item_index < len(pie.items)):
                return {'CANCELLED'}

            item = pie.items[self.item_index]
            old_position = item.position

            # If another item already sits in the target slot, swap the two.
            # Two items sharing a slot means one silently overwrites the other
            # when the pie is drawn, so never let a move create that.
            for i, other in enumerate(pie.items):
                if i != self.item_index and other.position == self.position:
                    other.position = old_position
                    break

            item.position = self.position
            register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to set position: {str(e)}")

        return {'FINISHED'}


class COCOPIE_OT_show_position_menu(Operator):
    """Show position selection menu"""
    bl_idname = "cocopie.show_position_menu"
    bl_label = "Choose Position"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()
    item_index: IntProperty()

    @classmethod
    def description(cls, context, properties):
        item = get_pie_item(context, properties.pie_index, properties.item_index)
        if item:
            return (f"Slot: {POSITION_NAMES.get(item.position, '?')}.\n"
                    "Click to move this item to another pie direction")
        return "Choose which pie direction this item sits in"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        # wm.popup_menu() auto-sizes to content and ignores ui_units_x once
        # the row content is mixed (icon buttons + text), which is what made
        # this grid render lopsided. invoke_popup() takes a real pixel width
        # and is the API Blender itself uses for fixed-size custom popups.
        return context.window_manager.invoke_popup(self, width=GRID_POPUP_WIDTH)

    def draw(self, context):
        layout = self.layout

        pie = get_pie(context, self.pie_index)
        item = get_pie_item(context, self.pie_index, self.item_index)

        if not pie or not item:
            layout.label(text="That item no longer exists", icon='ERROR')
            return

        # Which slots are spoken for by *other* items
        occupied = {}
        for i, other in enumerate(pie.items):
            if i != self.item_index:
                occupied.setdefault(other.position, other)

        # A bare compass: nothing but arrows, divided into cells by separator
        # lines. There is no header or caption — every cell explains itself on
        # hover, and the arrows plus their placement carry the rest.
        #
        # Built from plain rows rather than grid_flow: every cell holds a
        # single arrow glyph and nothing else, so Blender divides the row
        # width evenly on its own — grid_flow's "even_columns" turned out not
        # to be reliable inside a popup once one cell held different content.
        #
        # Text-only cells matter for more than tidiness: an icon-only button
        # collapses to the icon's width instead of filling its share of the
        # row, which is what squashed this grid into the left third of the
        # popup back when the buttons carried icons.
        # Only the row separators are drawn. A LINE separator inside a *row*
        # does not render as a full-height column divider — Blender degrades it
        # to a short dash at the cell boundary — so the vertical ones are left
        # out rather than shipping those stray marks.
        col = layout.column(align=True)
        for row_index, row_positions in enumerate(
                (POSITION_GRID[0:3], POSITION_GRID[3:6], POSITION_GRID[6:9])):
            if row_index:
                col.separator(type='LINE')

            row = col.row(align=True)
            for pos in row_positions:
                cell = row.row(align=True)
                cell.scale_y = GRID_CELL_SCALE_Y

                # Centre of the grid is inert: it shows the icon of the item
                # being moved, so the compass has its subject at its middle
                if pos is None:
                    cell.enabled = False
                    cell.alignment = 'CENTER'
                    cell.label(text="", icon=safe_icon(item.icon))
                    continue

                taken = occupied.get(pos)
                is_current = pos == item.position

                # Dim occupied slots, but keep them clickable — landing on
                # one swaps the two items rather than being refused
                cell.active = is_current or taken is None

                # Arrows draw flat, with no button chrome, so the grid reads
                # as glyphs on a ground rather than a wall of buttons. The one
                # exception is the slot the item already sits in: it keeps its
                # frame so "you are here" survives having no caption to say so.
                op = cell.operator(
                    "cocopie.set_item_position",
                    text=POSITION_ARROWS[pos],
                    emboss=is_current,
                    depress=is_current,
                )
                op.pie_index = self.pie_index
                op.item_index = self.item_index
                op.position = pos


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


class COCOPIE_OT_add_item(Operator):
    """Add a new item to the pie menu"""
    bl_idname = "cocopie.add_item"
    bl_label = "Add Item"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    pie_index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.pie_index < len(prefs.pie_menus):
                pie = prefs.pie_menus[self.pie_index]
                
                item = pie.items.add()
                item.label = f"Item {len(pie.items)}"

                # Drop it into the first free slot rather than the next index,
                # so a new item never lands on top of an existing one
                used = {it.position for it in pie.items[:-1]}
                for pos in range(8):
                    if pos not in used:
                        item.position = pos
                        break

                pie.active_item_index = len(pie.items) - 1
                
                # Re-register to update the menu
                register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to add item: {str(e)}")
        
        return {'FINISHED'}


class COCOPIE_OT_remove_item(Operator):
    """Remove the item from the pie menu"""
    bl_idname = "cocopie.remove_item"
    bl_label = "Remove Item"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    pie_index: IntProperty()
    item_index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.pie_index < len(prefs.pie_menus):
                pie = prefs.pie_menus[self.pie_index]
                
                if 0 <= self.item_index < len(pie.items):
                    pie.items.remove(self.item_index)
                    pie.active_item_index = max(0, pie.active_item_index - 1)
                    
                    # Re-register to update the menu
                    register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove item: {str(e)}")
        
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


class COCOPIE_OT_move_item(Operator):
    """Move item up or down"""
    bl_idname = "cocopie.move_item"
    bl_label = "Move Item"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    pie_index: IntProperty()
    item_index: IntProperty()
    direction: EnumProperty(
        items=[('UP', 'Up', ''), ('DOWN', 'Down', '')]
    )
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.pie_index < len(prefs.pie_menus):
                pie = prefs.pie_menus[self.pie_index]
                
                new_index = self.item_index + (-1 if self.direction == 'UP' else 1)
                
                if 0 <= new_index < len(pie.items):
                    pie.items.move(self.item_index, new_index)
                    pie.active_item_index = new_index
        except Exception as e:
            self.report({'ERROR'}, f"Failed to move item: {str(e)}")
        
        return {'FINISHED'}
