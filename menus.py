"""Builds the Blender Menu class that actually draws a pie."""

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
from .icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)


def execute_script(filepath):
    """Helper to run an external Python script from a pie menu command"""
    import os
    filepath = os.path.normpath(filepath)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Script not found: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        exec(f.read(), {"bpy": bpy})


def _resolve_bpy_data_path(path_str):
    """Resolve a dotted attribute path like 'bpy.context.space_data.overlay.show_edge_seams'
    into (data_object, prop_name). Returns None if it can't be safely resolved
    (e.g. it contains a function call, subscript, or isn't rooted at bpy)."""
    path_str = path_str.strip()
    parts = path_str.split(".")
    if len(parts) < 2 or parts[0] != "bpy":
        return None

    obj = bpy
    for part in parts[1:-1]:
        if not part.isidentifier():
            return None
        obj = getattr(obj, part, None)
        if obj is None:
            return None

    prop_name = parts[-1]
    if not prop_name.isidentifier() or not hasattr(obj, prop_name):
        return None

    return obj, prop_name


def create_pie_menu_class(pie_data):
    """Dynamically create a pie menu class"""
    
    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        
        # Create 8 slots (positions 0-7)
        slots = [None] * 8
        
        # Fill slots with enabled items
        for item in pie_data.items:
            if item.enabled and 0 <= item.position <= 7:
                slots[item.position] = item
        
        # Draw items in order
        for slot in slots:
            if slot:
                try:
                    icon = slot.icon if slot.icon and slot.icon != "NONE" else 'NONE'
                    command = slot.command
                    
                    # Check if this is a submenu call
                    if command and "wm.call_menu" in command and "name=" in command:
                        import re
                        match = re.search(r"name=['\"]([^'\"]+)['\"]", command)
                        if match:
                            menu_name = match.group(1)
                            pie.menu(menu_name, text=slot.label, icon=icon)
                        else:
                            op = pie.operator("cocopie.execute_command", text=slot.label, icon=icon)
                            op.command = command
                    
                    # Check if this is a property assignment (contains = but not ==, and not bpy.ops)
                    elif command and "=" in command and not command.startswith("bpy.ops.") and "==" not in command:
                        # Try to bind directly to the boolean property so the
                        # button reflects its live state (lit when True, like
                        # Blender's native overlay toggle buttons)
                        lhs = command.split("=")[0].strip()
                        resolved = _resolve_bpy_data_path(lhs)
                        bound = False
                        if resolved:
                            data_obj, prop_name = resolved
                            try:
                                current_val = getattr(data_obj, prop_name)
                                if isinstance(current_val, bool):
                                    pie.prop(data_obj, prop_name, text=slot.label, icon=icon, toggle=True)
                                    bound = True
                            except Exception:
                                bound = False
                        if not bound:
                            # Not a simple boolean property - fall back to
                            # running the raw command via a plain button
                            op = pie.operator("cocopie.execute_command", text=slot.label, icon=icon)
                            op.command = command
                    
                    # Check if this is a bpy.ops operator
                    elif command and command.startswith("bpy.ops."):
                        op_path = command.replace("bpy.ops.", "").split("(")[0]
                        
                        if "." in op_path:
                            module, op_name = op_path.split(".", 1)
                            try:
                                pie.operator(f"{module}.{op_name}", text=slot.label, icon=icon)
                            except:
                                op = pie.operator("cocopie.execute_command", text=slot.label, icon=icon)
                                op.command = command
                        else:
                            op = pie.operator("cocopie.execute_command", text=slot.label, icon=icon)
                            op.command = command
                    else:
                        # Anything else - use execute_command
                        op = pie.operator("cocopie.execute_command", text=slot.label, icon=icon)
                        op.command = command
                except Exception as e:
                    pie.label(text=slot.label)
            else:
                pie.separator()
    
    # Create the class - use name for both label and idname
    menu_class = type(
        pie_data.idname,
        (Menu,),
        {
            "bl_label": pie_data.name,
            "bl_idname": pie_data.idname,
            "draw": draw,
        }
    )
    
    return menu_class
