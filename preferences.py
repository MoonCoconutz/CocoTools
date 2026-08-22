"""The addon preferences panel -- the whole pie editor."""

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
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS, TWO_ICON_BUTTONS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut, oskey_label,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
    ensure_slot_items, slot_is_used,
    addon_version_string,
)
from .icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from .keymaps import register_pie_menus, unregister_pie_menus
from .previews import slot_button_args, icon_args
from .properties import COCOPIE_PieMenuItem, COCOPIE_PieMenuData


class COCOPIE_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_ID
    
    pie_menus: CollectionProperty(type=COCOPIE_PieMenuData)
    active_pie_index: IntProperty(default=0)
    
    def draw(self, context):
        layout = self.layout
        
        try:
            # Main split - Left: Pie Menu List, Right: Editor
            main_split = layout.split(factor=0.35)
            
            # LEFT COLUMN
            self.draw_left_column(main_split.column())
            
            # RIGHT COLUMN
            self.draw_right_column(main_split.column())
            
        except Exception as e:
            box = layout.box()
            box.alert = True
            box.label(text="Error drawing preferences!", icon='ERROR')
            box.label(text=str(e))
            import traceback
            traceback.print_exc()
    
    def draw_left_column(self, layout):
        """Draw the left column with pie menu list"""
        # Header — title on the left, live count on the right
        header = layout.box().row(align=True)
        header.label(text="Pie Menus", icon='MENU_PANEL')
        count = header.row(align=True)
        count.alignment = 'RIGHT'
        count.active = False
        active = len([p for p in self.pie_menus if p.enabled])
        count.label(text=f"{active} of {len(self.pie_menus)} active")

        layout.separator(factor=0.5)

        # List - native UIList gives a clear highlighted row for the active item
        if len(self.pie_menus) == 0:
            col = layout.box().column(align=True)
            col.scale_y = 1.4
            col.label(text="No pie menus yet", icon='INFO')
            col.label(text="Create one with the button below.")
        else:
            layout.template_list(
                "COCOPIE_UL_pie_menus", "",
                self, "pie_menus",
                self, "active_pie_index",
                rows=max(4, min(len(self.pie_menus), 10)),
            )

        # Buttons: New Pie Menu takes whatever width the reorder pair leaves,
        # which is a fixed two icon buttons' worth
        layout.separator(factor=0.5)
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("cocopie.add_pie_menu", text="New Pie Menu", icon='ADD')

        reorder = row.row(align=True)
        reorder.ui_units_x = TWO_ICON_BUTTONS_UNITS

        # Each arrow greys out at the end it cannot travel any further towards
        up = reorder.row(align=True)
        up.enabled = self.active_pie_index > 0
        up.operator("cocopie.move_pie_menu", text="", icon='TRIA_UP').direction = 'UP'

        down = reorder.row(align=True)
        down.enabled = self.active_pie_index < len(self.pie_menus) - 1
        down.operator("cocopie.move_pie_menu", text="", icon='TRIA_DOWN').direction = 'DOWN'

        # Presets
        layout.separator(factor=0.8)
        preset_box = layout.box()
        preset_box.label(text="Presets", icon='PRESET')
        row = preset_box.row(align=True)
        row.scale_y = 1.15
        row.operator("cocopie.save_preset", text="Export", icon='EXPORT')
        row.operator("cocopie.load_preset", text="Import", icon='IMPORT')

        row = preset_box.row(align=True)
        row.scale_y = 1.15
        row.operator("cocopie.restore_defaults", text="Restore Starter Pies", icon='RECOVER_LAST')

        # Refresh
        layout.separator(factor=0.8)
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("cocopie.refresh_menus", text="Refresh All Keymaps", icon='FILE_REFRESH')

        # Version footer
        layout.separator(factor=0.5)
        footer = layout.row(align=True)
        footer.alignment = 'RIGHT'
        footer.active = False
        footer.scale_y = 0.8
        footer.label(text=addon_version_string())


    def draw_right_column(self, layout):
        """Draw the right column with pie editor"""
        if len(self.pie_menus) == 0 or self.active_pie_index >= len(self.pie_menus):
            col = layout.box().column(align=True)
            col.scale_y = 1.8
            col.label(text="Nothing selected", icon='HAND')
            col.label(text="Pick a pie menu on the left, or create a new one.")
            return

        pie = self.pie_menus[self.active_pie_index]

        # Header — name on the left, live shortcut on the right
        header = layout.box().row(align=True)
        header.label(text=pie.name or "Untitled", icon='GREASEPENCIL')
        chip = header.row(align=True)
        chip.alignment = 'RIGHT'
        chip.active = pie.enabled
        chip.label(text=format_shortcut(pie), icon='KEYINGSET')

        layout.separator(factor=0.5)

        # Settings
        self.draw_pie_settings(layout, pie)

        layout.separator()

        # Items
        self.draw_pie_items(layout, pie)

    def draw_pie_settings(self, layout, pie):
        """Draw pie menu settings"""
        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')

        # Property split gives the native right-aligned label column
        col = box.column()
        col.use_property_split = True
        col.use_property_decorate = False

        col.prop(pie, "name", text="Name")
        col.prop(pie, "keymap_type", text="Editor")

        col.separator(factor=0.5)

        # Whole shortcut stays on one line: trigger + modifiers + key.
        # Modifier order and grouping (Any, Shift, Ctrl, Alt, OS) matches
        # Blender's own keymap editor exactly -- see rna_keymap_ui.py's
        # draw_kmi(), which draws kmi.any then shift_ui/ctrl_ui/alt_ui/oskey_ui
        # in that order.
        row = col.row(align=True, heading="Shortcut")
        trigger = row.row(align=True)
        trigger.scale_x = 0.9
        trigger.prop(pie, "event_value", text="")
        row.separator(factor=0.4)
        row.prop(pie, "any_modifier", text="Any", toggle=True)
        row.prop(pie, "shift", text="Shift", toggle=True)
        row.prop(pie, "ctrl", text="Ctrl", toggle=True)
        row.prop(pie, "alt", text="Alt", toggle=True)
        row.prop(pie, "oskey", text=oskey_label(), toggle=True)
        row.separator(factor=0.4)
        key = row.row(align=True)
        key.scale_x = 0.6
        key.prop(pie, "key", text="")

        conflicts = find_shortcut_conflicts(self, pie, self.active_pie_index)
        if conflicts:
            names = ", ".join(conflicts[:3])
            if len(conflicts) > 3:
                names += f" (+{len(conflicts) - 3} more)"
            warn = box.row()
            warn.label(text=f"Same shortcut as: {names}", icon='ERROR')

    def draw_pie_items(self, layout, pie):
        """Draw the item table for the selected pie menu"""
        box = layout.box()

        # Header: title, count badge, add button
        header = box.row(align=True)
        header.label(text="Menu Items", icon='PRESET')

        # One row per direction, always all eight, always in slot order. The
        # row *is* the slot, so there is nothing to add, remove or move -- a
        # direction is used once it has a label or a command, and free again
        # once it is cleared.
        ensure_slot_items(pie)

        used = [it for it in pie.items if slot_is_used(it)]

        count = header.row(align=True)
        count.alignment = 'RIGHT'
        count.active = False
        count.label(text=f"{len(used)} / 8 used")

        box.separator(factor=0.5)

        table = box.column(align=True)
        self.draw_item_header(table)
        for index, item in enumerate(pie.items):
            self.draw_single_item(table, pie, item, index)

        # Status line — anything that needs attention
        box.separator(factor=0.5)
        status = box.column(align=True)
        status.scale_y = 0.9

        if not used:
            row = status.row()
            row.active = False
            row.label(text="Nothing in this pie yet — fill in a direction above",
                      icon='INFO')

        missing = [it for it in used if not it.command.strip()]
        if missing:
            row = status.row()
            row.active = False
            row.label(text=f"{len(missing)} direction(s) named but with no command yet",
                      icon='INFO')

    def draw_item_header(self, layout):
        """Dim column captions sized to match draw_single_item's columns"""
        header = layout.row(align=True)
        header.scale_y = 0.7
        header.active = False

        cell = header.row(align=True)
        cell.ui_units_x = COL_CHECK_UNITS
        cell.label(text="")

        cell = header.row(align=True)
        cell.ui_units_x = COL_POS_UNITS
        cell.label(text="Pos")

        cell = header.row(align=True)
        cell.ui_units_x = COL_ICON_UNITS
        cell.label(text="Icon")

        cell = header.row(align=True)
        cell.scale_x = COL_LABEL_SCALE
        cell.label(text="Label")

        cell = header.row(align=True)
        cell.scale_x = COL_CMD_SCALE
        cell.label(text="Command")

        cell = header.row(align=True)
        cell.ui_units_x = COL_TOOLS_UNITS
        cell.label(text="")

    def draw_single_item(self, layout, pie, item, index):
        """Draw one direction's row. The row is the slot -- index is position."""
        used = slot_is_used(item)

        row = layout.row(align=True)
        # Matches COL_POS_UNITS / COL_ICON_UNITS so those buttons are square
        row.scale_y = ITEM_ROW_UNITS

        # Enable checkbox — meaningless on a direction that holds nothing
        chk_row = row.row(align=True)
        chk_row.ui_units_x = COL_CHECK_UNITS
        chk_row.enabled = used
        chk_row.prop(item, "enabled", text="",
                     icon='CHECKBOX_HLT' if item.enabled and used else 'CHECKBOX_DEHLT',
                     emboss=False)

        # Everything else dims with the item so disabled rows recede
        body = row.row(align=True)
        body.active = item.enabled and used

        # Direction: fixed to the row, not a control. It reads as a label
        # rather than a button because there is nothing to click -- the slot
        # is decided by which row you are on.
        pos_cell = body.row(align=True)
        pos_cell.ui_units_x = COL_POS_UNITS
        pos_cell.alignment = 'CENTER'
        pos_cell.label(**slot_button_args(item.position))

        # Icon selector button
        icon_btn = body.row(align=True)
        icon_btn.ui_units_x = COL_ICON_UNITS
        op = icon_btn.operator("cocopie.select_icon", text="",
                               **icon_args(item.icon, 'BLANK1'))
        op.pie_index = self.active_pie_index
        op.item_index = index

        # Label field
        label_row = body.row(align=True)
        label_row.scale_x = COL_LABEL_SCALE
        label_row.prop(item, "label", text="")

        # Command field
        cmd_row = body.row(align=True)
        cmd_row.scale_x = COL_CMD_SCALE
        cmd_row.prop(item, "command", text="")

        # Tools: expand the command in a roomy dialog, or point at a .py file
        tools = body.row(align=True)
        tools.ui_units_x = COL_TOOLS_UNITS
        op = tools.operator("cocopie.edit_item_command", text="", icon='CONSOLE')
        op.pie_index = self.active_pie_index
        op.item_index = index
        op = tools.operator("cocopie.pick_script", text="", icon='FILE_SCRIPT')
        op.pie_index = self.active_pie_index
        op.item_index = index

        # Clear, rather than delete: the row stays either way, since the eight
        # directions are fixed. Disabled on a row that is already empty.
        clear = row.row(align=True)
        clear.enabled = used
        op = clear.operator("cocopie.remove_item", text="", icon='X', emboss=False)
        op.pie_index = self.active_pie_index
        op.item_index = index
