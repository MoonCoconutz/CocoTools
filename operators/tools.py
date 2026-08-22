"""Per-item tools: testing a pie, editing a command, picking a script or icon."""

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
from ..menus import execute_script, create_pie_menu_class
from ..keymaps import register_pie_menus, unregister_pie_menus
from ..previews import (
    icon_args, custom_icon_names, custom_icon_dirs, register_previews,
    CUSTOM_PREFIX,
)


class COCOPIE_OT_test_pie_menu(Operator):
    """Test the selected pie menu"""
    bl_idname = "cocopie.test_pie_menu"
    bl_label = "Test Pie Menu"
    bl_options = {'REGISTER'}
    
    pie_index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.pie_index < len(prefs.pie_menus):
                pie = prefs.pie_menus[self.pie_index]
                bpy.ops.wm.call_menu_pie(name=pie.idname)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to test: {str(e)}")
        
        return {'FINISHED'}


class COCOPIE_OT_refresh_menus(Operator):
    """Refresh all pie menus"""
    bl_idname = "cocopie.refresh_menus"
    bl_label = "Refresh Menus"
    bl_description = "Re-register all pie menus and keymaps"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        try:
            register_pie_menus()
            self.report({'INFO'}, "Pie menus refreshed")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to refresh: {str(e)}")
        
        return {'FINISHED'}



class COCOPIE_OT_edit_item_command(Operator):
    """Edit this item's command in a roomier field"""
    bl_idname = "cocopie.edit_item_command"
    bl_label = "Set Command"
    bl_options = {'REGISTER', 'UNDO'}

    pie_index: IntProperty()
    item_index: IntProperty()
    command: StringProperty(
        name="Command",
        default="",
        description="Python command (copy/paste or type)"
    )

    def invoke(self, context, event):
        item = get_pie_item(context, self.pie_index, self.item_index)
        if item:
            self.command = item.command

        wm = context.window_manager
        try:
            return wm.invoke_props_dialog(self, width=680, title="Edit Command")
        except TypeError:
            return wm.invoke_props_dialog(self, width=680)

    def draw(self, context):
        layout = self.layout
        item = get_pie_item(context, self.pie_index, self.item_index)

        if item:
            head = layout.row(align=True)
            head.label(text=item.label or "Untitled item",
                       icon=safe_icon(item.icon, 'DOT'))
            slot = head.row(align=True)
            slot.alignment = 'RIGHT'
            slot.active = False
            slot.label(text=POSITION_NAMES.get(item.position, ""))
            layout.separator(factor=0.5)

        field = layout.row(align=True)
        field.scale_y = 1.4
        field.prop(self, "command", text="", icon='CONSOLE')

        layout.separator(factor=0.8)

        box = layout.box()
        box.label(text="What you can put here", icon='INFO')
        col = box.column(align=True)
        col.scale_y = 0.85
        col.active = False
        col.label(text="Operator      bpy.ops.mesh.subdivide()")
        col.label(text="Interactive   bpy.ops.transform.translate('INVOKE_DEFAULT')")
        col.label(text="Toggle        bpy.context.space_data.overlay.show_wireframes = True")
        col.label(text="Submenu       bpy.ops.wm.call_menu(name='VIEW3D_MT_snap')")
        col.label(text="Script        execute_script(\"C:/path/to/script.py\")")
        col.separator(factor=0.6)
        col.label(text="A toggle written as 'x = not x' becomes a lit on/off button.")

    def execute(self, context):
        item = get_pie_item(context, self.pie_index, self.item_index)
        if item:
            item.command = self.command
            register_pie_menus()

        return {'FINISHED'}




class COCOPIE_OT_pick_script(Operator):
    """Open file browser to pick a Python script"""
    bl_idname = "cocopie.pick_script"
    bl_label = "Pick Script"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    
    pie_index: IntProperty()
    item_index: IntProperty()
    
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.py", options={'HIDDEN'})
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_ID].preferences
        if 0 <= self.pie_index < len(prefs.pie_menus):
            pie = prefs.pie_menus[self.pie_index]
            if 0 <= self.item_index < len(pie.items):
                item = pie.items[self.item_index]
                
                # Normalize path with forward slashes
                filepath = self.filepath.replace("\\", "/")
                
                # Set command using clean execute_script syntax
                item.command = f'execute_script("{filepath}")'
                
                # Auto-set label from filename if label is still default
                import os
                filename = os.path.splitext(os.path.basename(filepath))[0]
                if item.label in ("New Item", "Item", ""):
                    item.label = filename.replace("_", " ").replace("-", " ").title()
                
                register_pie_menus()
        
        return {'FINISHED'}


class COCOPIE_OT_refresh_icons(Operator):
    """Re-read the custom icons folder, picking up files added since Blender
    started"""
    bl_idname = "cocopie.refresh_icons"
    bl_label = "Refresh Custom Icons"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        try:
            register_previews()
        except Exception as e:
            self.report({'ERROR'}, f"Could not reload icons: {e}")
            return {'CANCELLED'}

        found = len(custom_icon_names())
        self.report({'INFO'}, f"{found} custom icon(s) loaded" if found
                    else "No custom icons found in the folder")
        return {'FINISHED'}


# The picker's choice, held here rather than written straight to the item, so
# that closing the dialog with Cancel or Esc leaves the item alone. Only
# COCOPIE_OT_select_icon.execute() -- Done, or Return -- commits it.
_pending_icon = {"pie": -1, "item": -1, "icon": 'NONE'}


class COCOPIE_OT_select_icon(Operator):
    """Browse Blender's icons and pick one for this item"""
    bl_idname = "cocopie.select_icon"
    bl_label = "Select Icon"
    bl_options = {'REGISTER', 'INTERNAL'}

    # A props_dialog can't scroll, so the grid is capped and the footer tells
    # you to keep typing when there's more than fits
    GRID_COLUMNS = 24
    GRID_MAX_ROWS = 13

    pie_index: IntProperty()
    item_index: IntProperty()

    search: StringProperty(
        name="Search",
        description="Filter icons by name",
        default="",
        # TEXTEDIT_UPDATE redraws the dialog on every keystroke rather than
        # waiting for Return, which is what makes the grid filter live
        options={'TEXTEDIT_UPDATE'},
    )

    category: EnumProperty(
        name="Category",
        description="Narrow the grid down to one family of icons",
        items=ICON_CATEGORY_ENUM,
        default='ALL',
    )

    def invoke(self, context, event):
        self.search = ""

        # Start from whatever the item already has, so cancelling really is a
        # no-op and confirming without touching the grid changes nothing
        item = get_pie_item(context, self.pie_index, self.item_index)
        _pending_icon.update({
            "pie": self.pie_index,
            "item": self.item_index,
            "icon": item.icon if item else 'NONE',
        })

        wm = context.window_manager
        try:
            return wm.invoke_props_dialog(self, width=880, title="Select Icon",
                                          confirm_text="Done")
        except TypeError:
            # title/confirm_text aren't accepted on every 4.x/5.x build
            return wm.invoke_props_dialog(self, width=880)

    def _filtered_icons(self):
        # Custom icons are not in Blender's catalogue -- they are files
        # CocoPie loaded -- so they are listed by reference, prefix and all
        if self.category == 'CUSTOM':
            refs = [CUSTOM_PREFIX + name for name in custom_icon_names()]
            needle = self.search.strip().lower()
            if needle:
                refs = [r for r in refs if needle in r.lower()]
            return refs

        icons = get_icons_by_category().get(self.category, [])
        needle = self.search.strip().upper().replace(" ", "_")
        if not needle:
            return icons
        # Prefix matches first — typing "cube" should surface CUBE before
        # MESH_CUBE's noisier cousins
        starts = [n for n in icons if n.startswith(needle)]
        contains = [n for n in icons if needle in n and not n.startswith(needle)]
        return starts + contains

    def draw(self, context):
        layout = self.layout
        # The choice being previewed, not what the item holds -- the item is
        # only written on Done
        current = _pending_icon["icon"]
        has_icon = bool(current and current != 'NONE')

        # --- current selection -------------------------------------------
        head = layout.box().row(align=True)
        head.scale_y = 1.2
        preview = head.row(align=True)
        preview.label(text="Current", **icon_args(current, 'BLANK1'))
        name_row = head.row(align=True)
        name_row.alignment = 'LEFT'
        name_row.active = has_icon
        name_row.label(text=current if has_icon else "No icon set")

        clear = head.row(align=True)
        clear.alignment = 'RIGHT'
        clear.enabled = has_icon
        op = clear.operator("cocopie.set_icon_choice", text="Clear", icon='X')
        op.pie_index = self.pie_index
        op.item_index = self.item_index
        op.icon_name = 'NONE'

        # --- search ------------------------------------------------------
        layout.separator(factor=0.5)
        search_row = layout.row(align=True)
        search_row.scale_y = 1.3
        search_row.prop(self, "search", text="", icon='VIEWZOOM')

        # --- category tabs -----------------------------------------------
        layout.separator(factor=0.4)
        tabs = layout.row(align=True)
        tabs.scale_y = 1.1
        tabs.prop(self, "category", expand=True)

        # Custom icons are read from disk once, so a file added while Blender
        # is running needs a re-read to appear. Only shown where it applies.
        if self.category == 'CUSTOM':
            reload_row = layout.row(align=True)
            reload_row.scale_y = 1.1
            reload_row.operator("cocopie.refresh_icons",
                                text="Reload icons from folder",
                                icon='FILE_REFRESH')

        # --- grid --------------------------------------------------------
        layout.separator(factor=0.5)
        icons = self._filtered_icons()

        if not icons:
            empty = layout.box().column(align=True)
            empty.scale_y = 1.3
            if self.category == 'CUSTOM' and not self.search.strip():
                # Nothing to search through yet -- say where to put files
                empty.label(text="No custom icons yet", icon='INFO')
                empty.label(text="Drop PNG files here, then press Reload above:")
                for folder in custom_icon_dirs():
                    path = empty.row(align=True)
                    path.active = False
                    path.label(text=folder)
            else:
                empty.label(text=f'No icon matches "{self.search}"', icon='INFO')
                empty.label(text="Try a shorter word, or switch to the All tab")
            return

        limit = self.GRID_COLUMNS * self.GRID_MAX_ROWS
        shown = icons[:limit]

        box = layout.box()
        grid = box.grid_flow(row_major=True, columns=self.GRID_COLUMNS,
                             align=True, even_columns=True, even_rows=True)
        for name in shown:
            cell = grid.row(align=True)
            is_current = name == current
            if not is_current:
                # Flat cells keep a 300-icon grid calm; only the active one
                # gets a button frame
                cell.emboss = 'NONE'
            try:
                op = cell.operator("cocopie.set_icon_choice", text="",
                                   depress=is_current, **icon_args(name))
                op.pie_index = self.pie_index
                op.item_index = self.item_index
                op.icon_name = name
            except Exception:
                cell.label(text="", icon='BLANK1')

        foot = layout.row(align=True)
        foot.active = False
        if len(icons) > limit:
            foot.label(
                text=f"Showing {limit} of {len(icons)} icons — keep typing to narrow it down",
                icon='INFO')
        else:
            foot.label(text=f"{len(icons)} icon{'s' if len(icons) != 1 else ''}")

    def execute(self, context):
        # Done, or Return. This is the only place the item is written -- the
        # grid only stages a choice, so Cancel and Esc, which never reach here,
        # leave the item exactly as it was.
        if (_pending_icon["pie"] != self.pie_index
                or _pending_icon["item"] != self.item_index):
            return {'CANCELLED'}

        item = get_pie_item(context, self.pie_index, self.item_index)
        if item:
            item.icon = _pending_icon["icon"] or 'NONE'
            register_pie_menus()

        return {'FINISHED'}


class COCOPIE_OT_set_icon_choice(Operator):
    """Choose this icon. It is applied when you press Done"""
    bl_idname = "cocopie.set_icon_choice"
    bl_label = "Choose Icon"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()
    item_index: IntProperty()
    icon_name: StringProperty()

    @classmethod
    def description(cls, context, properties):
        if properties.icon_name in ('', 'NONE'):
            return "Clear the icon. Applied when you press Done"
        return properties.icon_name

    def execute(self, context):
        # Staged only. Writing straight to the item here is what used to make
        # Cancel pointless -- the change was already done by then.
        _pending_icon.update({
            "pie": self.pie_index,
            "item": self.item_index,
            "icon": self.icon_name or 'NONE',
        })
        return {'FINISHED'}
