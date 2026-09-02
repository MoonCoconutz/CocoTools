"""Builds the Blender Menu class that actually draws a pie."""

import ast
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
from .utils import slot_is_used
from .previews import icon_args, pie_icon_args
from .icons import (
    ICON_CATEGORY_ENUM, get_all_icons, safe_icon, get_icons_by_category,
)


def execute_script(filepath, **params):
    """Run an external Python script from a pie menu command.

    Keyword arguments land in the script's globals, so one script can serve a
    whole family of slots -- `execute_script(path, axis='X')` rather than three
    near-identical files per axis. A script written before this existed is
    unaffected: it simply has no extra names to see.
    """
    import os
    filepath = os.path.normpath(filepath)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Script not found: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        exec(f.read(), {"bpy": bpy, **params})


def _resolve_bpy_data_path(path_str):
    """Resolve a dotted attribute path like 'bpy.context.space_data.overlay.show_edge_seams'
    into (data_object, prop_name). Returns None if it can't be safely resolved
    (e.g. it contains a function call, subscript, or isn't rooted at bpy)."""
    path_str = path_str.strip()
    parts = path_str.split(".")
    if len(parts) < 2 or parts[0] != "bpy":
        return None

    obj = bpy
    for part in parts[1:-1]:
        if not part.isidentifier():
            return None
        obj = getattr(obj, part, None)
        if obj is None:
            return None

    prop_name = parts[-1]
    if not prop_name.isidentifier() or not hasattr(obj, prop_name):
        return None

    return obj, prop_name


def _parse_bpy_ops_call(command):
    """Parse "bpy.ops.module.op_name(kw=val, ...)" into (idname, kwargs).

    Returns None if the command is not a plain bpy.ops call with literal
    keyword arguments: a positional argument, a **kwargs spread, or a value
    that is not a literal (a function call, a name, an f-string) all bail
    out to None rather than guess. ast.literal_eval only ever produces plain
    Python values -- numbers, strings, tuples, lists, dicts, booleans, None
    -- from the text itself; there is no path from parsing this string to
    executing anything inside it.
    """
    if not command.startswith("bpy.ops."):
        return None
    try:
        tree = ast.parse(command, mode='eval')
    except SyntaxError:
        return None

    call = tree.body
    if not isinstance(call, ast.Call) or call.args:
        return None  # bpy.ops operators take keyword arguments only

    names = []
    node = call.func
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not (isinstance(node, ast.Name) and node.id == "bpy"):
        return None
    names.reverse()
    if len(names) != 3 or names[0] != "ops":
        return None

    kwargs = {}
    for kw in call.keywords:
        if kw.arg is None:
            return None  # a **spread -- nothing literal to read
        try:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            return None

    return f"{names[1]}.{names[2]}", kwargs


# Spaces put in front of a label drawn beside an icon_value icon.
#
# A button drawn with icon= reserves a gap between the icon and its text; one
# drawn with icon_value= does not, so a custom or brush icon ends up touching
# the first letter. There is no layout setting for that gap -- the 3D Viewport
# Pie Menus addon has the same problem and solves it the same way, by baking
# spaces into the label text. Doing it here instead of in the stored label
# keeps the padding out of the user's data, so it never shows up in the
# Preferences list, in an exported preset, or in a label they are editing.
# Five, not two: a pie slot's brush icon is geometry (~31px, see
# previews.pie_icon_args), so it reaches further into the label than the ~19px
# icon this padding was first measured against. Five is the user's own call on
# how the gap should look, not a measurement -- don't "correct" it back.
_ICON_VALUE_LABEL_PAD = "     "


def _label_for(label, icon_kw):
    """A slot's label as drawn, padded when it sits beside an icon_value icon"""
    if label and "icon_value" in icon_kw and icon_kw["icon_value"]:
        return _ICON_VALUE_LABEL_PAD + label
    return label


# A slot stays a *direct* child of the pie layout -- never wrapped in a box or
# a column to make room for a bigger icon. Blender only draws its number
# shortcuts on direct children, so a wrapped slot silently loses the keyboard
# number that picks it, and splits the bar into a clickable half and a dead
# one. Confirmed in a real window: wrapped slots came back with no numbers
# while the plain ones beside them kept theirs. A brush icon gets its size
# from previews.pie_icon_args() instead, which is free of that trade-off.
def create_pie_menu_class(pie_data):
    """Dynamically create a menu class -- a pie, or a flat dropdown list.

    Both styles draw a slot identically; the only difference is the container
    they draw into, which is why _draw_slots takes it as an argument rather
    than the two being written out twice. A pie slot must stay a direct child
    of menu_pie() to keep its number shortcut, so nothing here may wrap one.
    """

    def _draw_slots(container, slots):

        # A button drawn with layout.operator() defaults to INVOKE_DEFAULT --
        # the operator's own interactive path -- unless told otherwise. For an
        # operator with no real modal behaviour that is harmless, but for one
        # that does (transform.resize, translate, rotate...) it means the
        # click starts an open-ended mouse-drag instead of applying the exact
        # values the item was configured with. EXEC_DEFAULT is what a bare
        # bpy.ops.foo.bar(**kwargs) call from a script already uses by
        # default, so this makes a clicked button behave the same way a
        # scripted call does: apply immediately, deterministically, with
        # whatever properties were set on it below.
        container.operator_context = 'EXEC_DEFAULT'

        # Draw items in order
        for slot in slots:
            if slot:
                try:
                    # Custom icons draw through icon_value, Blender's through icon, so the
                    # whole keyword pair is built once and splatted into each call
                    icon_kw = pie_icon_args(slot.icon, 'NONE')
                    label = _label_for(slot.label, icon_kw)
                    command = slot.command
                    
                    # A pie opening another pie. Checked before the plain
                    # submenu case below, because "wm.call_menu_pie" contains
                    # "wm.call_menu" and would otherwise be drawn with
                    # container.menu() -- which renders a flat dropdown list, not a
                    # pie. Drawn as a real wm.call_menu_pie button so the
                    # second pie opens where the mouse is, the way Blender's
                    # own chained pies do.
                    if command and "wm.call_menu_pie" in command and "name=" in command:
                        import re
                        match = re.search(r"name=['\"]([^'\"]+)['\"]", command)
                        if match:
                            # INVOKE_DEFAULT just for this button: the pie
                            # sets EXEC_DEFAULT for everything (so configured
                            # operator arguments actually apply), but
                            # wm.call_menu_pie has to be *invoked* to know
                            # where the mouse is. Executed instead, the second
                            # pie has no anchor to open around.
                            previous_context = container.operator_context
                            container.operator_context = 'INVOKE_DEFAULT'
                            op = container.operator("wm.call_menu_pie", text=label, **icon_kw)
                            op.name = match.group(1)
                            container.operator_context = previous_context
                        else:
                            op = container.operator("cocopie.execute_command", text=label, **icon_kw)
                            op.command = command

                    # Check if this is a submenu call
                    elif command and "wm.call_menu" in command and "name=" in command:
                        import re
                        match = re.search(r"name=['\"]([^'\"]+)['\"]", command)
                        if match:
                            menu_name = match.group(1)
                            container.menu(menu_name, text=label, **icon_kw)
                        else:
                            op = container.operator("cocopie.execute_command", text=label, **icon_kw)
                            op.command = command
                    
                    # Check if this is a property assignment (contains = but not ==, and not bpy.ops)
                    elif command and "=" in command and not command.startswith("bpy.ops.") and "==" not in command:
                        # Try to bind directly to the boolean property so the
                        # button reflects its live state (lit when True, like
                        # Blender's native overlay toggle buttons)
                        lhs = command.split("=")[0].strip()
                        resolved = _resolve_bpy_data_path(lhs)
                        bound = False
                        if resolved:
                            data_obj, prop_name = resolved
                            try:
                                current_val = getattr(data_obj, prop_name)
                                if isinstance(current_val, bool):
                                    container.prop(data_obj, prop_name, text=label, toggle=True, **icon_kw)
                                    bound = True
                            except Exception:
                                bound = False
                        if not bound:
                            # Not a simple boolean property - fall back to
                            # running the raw command via a plain button
                            op = container.operator("cocopie.execute_command", text=label, **icon_kw)
                            op.command = command
                    
                    # Check if this is a bpy.ops operator
                    elif command and command.startswith("bpy.ops."):
                        # A native button draws the real tooltip and the real
                        # enabled/disabled state, which is worth having -- but
                        # only once its arguments actually reach the operator.
                        # A previous version drew the button from the idname
                        # alone (everything inside the parentheses discarded),
                        # so any item configured with keyword arguments --
                        # Flip X/Y's constrained scale, Unwrap Classic's
                        # method, both align and axis unwraps -- silently ran
                        # with the operator's bare defaults instead.
                        parsed = _parse_bpy_ops_call(command)
                        if parsed:
                            idname, kwargs = parsed
                            try:
                                op = container.operator(idname, text=label, **icon_kw)
                                for prop_name, value in kwargs.items():
                                    setattr(op, prop_name, value)
                            except Exception:
                                # A property that does not exist or will not
                                # accept this value -- fall back rather than
                                # leave the button half-configured
                                op = container.operator("cocopie.execute_command", text=label, **icon_kw)
                                op.command = command
                        else:
                            # Not parseable as literal keyword arguments (a
                            # positional arg, a **spread, a non-literal value)
                            # -- run the command as written instead of
                            # guessing at it
                            op = container.operator("cocopie.execute_command", text=label, **icon_kw)
                            op.command = command
                    else:
                        # Anything else - use execute_command
                        op = container.operator("cocopie.execute_command", text=label, **icon_kw)
                        op.command = command
                except Exception as e:
                    container.label(text=slot.label)
            else:
                container.separator()
    
    def _used_slots():
        """The eight positions, filled where an item is actually in use."""
        slots = [None] * 8
        for item in pie_data.items:
            if item.enabled and slot_is_used(item) and 0 <= item.position <= 7:
                slots[item.position] = item
        return slots

    def draw_pie(self, context):
        _draw_slots(self.layout.menu_pie(), _used_slots())

    def draw_list(self, context):
        # Empty positions are skipped rather than drawn as separators: a gap
        # is meaningful in a pie, where it keeps a direction free, and is just
        # a hole in a dropdown.
        _draw_slots(self.layout.column(), [x for x in _used_slots() if x])

    # Create the class - use name for both label and idname
    menu_class = type(
        pie_data.idname,
        (Menu,),
        {
            "bl_label": pie_data.name,
            "bl_idname": pie_data.idname,
            "draw": draw_list if pie_data.menu_style == 'LIST' else draw_pie,
        }
    )
    
    return menu_class
