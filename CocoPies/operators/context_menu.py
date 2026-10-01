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

import re
import bpy
import mathutils
from bpy.props import StringProperty, IntProperty, EnumProperty
from bpy.types import Operator, Menu
from ..items import POSITION_NAMES
from ..utils import (
    get_prefs, get_pie, ensure_slot_items, slot_is_used,
    holding_rebuilds, unused_pie_name, unused_pie_idname,
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


def _python_literal(value):
    """Source text that evaluates back to value, or None when there is none.

    Covers what a property or an operator option holds: numbers, strings,
    enum sets, arrays (vectors, colours, matrices, flag rows) and data-blocks,
    which are written the way Blender itself prints them,
    bpy.data.objects['Cube']. Floats keep six significant digits, so 0.1
    stays 0.1 rather than the 0.10000000149011612 a float32 reads back as.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return repr(value)
    if isinstance(value, float):
        return repr(float(f"{value:.6g}"))
    if isinstance(value, (set, frozenset)):
        return repr(set(sorted(value))) if value else "set()"
    if isinstance(value, bpy.types.ID):
        text = repr(value)
        return text if text.startswith("bpy.data.") else None
    if isinstance(value, bpy.types.bpy_struct):
        return None
    if isinstance(value, mathutils.Matrix):
        # Reads back as rows, but a matrix property takes a nested sequence
        # as columns
        value = value.transposed()
    try:
        parts = [_python_literal(v) for v in value]
    except TypeError:
        return None
    if None in parts:
        return None
    return "(" + ", ".join(parts) + ("," if len(parts) == 1 else "") + ")"


# Where a data-block is reached from the context rather than by its name, so
# a slot follows whatever is active when the pie opens: the proportional
# editing of the scene in front of you, the modifier of the selected object.
# Checked in order; a block that is none of these is named, which is right
# for things that exist once (one particular material's node, a brush).
_CONTEXT_OWNERS = (
    ("scene",),
    ("object",),
    ("object", "data"),
    ("object", "active_material"),
    ("object", "active_material", "node_tree"),
    ("scene", "world"),
    ("scene", "world", "node_tree"),
    ("workspace",),
    ("window_manager",),
)

# Structs a button can sit on that have no path from their data-block
_CONTEXT_STRUCTS = (
    ("region_data",),
    ("space_data",),
    ("area",),
    ("region",),
)


def _context_value(context, attrs):
    value = context
    for attr in attrs:
        value = getattr(value, attr, None)
        if value is None:
            return None
    return value


def _pointer_path(owner, pointer, depth=2):
    """The attribute path from owner down to pointer, following plain
    pointers only, or None.

    For structs Blender cannot give a path for itself: the scene's Display
    settings (Workbench's light and shadow, viewport anti-aliasing) say
    "does not support path creation".
    """
    for prop in owner.bl_rna.properties:
        if prop.type != 'POINTER' or prop.identifier == "rna_type":
            continue
        child = getattr(owner, prop.identifier, None)
        if child is None or isinstance(child, bpy.types.ID):
            continue
        if child == pointer:
            return prop.identifier
        if depth > 1:
            below = _pointer_path(child, pointer, depth - 1)
            if below is not None:
                return f"{prop.identifier}.{below}"
    return None


def _struct_path(context, pointer):
    """Python source that reaches pointer from bpy, or None.

    path_from_id() is relative to the data-block that owns the struct:
    "tool_settings" for the scene's tool settings, "areas[2].spaces[0].overlay"
    for a viewport's overlays. On its own it is not something Python can run
    -- a slot holding "tool_settings.proportional_edit_falloff" failed with
    "name 'tool_settings' is not defined" -- so the owner goes in front.
    """
    id_data = pointer.id_data
    if id_data is None:
        # Not inside any data-block. The Preferences are where such a button
        # lives, one level down (View, Interface, Input...).
        prefs = context.preferences
        if pointer == prefs:
            return "bpy.context.preferences"
        for prop in prefs.bl_rna.properties:
            if prop.type == 'POINTER' and getattr(prefs, prop.identifier, None) == pointer:
                return f"bpy.context.preferences.{prop.identifier}"
        return None

    if pointer == id_data:
        path = ""
    else:
        try:
            path = pointer.path_from_id()
        except ValueError:
            path = _pointer_path(id_data, pointer)
        if path is None:
            # Not reachable from its data-block, like the 3D View's own view
            # (Lock Camera to View, Clip Region): only through the context
            return next(("bpy.context." + ".".join(attrs) for attrs in _CONTEXT_STRUCTS
                         if _context_value(context, attrs) == pointer), None)

    if isinstance(id_data, bpy.types.Screen):
        # An area's index means nothing from a pie opened somewhere else: the
        # pie acts on the editor it is opened over.
        for pattern, owner in ((r'areas\[\d+\]\.spaces\[\d+\]', "bpy.context.space_data"),
                               (r'areas\[\d+\]', "bpy.context.area")):
            match = re.match(pattern, path)
            if match:
                return owner + path[match.end():]
        owner = "bpy.context.screen"
    else:
        owner = next(("bpy.context." + ".".join(attrs) for attrs in _CONTEXT_OWNERS
                      if _context_value(context, attrs) == id_data), None)
        if owner is None:
            owner = _python_literal(id_data)
            if owner is None:
                return None

    if not path:
        return owner
    return owner + ("" if path.startswith("[") else ".") + path


class _BpyInContext:
    """bpy, with bpy.context standing for the context menu's own context"""

    def __init__(self, context):
        self.context = context

    def __getattr__(self, name):
        return getattr(bpy, name)


def _reaches(context, path, pointer):
    """Whether path, run the way a pie runs it, lands on pointer right now.

    The last check before a capture is offered: a path that does not reach
    the right-clicked button from its own editor would not work from a pie
    either, so the entry is left out rather than written as a broken slot.
    """
    try:
        return eval(path, {"bpy": _BpyInContext(context)}) == pointer
    except Exception:
        return False


def _operator_command(button_op):
    """The bpy.ops call a right-clicked operator button runs, or None.

    The options the button sets are kept: Select Mode's Edge, a menu's Add
    Modifier > Subdivision Surface. Up to 1.14.0 only the operator's name was
    kept, so such a slot ran with the defaults instead.

    It is invoked, as the button was: an operator whose invoke() prepares
    what its execute() reads (Mio3 UV's Sort) fails when only executed, a
    modal one (Move in the Object menu) does nothing, and one that asks
    first (Delete) should still ask.
    """
    identifier = button_op.bl_rna.identifier
    if '_OT_' not in identifier:
        return None
    module, name = identifier.split('_OT_', 1)
    args = [repr('INVOKE_DEFAULT')]
    for prop in button_op.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type" or not button_op.is_property_set(ident):
            continue
        literal = _python_literal(getattr(button_op, ident, None))
        if literal is not None:
            args.append(f"{ident}={literal}")
    return f"bpy.ops.{module.lower()}.{name.lower()}({', '.join(args)})"


def _property_capture(context, pointer, prop):
    """The capture for a right-clicked property, or None"""
    if prop.is_readonly or prop.type == 'COLLECTION':
        return None
    owner = _struct_path(context, pointer)
    if owner is None or not _reaches(context, owner, pointer):
        return None
    target = f"{owner}.{prop.identifier}"
    label = prop.name
    if not label or label == prop.identifier:
        # A node input's value has no name of its own: the input's is the
        # one on screen ("Roughness")
        label = getattr(pointer, "name", "") or prop.identifier.replace('_', ' ').title()

    try:
        value = getattr(pointer, prop.identifier)
    except Exception:
        return None

    # One field of a row (Location's X) is right-clicked on its own, and is
    # what the slot sets. context.property carries its index.
    is_array = getattr(prop, "is_array", False)
    index = (getattr(context, "property", None) or (None, None, -1))[2]
    if is_array and index >= 0 and tuple(prop.array_dimensions)[1:2] == (0,):
        target = f"{target}[{index}]"
        value = value[index]
        is_array = False
        if prop.array_length <= 4:
            channels = "RGBA" if prop.subtype in {'COLOR', 'COLOR_GAMMA'} else "XYZW"
            label = f"{label} {channels[index]}"

    if prop.type == 'BOOLEAN' and not is_array:
        # A switch: flip it, as clicking it does
        return {'command': f"{target} = not {target}", 'label': label}

    if prop.type == 'ENUM' and not prop.is_enum_flag:
        if not value:
            # No current choice (the Image Editor's Mode while it shows UVs)
            return None
        # Blender passes the property but not which of its choices is under
        # the cursor -- right-clicking Random in a row whose current choice
        # is Smooth gives Smooth -- so the choice is asked for when the slot
        # is added, starting from the current one. The strings are held here
        # for the dropdown that shows them.
        choices = [(item.identifier, item.name, item.description, item.icon, i)
                   for i, item in enumerate(prop.enum_items)]
        if value in {c[0] for c in choices}:
            return {'command': f"{target} = {value!r}", 'label': label,
                    'enum_target': target, 'enum_value': value, 'choices': choices}
        # A list built while drawing (View Transform, Length unit, the
        # studio lights) cannot be listed from here: the current choice it is
        name = bpy.types.UILayout.enum_item_name(pointer, prop.identifier, value)
        return {'command': f"{target} = {value!r}", 'label': name or label}

    literal = _python_literal(value)
    if literal is None:
        return None
    return {'command': f"{target} = {literal}", 'label': label}


def _capture_button(context):
    """Describe the button under the cursor, or None if it is not capturable.

    Returns a dict holding the finished slot's 'command' and 'label', plus,
    for a choice property, what the value dropdown needs. Called during the
    context menu's draw, so it must not mutate anything.
    """
    button_op = getattr(context, 'button_operator', None)
    if button_op:
        command = _operator_command(button_op)
        if command is None:
            return None
        rna = button_op.bl_rna
        label = rna.name or rna.identifier.split('_OT_')[-1].replace('_', ' ').title()
        return {'command': command, 'label': label}

    pointer = getattr(context, 'button_pointer', None)
    prop = getattr(context, 'button_prop', None)
    if not (pointer and prop):
        return None
    return _property_capture(context, pointer, prop)


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


def _write_capture(item, command, label):
    """Put a captured button into a slot.

    Shared by both entry points -- assigning to an existing pie's direction,
    and creating a new pie around the button -- so the two cannot disagree
    about what a given button becomes. Returns the label it settled on.
    """
    item.icon = "NONE"
    item.enabled = True
    item.command = command
    item.label = label or "Item"
    return item.label


# The choices offered by the value dropdown of the add dialog that is open.
# Copied out of _CAPTURED when the dialog opens, since the next right-click
# redraws that, and held here because Blender keeps only pointers to a
# dynamic enum's strings.
_DIALOG_CHOICES = []


def _dialog_choices(self, context):
    return _DIALOG_CHOICES or [("NONE", "None", "")]


def _prepare_choice(op):
    """Fill op's value dropdown from the capture, starting at its current choice"""
    _DIALOG_CHOICES[:] = _CAPTURED.get('choices', [])
    value = _CAPTURED.get('enum_value')
    if any(choice[0] == value for choice in _DIALOG_CHOICES):
        op.value = value


def _chosen_slot(op):
    """(command, label) the add operator writes: as captured, or with the
    choice picked in its dialog"""
    if not op.enum_target:
        return op.command, op.label
    label = next((c[1] for c in _DIALOG_CHOICES if c[0] == op.value), op.value)
    return f"{op.enum_target} = {op.value!r}", label


class COCOPIE_MT_add_to_cocopie(Menu):
    """The pie list: one submenu per configured pie menu"""
    bl_idname = "COCOPIE_MT_add_to_cocopie"
    bl_label = "Add to CocoPies"

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)

        # Offered first, and offered even when no pie exists yet -- it is the
        # only entry that is useful in that state.
        op = layout.operator(
            "cocopie.add_to_new_pie", text="Add a New Pie...", icon='ADD')
        op.command = _CAPTURED.get('command', "")
        op.label = _CAPTURED.get('label', "")
        op.enum_target = _CAPTURED.get('enum_target', "")
        layout.separator()

        if prefs is None or len(prefs.pie_menus) == 0:
            row = layout.row()
            row.enabled = False
            row.label(text="No pie menus created yet", icon='INFO')
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
                op.command = _CAPTURED.get('command', "")
                op.label = _CAPTURED.get('label', "")
                op.enum_target = _CAPTURED.get('enum_target', "")

    _DirectionMenu.__name__ = f"COCOPIE_MT_cocopie_dirs_{index}"
    return _DirectionMenu


DIRECTION_MENUS = tuple(_make_direction_menu(i) for i in range(MAX_PIE_SUBMENUS))


class COCOPIE_OT_add_operator_to_pie(Operator):
    """Add the captured button to this direction of the pie menu"""
    bl_idname = "cocopie.add_operator_to_pie"
    bl_label = "Add to Pie Direction"
    bl_options = {'INTERNAL'}

    pie_index: IntProperty()
    position: IntProperty(default=-1)
    replacing: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    command: StringProperty()
    label: StringProperty(default="")
    # Set for a choice property: the slot then sets it to value
    enum_target: StringProperty()
    value: EnumProperty(name="Value", items=_dialog_choices)

    def invoke(self, context, event):
        # Overwriting an existing assignment is confirmed first; claiming an
        # empty direction is immediate, unless there is a choice to make.
        pie = get_pie(context, self.pie_index)
        existing = _items_by_position(pie).get(self.position) if pie is not None else None
        self.replacing = existing.label if existing is not None and slot_is_used(existing) else ""
        if self.enum_target:
            _prepare_choice(self)
            return context.window_manager.invoke_props_dialog(
                self, width=300, title="Add to Pie Direction",
                confirm_text="Replace" if self.replacing else "Add")
        if self.replacing:
            return context.window_manager.invoke_confirm(
                self, event,
                title="Replace Direction",
                message=f'Replace "{self.replacing}" on {POSITION_NAMES[self.position]}?',
                confirm_text="Replace",
                icon='WARNING',
            )
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "value")
        if self.replacing:
            layout.label(text=f'Replaces "{self.replacing}" on {POSITION_NAMES[self.position]}',
                         icon='WARNING')

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None or not (0 <= self.pie_index < len(prefs.pie_menus)):
            return {'CANCELLED'}
        if not self.command:
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

        _write_capture(item, *_chosen_slot(self))

        register_pie_menus()
        # item.position, not self.position: that is -1 when no direction was
        # asked for, and naming it raised after the item had been written
        self.report({'INFO'}, f"Added '{item.label}' to {pie.name} ({POSITION_NAMES[item.position]})")
        return {'FINISHED'}


class COCOPIE_OT_add_to_new_pie(Operator):
    """Create a new pie menu with the captured button on its first direction"""
    bl_idname = "cocopie.add_to_new_pie"
    bl_label = "Add to a New Pie"
    bl_options = {'INTERNAL'}

    name: StringProperty(
        name="Name",
        description="Name for the new pie menu",
        default="",
    )
    command: StringProperty()
    label: StringProperty(default="")
    # Set for a choice property: the slot then sets it to value
    enum_target: StringProperty()
    value: EnumProperty(name="Value", items=_dialog_choices)

    def invoke(self, context, event):
        # The name is asked for up front rather than assigned and renamed
        # afterwards: renaming is only possible in the Preferences pie list,
        # and not having to go there is the point of this entry.
        prefs = get_prefs(context)
        self.name = unused_pie_name(prefs) if prefs is not None else "Pie Menu 1"
        if self.enum_target:
            _prepare_choice(self)
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        self.layout.prop(self, "name")
        if self.enum_target:
            self.layout.prop(self, "value")

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            return {'CANCELLED'}
        if not self.command:
            self.report({'WARNING'}, "Nothing was captured from that button")
            return {'CANCELLED'}

        name = self.name.strip() or unused_pie_name(prefs)
        idname = unused_pie_idname(prefs)
        pie = prefs.pie_menus.add()
        with holding_rebuilds():
            pie.name = name
            pie.idname = idname
            # No shortcut, as the report below says. The property's default
            # is Q, which bound every new pie to Q in every editor -- taking
            # Blender's Quick Favorites with it.
            pie.key = ""

            ensure_slot_items(pie)
            label = _write_capture(pie.items[0], *_chosen_slot(self))

        prefs.active_pie_index = len(prefs.pie_menus) - 1
        register_pie_menus()

        # The new pie has no shortcut yet, so say so rather than leaving a pie
        # that exists but cannot be opened.
        self.report({'INFO'},
                    f"Created '{pie.name}' with '{label}' on "
                    f"{POSITION_NAMES[0]} -- set its shortcut in Preferences")
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
