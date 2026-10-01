"""The stored data: one pie menu, and one item inside it."""

from bpy.props import (
    StringProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup
from .items import POSITION_NAMES, KEYMAP_TYPE_ITEMS
from .utils import get_prefs, holding_rebuilds, rebuilds_held
from .keymaps import register_pie_menus


def update_key_uppercase(self, context):
    """Auto-uppercase the key and update menus"""
    upper = self.key.upper()
    if self.key != upper:
        # Re-enters this callback with the uppercase key, and that call does
        # the rebuild -- rebuilding here as well did it twice
        self.key = upper
        return
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
        description="Position in pie menu (0-7: Left, Right, Bottom, Top, Top-Left, Top-Right, Bottom-Left, Bottom-Right)",
        default=0,
        min=0,
        max=7
    )


# Blender keeps only pointers to the strings a dynamic enum callback returns,
# so Python has to keep them alive or the dropdown can read freed memory --
# garbled labels, or a crash (the EnumProperty documentation's own warning).
# One list per pie, handed back unchanged while its labels are, so the two
# dropdowns drawn side by side never free each other's strings.
_tap_direction_items = {}


def _tap_toggle_direction_items(self, context):
    """Every direction, labelled with whatever currently sits in it"""
    options = []
    for i in range(8):
        item = next((it for it in self.items if it.position == i), None)
        label = item.label if (item and item.label) else "Empty"
        options.append((str(i), f"{POSITION_NAMES[i]}: {label}", ""))
    key = self.as_pointer()
    if _tap_direction_items.get(key) == options:
        return _tap_direction_items[key]
    _tap_direction_items[key] = options
    return options


def update_pie_menu(self, context):
    """Called when pie menu properties change"""
    if rebuilds_held():
        return
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


class COCOPIE_SuppressedBinding(PropertyGroup):
    """One keymap item CocoPies is holding switched off on the user's behalf.

    Blender resolves a PRESS binding before a CLICK/CLICK_DRAG one can even be
    considered, so a native PRESS shortcut on the same key swallows a Quick Tap
    pie no matter how far above it CocoPies sits (measured: our items at Mesh[9]
    and Mesh[10], Blender's at Mesh[112], and Blender's still won). Position
    cannot fix that; the only thing that can is switching the other item off.

    Doing that is an edit to the *user* keyconfig, which is not ours to keep --
    so it is stored here rather than applied permanently, re-applied on every
    register, and undone on unregister. Disabling CocoPies gives the key back.

    Identified by content, never by index. Keymap items are appended and
    reindexed constantly; an index recorded now points at a different binding
    after any addon registers, which is the same class of bug that left
    fourteen orphaned items in this keymap.
    """
    keymap: StringProperty()
    idname: StringProperty()
    key_type: StringProperty()
    value: StringProperty()
    # wm.call_menu / wm.call_menu_pie are bound many times over with only
    # properties.name telling them apart, so identity is incomplete without it
    menu_name: StringProperty()
    any_modifier: BoolProperty(default=False)
    shift: BoolProperty(default=False)
    ctrl: BoolProperty(default=False)
    alt: BoolProperty(default=False)
    oskey: BoolProperty(default=False)
    # Set once, when the suppression is created (utils.record_prior_state):
    # False when the item was already switched off before CocoPies got to it,
    # so unregister does not switch on something the user turned off.
    restore_on_unregister: BoolProperty(default=False)


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
    
    # Pie or flat dropdown. Blender's own pies use both -- 3D Viewport Pie
    # Menus draws its Clear Transforms entry with `pie.menu()`, which renders a
    # list, because five clears do not want eight compass directions. A slot
    # pointing at this menu with wm.call_menu already drew it as a dropdown;
    # this is what lets the menu on the other end actually be one.
    #
    # Explicit item numbers: Blender stores an enum as its number, so
    # reordering or inserting later would silently repoint saved data.
    menu_style: EnumProperty(
        name="Style",
        description="Draw this menu as a pie, or as an ordinary dropdown list",
        items=[
            ('PIE',  "Pie",  "Eight directions around the cursor", 'MESH_CIRCLE', 1),
            ('LIST', "List", "A flat dropdown, in slot order", 'ALIGN_JUSTIFY', 2),
        ],
        default='PIE',
        update=update_pie_menu,
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
    
    # Replaces the Trigger with a CLICK_DRAG / CLICK pair (see
    # keymaps._add_keymap_item) -- press and move opens the pie, a quick tap
    # runs the tap action instead. Forced to Drag whenever this turns on,
    # since that is the only Trigger value that describes what opens the
    # pie. The
    # Settings UI greys the Trigger dropdown out while this is on rather
    # than hiding it, so the displayed value stays honest either way.
    # Turning Quick Tap off puts back the Trigger it replaced, which is
    # remembered in trigger_before_tap when it turns on. A pie that was already
    # on Quick Tap before this was remembered goes back to Press, the default.
    def _update_tap_toggle(self, context):
        with holding_rebuilds():
            if self.tap_toggle:
                if self.event_value != 'CLICK_DRAG':
                    self.trigger_before_tap = self.event_value
                self.event_value = 'CLICK_DRAG'
            elif self.event_value == 'CLICK_DRAG':
                self.event_value = self.trigger_before_tap or 'PRESS'
        update_pie_menu(self, context)

    # The Trigger Quick Tap replaced; see _update_tap_toggle. An identifier of
    # event_value, as text: no enum number to freeze, and "" means none kept.
    trigger_before_tap: StringProperty(default="", options={'HIDDEN'})

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
    # (the bundled MeshDeleteNoMenu.py), drag opens the delete pie. Kept as
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
