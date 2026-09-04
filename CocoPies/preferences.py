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
    SCOPE_COLUMNS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut, oskey_label,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
    ensure_slot_items, slot_is_used, ensure_keymap_scopes,
    addon_version_string, find_external_conflicts, pie_menu_groups,
    collapsed_group_keys,
)
from .icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)
from .keymaps import register_pie_menus, unregister_pie_menus
from .previews import slot_button_args, icon_args
from .properties import COCOPIE_PieMenuItem, COCOPIE_PieMenuData, COCOPIE_SuppressedBinding
from .ui import draw_pie_row


def icon_column_units(pie):
    """How wide the Icon column is for this pie.

    One square, the same for every pie and every row. Kept as a function
    because the table header and the rows both have to agree on it, and it used
    to differ per pie: an icon loaded as triangle geometry drew wider than its
    button, so a pie holding one widened the whole column. Nothing draws that
    way any more (see previews.py), so there is one width again.
    """
    return COL_ICON_UNITS


def _equal_slots(parent, count):
    """`count` equal-width slots across one line, filled or not.

    Blender has no layout that reserves a fixed share for a cell that may not
    exist: grid_flow sizes itself to the cells it is actually given, so a line
    holding fewer than `count` stretches them to fill it. Nested splits do
    reserve it -- each split's factor is applied whether or not anything is
    drawn into that side -- so a part-filled last line keeps its cells the same
    width as a full line's.

    Each pass splits off one slot's worth of whatever is left: 1/3 of the line,
    then 1/2 of the remaining 2/3, and the final slot takes the rest.
    """
    slots = []
    node = parent
    for i in range(count - 1):
        node = node.split(factor=1.0 / (count - i), align=True)
        slots.append(node.row(align=True))
    slots.append(node.row(align=True))
    return slots


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

        if len(self.pie_menus) == 0:
            col = layout.box().column(align=True)
            col.scale_y = 1.4
            col.label(text="No pie menus yet", icon='INFO')
            col.label(text="Create one with the button below.")
        else:
            # One section per editor: a collapsible heading, then that
            # editor's pies as plain rows. Deliberately not a template_list
            # per section -- that widget always draws inside a box, and six
            # stacked boxes read as six panels rather than one list.
            collapsed = collapsed_group_keys(self)
            groups = pie_menu_groups(self.pie_menus)
            for position, (key, label, indices) in enumerate(groups):
                if position > 0:
                    layout.separator(factor=0.35)

                is_open = key not in collapsed

                # The whole heading is the toggle. Unembossed so it still
                # reads as a heading rather than a button, with the triangle
                # showing which way it goes -- the same idiom Blender uses for
                # its own panel headers.
                heading = layout.row(align=True)
                heading.alignment = 'LEFT'
                op = heading.operator(
                    "cocopie.toggle_group",
                    text=f"{label.upper()}  ({len(indices)})",
                    icon='TRIA_DOWN' if is_open else 'TRIA_RIGHT',
                    emboss=False)
                op.group_key = key

                if not is_open:
                    continue

                rows = layout.column(align=True)
                for index in indices:
                    draw_pie_row(rows, self, self.pie_menus[index], index,
                                 index == self.active_pie_index)

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
        # Pie or dropdown. Right under Name because it changes what every other
        # setting below means -- slot positions become list order under List,
        # and the eight compass directions stop being directions.
        col.prop(pie, "menu_style", text="Style", expand=True)

        col.separator(factor=0.5)

        # Every editor this pie is live in.
        #
        # This block deliberately steps out of use_property_split: the label
        # column that suits single-widget rows like Name would squeeze the grid
        # into the right-hand ~65% and leave the dropdowns narrower than the
        # editor names in them. "Editor" is written as a plain label on its own
        # line instead, and the grid below spans the full width of the box.
        #
        # Every grid cell holds the same two widgets, dropdown then its own
        # remove button, and Add Editor flows as the cell straight after the
        # last one. Cell uniformity is what keeps grid_flow honest -- it lays
        # out by cell, so an odd cell out (the + used to live in the first one)
        # gets shuffled onto a line of its own and detaches an editor from its
        # row.
        scopes = ensure_keymap_scopes(pie)
        pie_index = self.active_pie_index

        scope_area = col.column(align=True)
        scope_area.use_property_split = False

        # Label and Add Editor share the header line, packed left.
        # alignment='LEFT' is what keeps both to their content width instead of
        # the button stretching across the rest of the line.
        header = scope_area.row(align=True)
        header.alignment = 'LEFT'
        header.label(text="Editor")
        header.operator("cocopie.add_keymap_scope", text="Add Editor",
                        icon='ADD').pie_index = pie_index

        # Fixed-width cells, SCOPE_COLUMNS to a line, wrapping onto a new line
        # after that. Built from nested splits rather than grid_flow: grid_flow
        # only creates as many columns as it has cells to put in them and then
        # stretches those to fill the line, so two editors came out half the
        # box wide each instead of holding a third. A split's factor sets the
        # width whether or not anything is drawn into it, which is what lets a
        # part-filled last line keep its cells the same size as a full one's.
        scope_list = list(scopes)
        for start in range(0, len(scope_list), SCOPE_COLUMNS):
            chunk = scope_list[start:start + SCOPE_COLUMNS]
            for offset, slot in enumerate(_equal_slots(scope_area.row(align=True),
                                                       SCOPE_COLUMNS)):
                if offset >= len(chunk):
                    # Empty tail slot: the split already reserved its width, so
                    # this only has to occupy it without drawing anything
                    slot.label(text="")
                    continue
                scope_index = start + offset
                slot.prop(chunk[offset], "keymap_type", text="")
                remove = slot.row(align=True)
                # The last remaining editor is not removable: a pie scoped
                # nowhere would be registered nowhere, with nothing in the UI
                # to get back from. Greyed rather than hidden so the cells keep
                # their shape.
                remove.enabled = len(scope_list) > 1
                op = remove.operator("cocopie.remove_keymap_scope",
                                     text="", icon='REMOVE')
                op.pie_index = pie_index
                op.scope_index = scope_index

        col.separator(factor=0.5)

        # Whole shortcut stays on one line: trigger + modifiers + key.
        # Modifier order and grouping (Any, Shift, Ctrl, Alt, OS) matches
        # Blender's own keymap editor exactly -- see rna_keymap_ui.py's
        # draw_kmi(), which draws kmi.any then shift_ui/ctrl_ui/alt_ui/oskey_ui
        # in that order.
        row = col.row(align=True, heading="Shortcut")
        trigger = row.row(align=True)
        trigger.scale_x = 0.9
        # Tap to Toggle drives its own hold/tap timing regardless of this
        # setting, so it is greyed out rather than hidden -- the value is
        # still there, ready to apply again the moment Tap to Toggle is off.
        trigger.enabled = not pie.tap_toggle
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

        # Shortcuts owned by Blender or another addon. Reported separately and
        # more quietly than a CocoPies-vs-CocoPies clash: this one is usually not
        # a mistake to fix but a fact to know about, and unlike the check above
        # CocoPies cannot resolve it by editing its own settings.
        external = find_external_conflicts(pie)
        if external:
            ext_box = box.box()
            ext_box.scale_y = 0.8
            header = ext_box.row()
            header.label(
                text=f"{format_shortcut(pie)} is also bound elsewhere "
                     f"(tick to switch off while CocoPies is on):",
                icon='INFO',
            )
            for other in external:
                row = ext_box.row(align=True)
                row.alignment = 'LEFT'
                # Greyed while suppressed, so a shortcut CocoPies is holding
                # off reads as off at a glance rather than only via its text.
                # `active` and not `enabled`: both dim the row, but `enabled`
                # also refuses clicks, which would leave a ticked box with no
                # way to untick it. This is Blender's own idiom for a field
                # dimmed by a toggle above it -- still editable.
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
                    label += "  -- disabled by CocoPies"
                row.label(text=label)

        # Replaces the Trigger entirely when on: holding the key opens the
        # pie, a quick tap alternates between the two chosen directions
        # instead. Not restricted to a particular Trigger -- it supplies its
        # own hold/tap timing (see COCOPIE_OT_hold_or_tap), since keyboard
        # keys have no built-in event value for that distinction.
        col.separator(factor=0.5)
        tt = col.row(align=True, heading="Quick Tap")
        tt.prop(pie, "tap_toggle", text="")
        action = tt.row(align=True)
        action.enabled = pie.tap_toggle
        action.prop(pie, "tap_action", text="")

        # Only one of the two tap forms has anything to configure at a time,
        # and an empty row here would just look like something failed to draw
        # Split by hand rather than with heading="": under use_property_split
        # every prop() claims the value column for itself, so a second one on
        # the same row wraps to its own line -- and a sub-row does not help,
        # since the setting is inherited by children. Turning the split off
        # and placing the label column explicitly is what keeps a pair of
        # fields side by side and still aligned with the rows above.
        # Compared against three other arrangements in a real window.
        detail = col.row(align=True)
        detail.enabled = pie.tap_toggle
        detail.use_property_split = False
        halves = detail.split(factor=0.4)
        halves.label(text="")
        fields = halves.row(align=True)
        if pie.tap_action == 'COMMAND':
            fields.prop(pie, "tap_command", text="", icon='CONSOLE')
        else:
            fields.prop(pie, "tap_toggle_a", text="")
            fields.prop(pie, "tap_toggle_b", text="")

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
        icon_units = icon_column_units(pie)
        self.draw_item_header(table, icon_units)
        for index, item in enumerate(pie.items):
            self.draw_single_item(table, pie, item, index, icon_units)

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

    def draw_item_header(self, layout, icon_units=COL_ICON_UNITS):
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
        cell.ui_units_x = icon_units
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

    def draw_single_item(self, layout, pie, item, index, icon_units=COL_ICON_UNITS):
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
        icon_cell.ui_units_x = icon_units
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
