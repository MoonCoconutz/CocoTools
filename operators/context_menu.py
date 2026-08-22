"""The right-click "Add to Pie Menu" entry."""

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
from ..icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from ..keymaps import register_pie_menus, unregister_pie_menus


class COCOPIE_OT_add_to_pie_from_context(Operator):
    """Add this operator to a pie menu"""
    bl_idname = "cocopie.add_to_pie_from_context"
    bl_label = "Add to Pie Menu"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        op_string = None
        is_property = False
        prop_label = ""
        
        try:
            # Case 1: Operator button
            if hasattr(context, 'button_operator') and context.button_operator:
                button_op = context.button_operator
                op_string = button_op.bl_rna.identifier
                if '.' in op_string:
                    parts = op_string.split('.')
                    op_string = '.'.join(parts[-2:]) if len(parts) > 1 else op_string
            
            # Case 2: Property button (overlay toggles, etc.)
            elif hasattr(context, 'button_pointer') and hasattr(context, 'button_prop'):
                button_pointer = context.button_pointer
                button_prop = context.button_prop
                
                if button_pointer and button_prop:
                    # Get the data path (e.g., "areas[2].spaces[0].overlay")
                    # Convert to bpy.context path
                    try:
                        data_path = button_pointer.path_from_id()
                    except:
                        data_path = None
                    
                    prop_id = button_prop.identifier
                    prop_type = button_prop.type
                    prop_label = prop_id.replace('_', ' ').title()
                    
                    if data_path and prop_id:
                        # Convert area-specific path to context path
                        # "areas[2].spaces[0].overlay" -> "bpy.context.space_data.overlay"
                        # "areas[2].spaces[0]" -> "bpy.context.space_data"
                        import re
                        # Replace areas[N].spaces[N] with context.space_data
                        clean_path = re.sub(r'areas\[\d+\]\.spaces\[\d+\]', 'bpy.context.space_data', data_path)
                        # Replace screens[N].areas[N].spaces[N] patterns too
                        clean_path = re.sub(r'screens\[\w+\]\.areas\[\d+\]\.spaces\[\d+\]', 'bpy.context.space_data', clean_path)
                        
                        full_prop_path = f"{clean_path}.{prop_id}"
                        
                        if prop_type == 'BOOLEAN':
                            # Toggle boolean
                            op_string = f"{full_prop_path} = not {full_prop_path}"
                        elif prop_type in ('INT', 'FLOAT'):
                            # Set to current value (user can edit)
                            try:
                                current_val = getattr(button_pointer, prop_id)
                                op_string = f"{full_prop_path} = {current_val}"
                            except:
                                op_string = f"{full_prop_path} = 0"
                        elif prop_type == 'ENUM':
                            try:
                                current_val = getattr(button_pointer, prop_id)
                                op_string = f"{full_prop_path} = '{current_val}'"
                            except:
                                op_string = f"{full_prop_path} = ''"
                        else:
                            op_string = f"{full_prop_path} = not {full_prop_path}"
                        
                        is_property = True
            
            if op_string:
                captured_label = prop_label if is_property else ""
                is_prop = is_property
                op_str = op_string
                
                def draw_pie_selector(self_menu, context):
                    layout = self_menu.layout
                    prefs = context.preferences.addons[ADDON_ID].preferences
                    if len(prefs.pie_menus) == 0:
                        layout.label(text="No pie menus created yet", icon='INFO')
                        return
                    layout.label(text="Select Pie Menu:", icon='NONE')
                    for i, pie in enumerate(prefs.pie_menus):
                        if len(pie.items) < 8:
                            op = layout.operator("cocopie.add_operator_to_pie", text=pie.name, icon='MENU_PANEL')
                            op.pie_index = i
                            op.operator_string = op_str
                            op.prop_label = captured_label
                            op.is_property = is_prop
                
                context.window_manager.popup_menu(draw_pie_selector, title="Add to Pie Menu", icon='NONE')
                return {'FINISHED'}
        
        except Exception as e:
            print(f"CocoPie capture error: {e}")
            import traceback
            traceback.print_exc()
        
        self.report({'INFO'}, "For menus: hover over item, copy command from status bar, paste into command field")
        return {'CANCELLED'}


class COCOPIE_OT_add_operator_to_pie(Operator):
    """Add the captured operator to the selected pie menu"""
    bl_idname = "cocopie.add_operator_to_pie"
    bl_label = "Add Operator to Pie"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    
    pie_index: IntProperty()
    operator_string: StringProperty()
    prop_label: StringProperty(default="")
    is_property: BoolProperty(default=False)
    
    def should_use_invoke(self, op_name):
        invoke_keywords = [
            'shade_smooth', 'shade_flat', 'shade_auto',
            'subdivision', 'subdivide', 'subsurf',
            'bevel', 'inset', 'extrude', 'delete', 'dissolve',
            'duplicate', 'separate', 'merge', 'split',
            'loop_cut', 'knife', 'rip',
            'modifier_add', 'modifier_apply',
            'translate', 'rotate', 'resize', 'scale', 'transform',
            'save_as', 'save_mainfile', 'open_mainfile',
            'import_', 'export_',
        ]
        return any(keyword in op_name.lower() for keyword in invoke_keywords)
    
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_ID].preferences
        
        if 0 <= self.pie_index < len(prefs.pie_menus):
            pie = prefs.pie_menus[self.pie_index]
            
            if len(pie.items) < 8:
                item = pie.items.add()
                item.icon = "NONE"
                item.enabled = True
                
                if self.is_property:
                    # Property command - store as-is
                    item.command = self.operator_string
                    item.label = self.prop_label if self.prop_label else self.operator_string.split('.')[-1].split(' ')[0].replace('_', ' ').title()
                    self.report({'INFO'}, f"Added property '{item.label}' to {pie.name}")
                
                elif 'MT_' in self.operator_string or '_MT_' in self.operator_string:
                    # Menu
                    menu_class = self.operator_string
                    label = menu_class.replace('VIEW3D_MT_', '').replace('_MT_', ' ').replace('_', ' ').title()
                    item.label = label
                    item.command = f"bpy.ops.wm.call_menu(name='{menu_class}')"
                    self.report({'INFO'}, f"Added menu '{label}' to {pie.name}")
                
                else:
                    # Regular operator
                    op_name = self.operator_string
                    if '_OT_' in op_name:
                        parts = op_name.split('_OT_')
                        if len(parts) == 2:
                            op_name = f"{parts[0].lower()}.{parts[1].lower()}"
                    else:
                        op_name = op_name.lower()
                    
                    item.label = op_name.split('.')[-1].replace('_', ' ').title()
                    item.command = f"bpy.ops.{op_name}()"
                    self.report({'INFO'}, f"Added '{op_name}' to {pie.name}")
                
                # Find first available position
                used_positions = [it.position for it in pie.items[:-1]]
                for pos in range(8):
                    if pos not in used_positions:
                        item.position = pos
                        break
                
                register_pie_menus()
            else:
                self.report({'WARNING'}, f"{pie.name} is full (8/8 items)")
        
        return {'FINISHED'}




def menu_func_context(self, context):
    """Add 'Add to Pie Menu' to right-click context menu"""
    layout = self.layout
    layout.separator()
    layout.operator("cocopie.add_to_pie_from_context", icon='MENU_PANEL')
