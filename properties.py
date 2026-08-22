"""The stored data: one pie menu, and one item inside it."""

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
from .icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from .keymaps import register_pie_menus, unregister_pie_menus


def update_key_uppercase(self, context):
    """Auto-uppercase the key and update menus"""
    # Convert to uppercase automatically (avoid infinite loop)
    if self.key and self.key != self.key.upper():
        # Store old value to check if it changed
        old_key = self.key
        self.key = self.key.upper()
        # Only update if it actually changed
        if old_key != self.key:
            # Update the pie menu after uppercase conversion
            update_pie_menu(self, context)
    else:
        # Key is already uppercase, just update
        update_pie_menu(self, context)


class COCOPIE_PieMenuItem(PropertyGroup):
    """Individual item in a pie menu"""
    label: StringProperty(
        name="Label",
        description="Display label for this pie menu item",
        default="New Item"
    )
    
    command: StringProperty(
        name="Command",
        description="Python command to execute (e.g., bpy.ops.mesh.primitive_cube_add())",
        default=""
    )
    
    icon: StringProperty(
        name="Icon",
        description="Icon name (e.g., MESH_CUBE, OUTLINER_OB_LIGHT)",
        default="NONE"
    )
    
    enabled: BoolProperty(
        name="Enabled",
        description="Enable this menu item",
        default=True
    )
    
    position: IntProperty(
        name="Position",
        description="Position in pie menu (0-7: Right, Top, Left, Bottom, Bottom-Left, Bottom-Right, Top-Left, Top-Right)",
        default=0,
        min=0,
        max=7
    )


def update_pie_menu(self, context):
    """Called when pie menu properties change"""
    try:
        register_pie_menus()
    except Exception as e:
        # Still swallowed: this runs from a property update callback, and
        # letting it raise would break editing the field. But a failed rebuild
        # leaves the menus half-torn-down with nothing in the UI to show it,
        # so it has to at least say so rather than vanishing entirely.
        print(f"CocoPie: failed to rebuild pie menus: {e}")

class COCOPIE_PieMenuData(PropertyGroup):
    """Stores data for a single pie menu"""
    name: StringProperty(
        name="Menu Name",
        description="Name of the pie menu",
        default="New Pie Menu",
        update=update_pie_menu
    )
    
    idname: StringProperty(
        name="ID Name",
        description="Unique identifier (e.g., VIEW3D_MT_my_pie)",
        default="COCOPIE_MT_custom_pie",
        update=update_pie_menu
    )
    
    # No `label` property: the menu's displayed title is bl_label, which is
    # built from `name`. A separate label field existed here but was never
    # read by anything -- only written on create, on duplicate, and into
    # presets -- while still triggering a full re-registration on every change.

    keymap_type: EnumProperty(
        name="Keymap Type",
        description="Where to register the keymap",
        items=[
            ('WINDOW', "Window (Global)",
             "Every 3D viewport mode - object, edit, sculpt and the paint modes"),

            ("", "Modes", ""),
            ('OBJECT_MODE', "Object Mode", "3D viewport, object mode only"),
            ('MESH', "Mesh (Edit Mode)", "3D viewport, mesh edit mode only"),
            ('CURVE', "Curve (Edit Mode)", "3D viewport, curve edit mode only"),
            ('ARMATURE', "Armature (Edit Mode)", "3D viewport, armature edit mode only"),
            ('POSE', "Pose Mode", "3D viewport, pose mode only"),
            ('SCULPT', "Sculpt Mode", "3D viewport, sculpt mode only"),
            ('VERTEX_PAINT', "Vertex Paint", "3D viewport, vertex paint mode only"),
            ('WEIGHT_PAINT', "Weight Paint", "3D viewport, weight paint mode only"),
            ('IMAGE_PAINT', "Texture Paint", "3D viewport, texture paint mode only"),
            ('UV_EDITOR', "UV Editor", "UV editing only, not the Image editor at large"),

            ("", "Editors", ""),
            ('3D_VIEW', "3D View", "3D Viewport, every mode"),
            ('IMAGE_EDITOR', "Image Editor", "Image Editor, including UV editing"),
            ('NODE_EDITOR', "Node Editor", "Node Editor/Shader Editor/Geometry Nodes"),
            ('SEQUENCE_EDITOR', "Sequencer", "Video Sequencer"),
            ('CLIP_EDITOR', "Movie Clip Editor", "Movie Clip Editor"),
            ('DOPESHEET_EDITOR', "Dope Sheet", "Dope Sheet"),
            ('GRAPH_EDITOR', "Graph Editor", "Graph Editor"),
            ('NLA_EDITOR', "NLA Editor", "NLA Editor"),
            ('TEXT_EDITOR', "Text Editor", "Text Editor"),
            ('CONSOLE', "Python Console", "Python Console"),
            ('INFO', "Info", "Info"),
            ('OUTLINER', "Outliner", "Outliner"),
            ('PROPERTIES', "Properties", "Properties"),
            ('FILE_BROWSER', "File Browser", "File Browser"),
            ('PREFERENCES', "Preferences", "Preferences"),
        ],
        default='WINDOW',
        update=update_pie_menu
    )
    
    key: StringProperty(
        name="Key",
        description="Keyboard key (case-insensitive: 'q' becomes 'Q')",
        default="Q",
        update=update_key_uppercase
    )
    
    # Blender's real KeyMapItem.ctrl/shift/alt/oskey are tri-state ints (-1
    # "any", 0 off, 1 required) -- but its own keymap editor does not expose
    # that tri-state either. Its source comment says why: "integers aren't
    # practical" for a toggle button. It uses plain on/off booleans for each
    # modifier plus one separate "Any" button that means "ignore all of them",
    # and passes that straight to keymap_items.new(any=...). This mirrors that
    # exactly rather than building real tri-state cycling Blender itself skips.
    any_modifier: BoolProperty(
        name="Any", description="Any modifier keys pressed",
        default=False, update=update_pie_menu,
    )
    shift: BoolProperty(name="Shift", default=False, update=update_pie_menu)
    ctrl: BoolProperty(name="Ctrl", default=False, update=update_pie_menu)
    alt: BoolProperty(name="Alt", default=False, update=update_pie_menu)
    oskey: BoolProperty(
        name="OS", description="Operating system key (Cmd / Win) pressed",
        default=False, update=update_pie_menu,
    )
    
    event_value: EnumProperty(
        name="Trigger",
        description="Which key event fires the pie -- the same set Blender's own "
                    "keymap editor offers for a KeyMapItem",
        # Identifiers, names and order match bpy.types.KeyMapItem.value exactly,
        # so a shortcut set up here means what it would mean anywhere else in
        # Blender. The previous version quietly dropped CLICK and NOTHING, and
        # mislabelled ANY as "Key Chords" and RELEASE as "Hold" -- RELEASE fires
        # once on key-up, it does not mean holding the key down.
        items=[
            ('ANY',          "Any",          "Trigger on any event for this key",   'HAND',           0),
            ('PRESS',        "Press",        "Trigger the moment the key goes down", 'MOUSE_LMB',      1),
            ('RELEASE',      "Release",      "Trigger the moment the key goes up",   'TIME',           2),
            ('CLICK',        "Click",        "Trigger on a press immediately followed by a release", 'MOUSE_LMB', 3),
            ('DOUBLE_CLICK', "Double Click", "Trigger on double click",              'MOUSE_LMB_2X',   4),
            ('CLICK_DRAG',   "Drag",         "Trigger once the key is pressed and moved", 'MOUSE_LMB_DRAG', 5),
            ('NOTHING',      "Nothing",      "Never trigger -- keeps the shortcut defined without making it live", 'X', 6),
        ],
        default='PRESS',
        update=update_pie_menu
    )
    
    items: CollectionProperty(type=COCOPIE_PieMenuItem)
    active_item_index: IntProperty(default=0)
    
    enabled: BoolProperty(
        name="Enabled",
        description="Enable this pie menu and its keymap",
        default=True,
        update=update_pie_menu
    )
