"""The right-click "Add to CocoPies" entry.

Built out of real nested Menus rather than chained popups. Clicking an entry
in a popup tears that popup down, and a second popup opened during the same
click is destroyed along with it -- which silently did nothing at all. A
submenu is drawn by the menu system instead of being spawned from a click, so
it is not subject to that teardown.

The trade-off is that a submenu's draw gets no arguments, so the button under
the cursor is captured while the *context menu itself* draws (where
`button_operator` / `button_prop` are still in context) and stashed in
`_CAPTURED` for the submenus to read.
"""

import bpy
import re
from bpy.props import StringProperty, IntProperty, BoolProperty
from bpy.types import Operator, Menu
from ..items import POSITION_NAMES
from ..utils import (
    ADDON_ID, get_prefs, get_pie, ensure_slot_items, slot_is_used,
)
from ..keymaps import register_pie_menus


# What the cursor was over when the context menu last drew. Written by
# menu_func_context, read by the submenus and baked into the operator buttons
# they draw. A dict rather than separate globals so it is cleared atomically.
_CAPTURED = {}

# Direction submenus need one registered class each, since a Menu's draw
# receives no arguments and so cannot be told which pie it belongs to. The
# pie count is user-driven, so a pool is registered up front and indexed.
MAX_PIE_SUBMENUS = 32


def _capture_button(context):
    """Describe the button under the cursor, or None if it is not capturable.

    Returns a dict of the operator/property payload the add operator needs.
    Called during the context menu's draw, so it must not mutate anything.
    """
    # Case 1: Operator button
    button_op = getattr(context, 'button_operator', None)
    if button_op:
        op_string = button_op.bl_rna.identifier
        if '.' in op_string:
            parts = op_string.split('.')
            op_string = '.'.join(parts[-2:]) if len(parts) > 1 else op_string
        return {
            'operator_string': op_string,
            'prop_label': "",
            'is_property': False,
        }

    # Case 2: Property button (overlay toggles, etc.)
    button_pointer = getattr(context, 'button_pointer', None)
    button_prop = getattr(context, 'button_prop', None)
    if not (button_pointer and button_prop):
        return None

    try:
        data_path = button_pointer.path_from_id()
    except Exception:
        data_path = None

    prop_id = button_prop.identifier
    if not (data_path and prop_id):
        return None

    prop_type = button_prop.type

    # An area-specific path is meaningless from a pie invoked elsewhere, so
    # rewrite it to the equivalent context path:
    #   "areas[2].spaces[0].overlay" -> "bpy.context.space_data.overlay"
    clean_path = re.sub(
        r'areas\[\d+\]\.spaces\[\d+\]', 'bpy.context.space_data', data_path)
    clean_path = re.sub(
        r'screens\[\w+\]\.areas\[\d+\]\.spaces\[\d+\]',
        'bpy.context.space_data', clean_path)

    full_prop_path = f"{clean_path}.{prop_id}"

    if prop_type in ('INT', 'FLOAT'):
        try:
            op_string = f"{full_prop_path} = {getattr(button_pointer, prop_id)}"
        except Exception:
            op_string = f"{full_prop_path} = 0"
    elif prop_type == 'ENUM':
        try:
            op_string = f"{full_prop_path} = '{getattr(button_pointer, prop_id)}'"
        except Exception:
            op_string = f"{full_prop_path} = ''"
    else:
        # BOOLEAN and anything else toggle-shaped
        op_string = f"{full_prop_path} = not {full_prop_path}"

    return {
        'operator_string': op_string,
        'prop_label': prop_id.replace('_', ' ').title(),
        'is_property': True,
    }


def _items_by_position(pie):
    """Map slot -> item without mutating the pie.

    ensure_slot_items() would fill in the missing slots, but it writes to the
    collection and this runs inside a menu draw. The add operator calls it
    before assigning, so the slots exist by the time anything is written.
    """
    by_pos = {}
    for item in pie.items:
        by_pos.setdefault(item.position, item)
    return by_pos


class COCOPIE_MT_add_to_cocopie(Menu):
    """The pie list: one submenu per configured pie menu"""
    bl_idname = "COCOPIE_MT_add_to_cocopie"
    bl_label = "Add to CocoPies"

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)

        if prefs is None or len(prefs.pie_menus) == 0:
            layout.label(text="No pie menus created yet", icon='INFO')
            return

        for i, pie in enumerate(prefs.pie_menus):
            if i >= MAX_PIE_SUBMENUS:
                row = layout.row()
                row.enabled = False
                row.label(text=f"...and {len(prefs.pie_menus) - i} more", icon='INFO')
                break
            layout.menu(f"COCOPIE_MT_cocopie_dirs_{i}", text=pie.name, icon='MENU_PANEL')


def _make_direction_menu(index):
    """Build the direction submenu class for one pie slot in the pool"""

    class _DirectionMenu(Menu):
        bl_idname = f"COCOPIE_MT_cocopie_dirs_{index}"
        bl_label = "Choose Direction"
        pie_index = index

        def draw(self, context):
            layout = self.layout
            pie = get_pie(context, self.pie_index)

            if pie is None:
                layout.label(text="Pie menu no longer exists", icon='ERROR')
                return
            if not _CAPTURED:
                layout.label(text="Nothing captured", icon='ERROR')
                return

            by_pos = _items_by_position(pie)

            for position in range(8):
                item = by_pos.get(position)
                used = item is not None and slot_is_used(item)
                label = item.label if (used and item.label) else "Empty"
                op = layout.operator(
                    "cocopie.add_operator_to_pie",
                    text=f"{POSITION_NAMES[position]}:  {label}",
                    icon='RADIOBUT_ON' if used else 'RADIOBUT_OFF',
                )
                op.pie_index = self.pie_index
                op.position = position
                op.operator_string = _CAPTURED.get('operator_string', "")
                op.prop_label = _CAPTURED.get('prop_label', "")
                op.is_property = _CAPTURED.get('is_property', False)

    _DirectionMenu.__name__ = f"COCOPIE_MT_cocopie_dirs_{index}"
    return _DirectionMenu


DIRECTION_MENUS = tuple(_make_direction_menu(i) for i in range(MAX_PIE_SUBMENUS))


class COCOPIE_OT_add_operator_to_pie(Operator):
    """Add the captured button to this direction of the pie menu"""
    bl_idname = "cocopie.add_operator_to_pie"
    bl_label = "Add to Pie Direction"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    pie_index: IntProperty()
    position: IntProperty(default=-1)
    operator_string: StringProperty()
    prop_label: StringProperty(default="")
    is_property: BoolProperty(default=False)

    def invoke(self, context, event):
        # Overwriting an existing assignment is confirmed first; claiming an
        # empty direction is immediate.
        pie = get_pie(context, self.pie_index)
        if pie is not None:
            existing = _items_by_position(pie).get(self.position)
            if existing is not None and slot_is_used(existing):
                return context.window_manager.invoke_confirm(
                    self, event,
                    title="Replace Direction",
                    message=f'Replace "{existing.label}" on {POSITION_NAMES[self.position]}?',
                    confirm_text="Replace",
                    icon='WARNING',
                )
        return self.execute(context)

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None or not (0 <= self.pie_index < len(prefs.pie_menus)):
            return {'CANCELLED'}
        if not self.operator_string:
            self.report({'WARNING'}, "Nothing was captured from that button")
            return {'CANCELLED'}

        pie = prefs.pie_menus[self.pie_index]

        # Every pie carries all eight directions. A caller that already knows
        # which one to use passes it in position; otherwise fall back to the
        # first unused one.
        ensure_slot_items(pie)
        if 0 <= self.position < len(pie.items):
            item = pie.items[self.position]
        else:
            item = next((it for it in pie.items if not slot_is_used(it)), None)

        if item is None:
            self.report({'WARNING'}, f"{pie.name} has no free direction (8 of 8 used)")
            return {'CANCELLED'}

        item.icon = "NONE"
        item.enabled = True

        if self.is_property:
            item.command = self.operator_string
            item.label = self.prop_label or self.operator_string.split('.')[-1].split(' ')[0].replace('_', ' ').title()

        elif 'MT_' in self.operator_string or '_MT_' in self.operator_string:
            menu_class = self.operator_string
            item.label = menu_class.replace('VIEW3D_MT_', '').replace('_MT_', ' ').replace('_', ' ').title()
            item.command = f"bpy.ops.wm.call_menu(name='{menu_class}')"

        else:
            op_name = self.operator_string
            if '_OT_' in op_name:
                parts = op_name.split('_OT_')
                if len(parts) == 2:
                    op_name = f"{parts[0].lower()}.{parts[1].lower()}"
            else:
                op_name = op_name.lower()
            item.label = op_name.split('.')[-1].replace('_', ' ').title()
            item.command = f"bpy.ops.{op_name}()"

        register_pie_menus()
        self.report({'INFO'}, f"Added '{item.label}' to {pie.name} ({POSITION_NAMES[self.position]})")
        return {'FINISHED'}


def menu_func_context(self, context):
    """Add the 'Add to CocoPies' submenu to the button right-click menu"""
    captured = _capture_button(context)
    if not captured:
        return

    # Stashed here rather than passed along, because a submenu's draw takes no
    # arguments. Safe because only one context menu is ever open at a time.
    _CAPTURED.clear()
    _CAPTURED.update(captured)

    layout = self.layout
    layout.separator()
    layout.menu("COCOPIE_MT_add_to_cocopie", text="Add to CocoPies", icon='MENU_PANEL')
