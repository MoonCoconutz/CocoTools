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
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS, KEYMAP_TYPE_ITEMS,
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


def _tap_toggle_direction_items(self, context):
    """Every direction, labelled with whatever currently sits in it"""
    options = []
    for i in range(8):
        item = next((it for it in self.items if it.position == i), None)
        label = item.label if (item and item.label) else "Empty"
        options.append((str(i), f"{POSITION_NAMES[i]}: {label}", ""))
    return options


def update_pie_menu(self, context):
    """Called when pie menu properties change"""
    try:
        register_pie_menus()
    except Exception as e:
        # Still swallowed: this runs from a property update callback, and
        # letting it raise would break editing the field. But a failed rebuild
        # leaves the menus half-torn-down with nothing in the UI to show it,
        # so it has to at least say so rather than vanishing entirely.
        print(f"CocoPies: failed to rebuild pie menus: {e}")


class COCOPIE_KeymapScope(PropertyGroup):
    """One editor/mode a pie is registered into. A pie holds a collection of
    these, so the same shortcut can be live in several editors at once."""
    keymap_type: EnumProperty(
        name="Editor",
        description="An editor or mode this pie's shortcut is live in",
        items=KEYMAP_TYPE_ITEMS,
        default='WINDOW',
        update=update_pie_menu,
    )


class COCOPIE_PieMenuData(PropertyGroup):
    """Stores data for a single pie menu"""
    # Confirming the field is the end of the rename, so the row goes back to
    # being a plain selected row rather than leaving an edit box open on it
    def _update_name(self, context):
        prefs = get_prefs(context)
        if prefs is not None:
            prefs.renaming_pie_index = -1
        update_pie_menu(self, context)

    name: StringProperty(
        name="Menu Name",
        description="Name of the pie menu",
        default="New Pie Menu",
        update=_update_name
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
        items=KEYMAP_TYPE_ITEMS,
        default='WINDOW',
        update=update_pie_menu
    )

    # The real scope list. `keymap_type` above is the pre-multi-scope field,
    # kept readable so old preferences and old exported presets still load --
    # ensure_keymap_scopes() seeds this collection from it on first touch.
    # Everything that asks "where is this pie live?" goes through
    # keymap_names_for_pie(), never keymap_type directly.
    keymap_scopes: CollectionProperty(type=COCOPIE_KeymapScope)

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
    
    # Replaces the Trigger with its own hold/tap timing (see
    # COCOPIE_OT_hold_or_tap) -- holding the key opens the pie, a quick tap
    # jumps straight to one of two chosen directions instead. Forced to
    # Drag whenever this turns on, since that is the only Trigger value that
    # describes what is actually happening: the key is held down. The
    # Settings UI greys the Trigger dropdown out while this is on rather
    # than hiding it, so the displayed value stays honest either way.
    def _update_tap_toggle(self, context):
        if self.tap_toggle:
            self.event_value = 'CLICK_DRAG'
        update_pie_menu(self, context)

    tap_toggle: BoolProperty(
        name="Tap to Toggle",
        description="A quick tap of the shortcut (press and release without "
                    "moving) jumps straight to one of two chosen directions "
                    "instead of opening the pie",
        default=False,
        update=_update_tap_toggle,
    )
    # What a tap does. Explicit numbers because Blender stores an
    # EnumProperty as its integer value -- see this addon's CLAUDE.md; adding
    # an item above an existing one without a number repoints stored pies.
    tap_action: EnumProperty(
        name="On Tap",
        description="What a quick tap runs, while a hold still opens the pie",
        items=[
            ('TOGGLE', "Toggle Two Directions",
             "Alternate between the two chosen directions", 1),
            ('COMMAND', "Run a Command",
             "Run one command directly, whatever is in the pie", 2),
        ],
        default='TOGGLE',
        update=update_pie_menu,
    )
    # The command form exists so a tap can do something the pie does not
    # contain at all -- most usefully, hand the key back to whatever owned it
    # before. X in mesh edit is the case this was built for: tap deletes
    # (bpy.ops.mesh.cocodelete_delete()), hold opens the delete pie. Kept as
    # a plain command string rather than a reference to another extension, so
    # CocoPies needs to know nothing about what is on the other end.
    tap_command: StringProperty(
        name="Tap Command",
        description="Python run by a quick tap, in the same form as a pie "
                    "item's command",
        default="",
        update=update_pie_menu,
    )
    tap_toggle_a: EnumProperty(
        name="First", description="One of the two directions a tap alternates between",
        items=_tap_toggle_direction_items, update=update_pie_menu,
    )
    tap_toggle_b: EnumProperty(
        name="Second", description="The other direction a tap alternates between",
        items=_tap_toggle_direction_items, update=update_pie_menu,
    )
    # Which of the two ran last, so the next tap runs the other one. Not
    # exposed in the UI.
    tap_toggle_last_ran_a: BoolProperty(default=True)

    items: CollectionProperty(type=COCOPIE_PieMenuItem)
    active_item_index: IntProperty(default=0)
    
    enabled: BoolProperty(
        name="Enabled",
        description="Enable this pie menu and its keymap",
        default=True,
        update=update_pie_menu
    )
