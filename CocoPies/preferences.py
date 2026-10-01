"""The addon preferences panel -- the whole pie editor."""

import traceback
import bpy
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, CollectionProperty,
)
from bpy.types import AddonPreferences
from .items import (
    ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
)
from .utils import (
    ADDON_ID, format_shortcut, find_shortcut_conflicts,
    ensure_slot_items, slot_is_used,
    find_external_conflicts, pie_menu_groups,
    collapsed_group_keys,
)
from .previews import slot_button_args, icon_args
from .properties import COCOPIE_PieMenuData, COCOPIE_SuppressedBinding
from .ui import draw_pie_row, draw_list_toolbar, editors_summary
from .keymaps import _resolve_key
# The module, not the name: capturing_pie_index is reassigned while a capture
# runs, and a name imported once would never see that
from .operators import pies as pie_ops


# Width of the label column in the pie editor's boxes
LABEL_FACTOR = 0.15
# Width of the Name, Style and Editors fields in the Menu box
MENU_FIELD_UNITS = 10
# The Menu box is half as wide as Shortcut under it, so twice the factor
# keeps the two label columns ending at the same place
MENU_LABEL_FACTOR = LABEL_FACTOR * 2


def _labelled(parent, text, factor=LABEL_FACTOR):
    """One line with a right-aligned label column; returns the value side.

    Done by hand instead of use_property_split: under the split every prop()
    claims the whole value column, so a line holding several fields (the key
    and its modifiers, Quick Tap) wraps them onto lines of their own.
    """
    split = parent.split(factor=factor, align=True)
    label = split.row()
    label.alignment = 'RIGHT'
    label.label(text=text)
    return split.row(align=True)


def _key_label(key):
    """A stored key as Blender names it: "Space Bar" for SPACE, "2" for 2"""
    if not key:
        return "Not set"
    items = bpy.types.Event.bl_rna.properties['type'].enum_items
    event = _resolve_key(key)
    return items[event].name if event in items.keys() else key


def _shortcut_label(pie):
    """The whole shortcut on the key button, as the keymap editor writes it:
    "Alt + R". Modifier order as utils.format_shortcut."""
    if pie.any_modifier:
        mods = ["Any"]
    else:
        mods = [name for name, on in (("Shift", pie.shift), ("Ctrl", pie.ctrl),
                                      ("Alt", pie.alt)) if on]
    return " + ".join(mods + [_key_label(pie.key)])


class COCOPIE_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_ID
    
    pie_menus: CollectionProperty(type=COCOPIE_PieMenuData)
    # Keymap items CocoPies holds switched off while it is loaded, so a Quick
    # Tap pie can actually own a key Blender already binds on PRESS. Restored
    # on unregister -- see apply_suppressions/restore_suppressions.
    suppressed_bindings: CollectionProperty(type=COCOPIE_SuppressedBinding)
    active_pie_index: IntProperty(default=0)
    # Which row is currently being renamed in place, or -1 for none. Session
    # state rather than settings: a rename is over as soon as it is confirmed
    # or another row is clicked, so this is never meaningfully saved.
    renaming_pie_index: IntProperty(default=-1)

    # Names of every starter pie this configuration has ever been given, as a
    # JSON list. What makes "add starters the user has never seen" different
    # from "add starters that are missing": an update's new starters appear on
    # their own, while a starter the user deliberately deleted stays deleted
    # instead of coming back at every startup. Restore Starter Pies is the
    # deliberate way to get a deleted one back. See sync_starter_pies().
    seeded_starters: StringProperty(default="", options={'HIDDEN'})
    # One-shot: the delete starters gained their keymap suppression after they
    # had already shipped, so configurations that were seeded before it exists
    # need it backfilled once. Recorded rather than repeated, or unticking the
    # box would be undone at the next startup.
    starter_suppressions_migrated: BoolProperty(default=False, options={'HIDDEN'})
    # One-shot: CocoPies up to 1.13.2 wrote suppressions into the keymap
    # preset in memory as well, and switched them back *on* there when it was
    # unregistered -- which is what an in-session update does. The first
    # suppression pass of a later version re-reads the preset from its file
    # once, so its edit is not recorded against that leftover.
    # See keymaps._reread_keymap_preset_once.
    keymap_preset_reread: BoolProperty(default=False, options={'HIDDEN'})
    # One-shot: the same versions could delete the Delete-key menus outright
    # (Mesh, Curve), and saved preferences kept them deleted. A later version
    # puts back, once, what went missing that way. Once only, so a shortcut
    # the user removes afterwards stays removed.
    # See keymaps._restore_lost_shortcuts_once.
    lost_shortcuts_restored: BoolProperty(default=False, options={'HIDDEN'})

    # Section keys the user has collapsed in the Pie Menus list, as a JSON
    # list. Stored rather than kept in memory so the panel opens the way it
    # was left. Held as text for the same reason seeded_starters is: the set
    # of sections is data (KEYMAP_TYPE_ITEMS), and a BoolProperty per section
    # would have to be regenerated -- and migrated -- every time a scope is
    # added. Absent from the list means expanded, so a new section shows up
    # open rather than silently hidden.
    collapsed_groups: StringProperty(default="", options={'HIDDEN'})
    
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
            traceback.print_exc()
    
    def draw_left_column(self, layout):
        """Draw the left column with pie menu list"""
        # Header — title on the left, live count on the right
        header = layout.row(align=True)
        header.label(text="Pie Menus", icon='MENU_PANEL')
        count = header.row(align=True)
        count.alignment = 'RIGHT'
        count.active = False
        active = len([p for p in self.pie_menus if p.enabled])
        count.label(text=f"{active} of {len(self.pie_menus)} active")

        # Every list action in one line above the list (ui/toolbar.py)
        draw_list_toolbar(layout, self)

        layout.separator(factor=1.0)

        if len(self.pie_menus) == 0:
            col = layout.box().column(align=True)
            col.scale_y = 1.4
            col.label(text="No pie menus yet", icon='INFO')
            col.label(text="Create one with New above.")
        else:
            # One section per editor: a collapsible heading, then that
            # editor's pies as plain rows (ui/lists.py). Deliberately not a
            # template_list per section -- that widget always draws inside a
            # box, and six stacked boxes read as six panels, not one list.
            collapsed = collapsed_group_keys(self)
            groups = pie_menu_groups(self.pie_menus)
            for position, (key, label, indices) in enumerate(groups):
                if position > 0:
                    layout.separator(factor=0.8)

                is_open = key not in collapsed

                # The whole heading is the toggle. Unembossed so it still
                # reads as a heading rather than a button, with the triangle
                # showing which way it goes -- the same idiom Blender uses for
                # its own panel headers. Not dimmed: greyed headings were too
                # hard to read in the user's theme.
                heading = layout.row(align=True)
                heading.alignment = 'LEFT'
                op = heading.operator(
                    "cocopie.toggle_group",
                    text=f"{label}  ·  {len(indices)}",
                    icon='TRIA_DOWN' if is_open else 'TRIA_RIGHT',
                    emboss=False)
                op.group_key = key

                if not is_open:
                    continue

                rows = layout.column(align=True)
                for index in indices:
                    draw_pie_row(rows, self, self.pie_menus[index], index,
                                 index == self.active_pie_index)



    def draw_right_column(self, layout):
        """Draw the right column with pie editor"""
        if len(self.pie_menus) == 0 or self.active_pie_index >= len(self.pie_menus):
            col = layout.box().column(align=True)
            col.scale_y = 1.8
            col.label(text="Nothing selected", icon='HAND')
            col.label(text="Pick a pie menu on the left, or create a new one.")
            return

        pie = self.pie_menus[self.active_pie_index]

        # Settings: Menu, Shortcut, and the conflicts box only when there is one
        self.draw_pie_settings(layout, pie)

        layout.separator()

        # Items
        self.draw_pie_items(layout, pie)

    def draw_pie_settings(self, layout, pie):
        """Draw pie menu settings: Menu and Quick Tap side by side, then
        Shortcut"""
        top = layout.split(factor=0.5)
        self.draw_menu_box(top.column(), pie)
        self.draw_quick_tap_box(top.column(), pie)
        self.draw_shortcut_box(layout, pie)
        self.draw_external_conflicts(layout, pie)

    def draw_menu_box(self, layout, pie):
        """Name, style and the editors the pie is live in"""
        box = layout.box()
        box.label(text="Menu", icon='GREASEPENCIL')
        col = box.column()

        # Name, Style and Editors share one width, packed left, so the three
        # fields end on the same line instead of Name and Editors running to
        # the far edge of the box
        row = _labelled(col, "Name", MENU_LABEL_FACTOR)
        row.alignment = 'LEFT'
        field = row.row(align=True)
        field.ui_units_x = MENU_FIELD_UNITS
        field.prop(pie, "name", text="")

        # Pie or dropdown, side by side at a fixed width. Right under Name
        # because it changes what every setting below means -- slot positions
        # become list order under List, and the eight compass directions stop
        # being directions.
        row = _labelled(col, "Style", MENU_LABEL_FACTOR)
        row.alignment = 'LEFT'
        style = row.row(align=True)
        style.ui_units_x = MENU_FIELD_UNITS
        style.prop(pie, "menu_style", expand=True)

        # Every editor this pie is live in, as one button showing them all.
        # It opens the Editors popover (ui/editors.py), a checkbox per editor,
        # which stays open so several can be ticked in one go.
        row = _labelled(col, "Editors", MENU_LABEL_FACTOR)
        row.alignment = 'LEFT'
        field = row.row(align=True)
        field.ui_units_x = MENU_FIELD_UNITS
        field.popover("COCOPIE_PT_editors", text=editors_summary(pie))

    def draw_shortcut_box(self, layout, pie):
        """Key, modifiers, trigger and Quick Tap"""
        box = layout.box()
        box.label(text="Shortcut", icon='KEYINGSET')
        col = box.column()

        # Whole shortcut on one line: key, modifiers, trigger. Modifier order
        # and grouping (Any, Shift, Ctrl, Alt) matches Blender's own keymap
        # editor -- rna_keymap_ui.py's draw_kmi() draws kmi.any then
        # shift_ui/ctrl_ui/alt_ui in that order. Fixed widths, packed left, so
        # the modifiers sit next to the key instead of drifting to the far edge
        # of a wide window.
        row = _labelled(col, "Key")
        row.alignment = 'LEFT'
        key = row.row(align=True)
        key.ui_units_x = 8
        # Click, then press the whole shortcut: cocopie.capture_key records
        # the key with the modifiers held at that moment, so only a real key
        # can end up here, never typed text. Blender's own capture field
        # (prop(event=True)) cannot do this for an add-on setting -- it takes
        # the modifiers along only on a real keymap item, so pressing Shift
        # first recorded Shift on its own.
        capturing = pie_ops.capturing_pie_index == self.active_pie_index
        key.operator("cocopie.capture_key",
                     text=pie_ops.capture_text if capturing else _shortcut_label(pie),
                     depress=capturing).pie_index = self.active_pie_index
        row.separator(factor=0.6)
        mods = row.row(align=True)
        mods.ui_units_x = 12
        mods.prop(pie, "any_modifier", text="Any", toggle=True)
        mods.prop(pie, "shift", text="Shift", toggle=True)
        mods.prop(pie, "ctrl", text="Ctrl", toggle=True)
        mods.prop(pie, "alt", text="Alt", toggle=True)
        # No Win/Cmd toggle: the OS takes those combinations before Blender
        # sees them, so a pie bound there is unreachable. See utils.clear_oskey
        row.separator(factor=0.6)
        trigger = row.row(align=True)
        trigger.ui_units_x = 5
        # Quick Tap binds its own drag/tap pair regardless of this setting,
        # so it is greyed out rather than hidden -- the value is still there,
        # ready to apply again the moment Quick Tap is off.
        trigger.enabled = not pie.tap_toggle
        trigger.prop(pie, "event_value", text="")

        conflicts = find_shortcut_conflicts(self, pie, self.active_pie_index)
        if conflicts:
            names = ", ".join(conflicts[:3])
            if len(conflicts) > 3:
                names += f" (+{len(conflicts) - 3} more)"
            _labelled(col, "").label(text=f"Same shortcut as: {names}",
                                     icon='ERROR')

    def draw_quick_tap_box(self, layout, pie):
        """Quick Tap: the switch, what a tap does, and its detail.

        Replaces the Trigger entirely when on: pressing and moving opens the
        pie, a quick tap runs the tap action instead. It binds its own
        CLICK_DRAG / CLICK pair (keymaps._add_keymap_item), whatever the
        Trigger says.
        """
        box = layout.box()
        box.prop(pie, "tap_toggle", text="Quick Tap")

        col = box.column()
        col.enabled = pie.tap_toggle
        col.prop(pie, "tap_action", text="")
        # Only one of the two tap forms has anything to configure at a time
        detail = col.row(align=True)
        if pie.tap_action == 'COMMAND':
            detail.prop(pie, "tap_command", text="", icon='CONSOLE')
        else:
            detail.prop(pie, "tap_toggle_a", text="")
            detail.prop(pie, "tap_toggle_b", text="")

        # Also evens the box up with Menu beside it, which has one line more
        hint = box.row()
        hint.active = False
        hint.label(text="Tap the key for this, press and drag for the pie")

    def draw_external_conflicts(self, layout, pie):
        """Shortcuts owned by Blender or another addon, in a box of their own.

        Drawn only when there is one. Separate from, and quieter than, a
        CocoPies-vs-CocoPies clash: this one is usually not a mistake to fix
        but a fact to know about, and unlike that one CocoPies cannot resolve
        it by editing its own settings.
        """
        external = find_external_conflicts(pie)
        if not external:
            return

        box = layout.box()
        box.label(text=f"{format_shortcut(pie)} is also bound elsewhere",
                  icon='ERROR')
        col = box.column(align=True)
        hint = col.row()
        hint.active = False
        hint.label(text="Tick one to switch it off while CocoPies is on")
        for other in external:
            row = col.row(align=True)
            row.alignment = 'LEFT'
            # Greyed while suppressed, so a shortcut CocoPies is holding
            # off reads as off at a glance rather than only via its text.
            # `active` and not `enabled`: both dim the row, but `enabled`
            # also refuses clicks, which would leave a ticked box with no
            # way to untick it.
            row.active = not other['suppressed']
            # Ticked means "CocoPies is holding this off for me". Drawn as
            # an operator rather than a prop because the row is derived
            # from a live keyconfig scan, not from stored data -- there is
            # no property to point at until the box is ticked.
            toggle = row.operator(
                "cocopie.toggle_suppress_binding",
                text="",
                icon='CHECKBOX_HLT' if other['suppressed'] else 'CHECKBOX_DEHLT',
                emboss=False,
            )
            (toggle.keymap, toggle.idname_prop, toggle.key_type,
             toggle.value, toggle.menu_name, toggle.any_modifier,
             toggle.shift, toggle.ctrl, toggle.alt,
             toggle.oskey) = other['identity']
            # The detail is what the binding actually points at, and it is
            # only carried when the label does not already say it (see
            # _kmi_detail). Without it a tool shortcut read "Set Tool by
            # Name", naming the operator every tool binding shares and
            # leaving no way to tell which tool the checkbox would switch
            # off.
            name = other['label']
            if other['detail']:
                name = f"{name}: {other['detail']}"
            # Which addon, by name, whenever it can be worked out -- "some
            # addon has this key" leaves the user hunting through their
            # whole stack for it. The coarse source stays in front of it:
            # "Custom: MACHIN3tools" is a MACHIN3tools operator the user
            # bound by hand, which is a different thing to fix than one
            # MACHIN3tools ships.
            source = other['source']
            if other['owner']:
                source = f"{source}: {other['owner']}"
            label = f"{name}  ({source}, {other['keymap']})"
            if other['suppressed']:
                label += "  -- switched off by CocoPies"
            row.label(text=label)

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

        # Icon selector button. One square button per row, framed whatever it
        # holds -- a built-in icon, a PNG or nothing -- because every kind of
        # icon now draws the same way: centred inside the button at the same
        # size as Blender's own. That was not true while the brush icons were
        # triangle geometry, which drew half again as large as the button and
        # spilled out of it; the column used to carry a second, wider width and
        # drop the frame for those icons to hide it. Both went away with the
        # icons themselves (see previews.py).
        # The cell reserves the column so the header caption lines up with it;
        # scale_x is what actually sizes the button, since an icon-only button
        # sits at its natural one unit inside however wide a cell it is given.
        # Scaled by the same number as the row's height, so it comes out square.
        icon_cell = body.row(align=True)
        icon_cell.ui_units_x = COL_ICON_UNITS
        icon_btn = icon_cell.row(align=True)
        icon_btn.scale_x = ITEM_ROW_UNITS
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
