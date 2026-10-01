"""Operators for creating pies and arranging the items inside them."""

import bpy
import traceback
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import Operator
from ..utils import (
    apply_suppressions, restore_suppressions, find_suppression,
    record_prior_state,
    suppression_identity, invalidate_external_shortcut_index,
    ADDON_ID, get_prefs, get_pie, ensure_keymap_scopes,
    collapsed_group_keys, set_group_collapsed,
    holding_rebuilds, unused_pie_name, unused_pie_idname,
    section_neighbour,
)
from ..menus import execute_script
from ..keymaps import register_pie_menus, unregister_pie_menus
from ..presets import pie_to_dict, _apply_pie_dict


class COCOPIE_OT_execute_command(Operator):
    """Execute a Python command"""
    bl_idname = "cocopie.execute_command"
    bl_label = "Execute Command"
    bl_options = {'UNDO', 'INTERNAL'}
    
    command: StringProperty()
    
    def execute(self, context):
        if not self.command:
            return {'CANCELLED'}
        
        try:
            exec(self.command, {"bpy": bpy, "context": context, "execute_script": execute_script})
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Command failed: {str(e)}")
            return {'CANCELLED'}


class COCOPIE_OT_tap_toggle_direction(Operator):
    """Quick-tap alternative to a Drag pie: run one of two chosen directions
    directly, alternating between them, without opening the pie at all"""
    bl_idname = "cocopie.tap_toggle_direction"
    bl_label = "Toggle Pie Direction"
    bl_options = {'UNDO', 'INTERNAL'}

    pie_index: IntProperty()

    def execute(self, context):
        pie = get_pie(context, self.pie_index)
        if pie is None:
            return {'CANCELLED'}

        try:
            pos_a, pos_b = int(pie.tap_toggle_a), int(pie.tap_toggle_b)
        except (TypeError, ValueError):
            return {'CANCELLED'}

        item_a = next((it for it in pie.items if it.position == pos_a), None)
        item_b = next((it for it in pie.items if it.position == pos_b), None)
        if item_a is None or item_b is None:
            return {'CANCELLED'}

        target = item_b if pie.tap_toggle_last_ran_a else item_a
        pie.tap_toggle_last_ran_a = not pie.tap_toggle_last_ran_a

        if not target.command:
            return {'CANCELLED'}
        try:
            exec(target.command, {"bpy": bpy, "context": context, "execute_script": execute_script})
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Command failed: {str(e)}")
            return {'CANCELLED'}


class COCOPIE_OT_toggle_suppress_binding(Operator):
    """Switch this shortcut off while CocoPies is enabled, so the pie can use
    the key. Restored the moment CocoPies is disabled"""
    bl_idname = "cocopie.toggle_suppress_binding"
    bl_label = "Suppress Conflicting Shortcut"
    bl_options = {'INTERNAL'}

    # The full content identity of the keymap item, passed down from the row
    # that drew it. "idname" is taken by Operator itself, hence idname_prop.
    keymap: StringProperty()
    idname_prop: StringProperty()
    key_type: StringProperty()
    value: StringProperty()
    menu_name: StringProperty()
    any_modifier: BoolProperty()
    shift: BoolProperty()
    ctrl: BoolProperty()
    alt: BoolProperty()
    oskey: BoolProperty()

    def execute(self, context):
        prefs = get_prefs()
        if prefs is None:
            return {'CANCELLED'}

        identity = (self.keymap, self.idname_prop, self.key_type, self.value,
                    self.menu_name, self.any_modifier, self.shift, self.ctrl,
                    self.alt, self.oskey)

        existing = find_suppression(prefs, identity)
        if existing is not None:
            # Hand the key back before forgetting we ever took it -- dropping
            # the entry first would leave the item switched off with nothing
            # left that knows to restore it.
            restore_suppressions(prefs)
            for i, entry in enumerate(prefs.suppressed_bindings):
                if suppression_identity(entry) == identity:
                    prefs.suppressed_bindings.remove(i)
                    break
        else:
            entry = prefs.suppressed_bindings.add()
            (entry.keymap, entry.idname, entry.key_type, entry.value,
             entry.menu_name, entry.any_modifier, entry.shift, entry.ctrl,
             entry.alt, entry.oskey) = identity
            # Before apply_suppressions switches it off, while its own state is
            # still the answer to "was this on before CocoPies touched it"
            record_prior_state(prefs, entry)

        apply_suppressions(prefs)
        invalidate_external_shortcut_index()
        return {'FINISHED'}


class COCOPIE_OT_toggle_keymap_scope(Operator):
    """Register this pie in this editor, or stop registering it there"""
    bl_idname = "cocopie.toggle_keymap_scope"
    bl_label = "Toggle Editor"
    bl_options = {'INTERNAL'}

    pie_index: IntProperty()
    keymap_type: StringProperty()

    def execute(self, context):
        pie = get_pie(context, self.pie_index)
        if pie is None or not self.keymap_type:
            return {'CANCELLED'}

        scopes = ensure_keymap_scopes(pie)
        found = [i for i, s in enumerate(scopes)
                 if s.keymap_type == self.keymap_type]
        if found:
            # Never the last one: a pie scoped nowhere would be registered
            # nowhere, with nothing in the UI to get back from. The checkbox
            # is greyed for it too; this is the backstop.
            if len(scopes) - len(found) < 1:
                return {'CANCELLED'}
            with holding_rebuilds():
                for i in reversed(found):
                    scopes.remove(i)
        else:
            with holding_rebuilds():
                scopes.add().keymap_type = self.keymap_type
        register_pie_menus()
        return {'FINISHED'}


# Keys held down on their own never end a capture: they are read off the
# event as modifiers when the real key arrives
_MODIFIER_EVENTS = {
    'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL',
    'LEFT_ALT', 'RIGHT_ALT', 'OSKEY', 'HYPER', 'APP',
}
# Nothing a person presses, or not a key (movement, timers, the scroll wheel)
_NOT_KEYS = {
    'NONE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TEXTINPUT',
    'WINDOW_DEACTIVATE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE',
    'MOUSESMARTZOOM', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE',
    'WHEELOUTMOUSE', 'WHEELLEFTMOUSE', 'WHEELRIGHTMOUSE',
}
# Stops the capture and leaves the shortcut as it was
_CANCEL_EVENTS = {'ESC', 'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}
# Digits are stored the way they have always been typed ("2", not "TWO");
# keymaps._resolve_key turns them back into event types
_DIGITS = {'ZERO': '0', 'ONE': '1', 'TWO': '2', 'THREE': '3', 'FOUR': '4',
           'FIVE': '5', 'SIX': '6', 'SEVEN': '7', 'EIGHT': '8', 'NINE': '9'}

# The pie whose key is being captured right now, or -1, and what its button
# says meanwhile. Read by the draw code.
capturing_pie_index = -1
capture_text = ""

# Which modifier each modifier key is, in the order the shortcut is written
# (utils.format_shortcut: Shift, Ctrl, Alt)
_MODIFIER_NAMES = {
    'LEFT_SHIFT': "Shift", 'RIGHT_SHIFT': "Shift",
    'LEFT_CTRL': "Ctrl", 'RIGHT_CTRL': "Ctrl",
    'LEFT_ALT': "Alt", 'RIGHT_ALT': "Alt",
}
_MODIFIER_ORDER = ("Shift", "Ctrl", "Alt")


def _redraw_preferences(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PREFERENCES':
                area.tag_redraw()


class COCOPIE_OT_capture_key(Operator):
    """Click, then press the shortcut -- modifiers and all, e.g. Shift + A.
    Esc or a mouse click cancels"""
    bl_idname = "cocopie.capture_key"
    bl_label = "Set Shortcut"
    bl_options = {'INTERNAL'}

    pie_index: IntProperty()

    def _show_held(self, context):
        """Write the modifiers held so far on the button, as Blender's own
        keymap editor does while it waits: "Alt + ...", or "Press a key..."
        """
        global capture_text
        held = [m for m in _MODIFIER_ORDER if m in self._held]
        capture_text = " + ".join(held + ["..."]) if held else "Press a key..."
        _redraw_preferences(context)

    def invoke(self, context, event):
        global capturing_pie_index
        if get_pie(context, self.pie_index) is None:
            return {'CANCELLED'}
        capturing_pie_index = self.pie_index
        # Tracked from the modifier keys' own press and release rather than
        # read off event.shift/ctrl/alt, so the button follows a key being let
        # go of the moment it is
        self._held = set()
        context.window_manager.modal_handler_add(self)
        self._show_held(context)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        global capturing_pie_index, capture_text
        capturing_pie_index = -1
        capture_text = ""
        _redraw_preferences(context)

    def modal(self, context, event):
        name = _MODIFIER_NAMES.get(event.type)
        if name:
            if event.value == 'PRESS':
                self._held.add(name)
            elif event.value == 'RELEASE':
                self._held.discard(name)
            self._show_held(context)
            return {'RUNNING_MODAL'}
        if event.value != 'PRESS' or event.type in _MODIFIER_EVENTS \
                or event.type in _NOT_KEYS or event.type.startswith('TIMER'):
            return {'RUNNING_MODAL'}
        if event.type in _CANCEL_EVENTS:
            self._finish(context)
            return {'CANCELLED'}

        pie = get_pie(context, self.pie_index)
        if pie is not None:
            # One rebuild for the whole shortcut, not one per field. Holding
            # modifiers means exactly these, so Any goes off.
            with holding_rebuilds():
                pie.key = _DIGITS.get(event.type, event.type)
                pie.shift = event.shift
                pie.ctrl = event.ctrl
                pie.alt = event.alt
                pie.any_modifier = False
            register_pie_menus()
        self._finish(context)
        return {'FINISHED'}


class COCOPIE_OT_toggle_group(Operator):
    """Show or hide the pie menus in this editor's section"""
    bl_idname = "cocopie.toggle_group"
    bl_label = "Toggle Section"
    bl_options = {'INTERNAL'}

    group_key: StringProperty()

    def execute(self, context):
        prefs = get_prefs()
        if prefs is None:
            return {'CANCELLED'}
        collapsed = self.group_key in collapsed_group_keys(prefs)
        set_group_collapsed(prefs, self.group_key, not collapsed)
        return {'FINISHED'}


class COCOPIE_OT_select_pie(Operator):
    """Select a pie menu for editing"""
    bl_idname = "cocopie.select_pie"
    bl_label = "Select Pie Menu"
    bl_options = {'INTERNAL'}
    
    index: IntProperty()
    # Clicking the name of the row that is *already* selected starts a rename
    # rather than re-selecting it, which is what makes a double-click on any
    # row rename it: the first click selects, the second lands on this. Only
    # the name half asks for it -- clicking the shortcut half of a selected
    # row should not open a field the user was not aiming at.
    rename_if_active: BoolProperty(default=False)

    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            if self.rename_if_active and prefs.active_pie_index == self.index:
                prefs.renaming_pie_index = self.index
            else:
                prefs.active_pie_index = self.index
                # Selecting anything else ends a rename in progress, so the
                # field cannot be left open on a row that is no longer current
                prefs.renaming_pie_index = -1
        except Exception as e:
            self.report({'ERROR'}, f"Failed to select: {str(e)}")
        return {'FINISHED'}


class COCOPIE_OT_add_pie_menu(Operator):
    """Add a new pie menu"""
    bl_idname = "cocopie.add_pie_menu"
    bl_label = "Add Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences

            # Named before it is added, from what is actually taken: counting
            # the pies collides with a name still in use once one is deleted
            name = unused_pie_name(prefs)
            idname = unused_pie_idname(prefs)
            new_pie = prefs.pie_menus.add()
            with holding_rebuilds():
                new_pie.name = name
                new_pie.idname = idname

                # Add default item
                item = new_pie.items.add()
                item.label = "Example Item"
                item.command = "bpy.ops.mesh.primitive_cube_add()"
                item.icon = "MESH_CUBE"
                item.position = 0

            prefs.active_pie_index = len(prefs.pie_menus) - 1
            register_pie_menus()

            self.report({'INFO'}, f"Created {new_pie.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to add pie menu: {str(e)}")
            traceback.print_exc()

        return {'FINISHED'}


class COCOPIE_OT_remove_pie_menu(Operator):
    """Remove the selected pie menu"""
    bl_idname = "cocopie.remove_pie_menu"
    bl_label = "Remove Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.index < len(prefs.pie_menus):
                # Unregister before removing
                unregister_pie_menus()
                
                prefs.pie_menus.remove(self.index)
                prefs.active_pie_index = max(0, min(prefs.active_pie_index, len(prefs.pie_menus) - 1))
                
                # Re-register remaining menus
                register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove: {str(e)}")
        
        return {'FINISHED'}


class COCOPIE_OT_remove_all_pie_menus(Operator):
    """Delete every pie menu. Asks first; Restore Starter Pies or Import
    brings pies back"""
    bl_idname = "cocopie.remove_all_pie_menus"
    bl_label = "Delete All Pies"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        prefs = get_prefs(context)
        return prefs is not None and len(prefs.pie_menus) > 0

    def invoke(self, context, event):
        count = len(get_prefs(context).pie_menus)
        return context.window_manager.invoke_confirm(
            self, event,
            title="Delete All Pies",
            message=f"Delete all {count} pie menus? Export a preset first "
                    f"to keep them.",
            confirm_text="Delete All",
            icon='WARNING',
        )

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            return {'CANCELLED'}
        try:
            count = len(prefs.pie_menus)
            unregister_pie_menus()
            # With no pie left, nothing needs the keys the pies took: hand
            # them back (Blender's X delete menus) before forgetting them, as
            # unticking a box does. Restore Starter Pies records them again.
            restore_suppressions(prefs)
            prefs.suppressed_bindings.clear()
            prefs.pie_menus.clear()
            prefs.active_pie_index = 0
            # Starters stay recorded as seeded, so the next start does not
            # bring them back
            register_pie_menus()
            invalidate_external_shortcut_index()
            self.report({'INFO'}, f"Deleted {count} pie menu(s)")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to delete pies: {e}")
            traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}


class COCOPIE_OT_duplicate_pie_menu(Operator):
    """Duplicate the selected pie menu"""
    bl_idname = "cocopie.duplicate_pie_menu"
    bl_label = "Duplicate Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    index: IntProperty()
    
    def execute(self, context):
        try:
            prefs = context.preferences.addons[ADDON_ID].preferences
            
            if 0 <= self.index < len(prefs.pie_menus):
                # Copied through the same dict a preset file holds, so a
                # duplicate carries every setting a preset does -- the old
                # field-by-field copy dropped the Trigger, the Style and the
                # whole Quick Tap setup. Read before the add, which can move
                # the collection in memory under `source`.
                source = prefs.pie_menus[self.index]
                data = pie_to_dict(source)
                data["idname"] = unused_pie_idname(prefs, f"{source.idname}_copy")
                # Off until the user changes its shortcut, which is still the
                # original's
                data["enabled"] = False
                name = unused_pie_name(prefs, f"{source.name} Copy")

                unregister_pie_menus()
                new_pie = prefs.pie_menus.add()
                with holding_rebuilds():
                    new_pie.name = name
                    _apply_pie_dict(new_pie, data)
                register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to duplicate: {str(e)}")

        return {'FINISHED'}


class COCOPIE_OT_remove_item(Operator):
    """Clear this direction, leaving the slot empty"""
    bl_idname = "cocopie.remove_item"
    bl_label = "Clear Direction"
    bl_options = {'REGISTER', 'INTERNAL'}

    pie_index: IntProperty()
    item_index: IntProperty()

    def execute(self, context):
        try:
            pie = get_pie(context, self.pie_index)
            if not pie or not (0 <= self.item_index < len(pie.items)):
                return {'CANCELLED'}

            # Emptied rather than removed. The eight directions are fixed, so
            # dropping the row would shift every direction below it up one.
            item = pie.items[self.item_index]
            item.label = ""
            item.command = ""
            item.icon = 'NONE'
            item.enabled = True

            register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear direction: {str(e)}")

        return {'FINISHED'}


class COCOPIE_OT_move_pie_menu(Operator):
    """Move this pie menu up or down inside its section.

    Ordering here is cosmetic -- it changes nothing about shortcuts or
    registration, only the order the menus are listed in"""
    bl_idname = "cocopie.move_pie_menu"
    bl_label = "Move Pie Menu"
    bl_options = {'REGISTER', 'INTERNAL'}

    direction: EnumProperty(
        items=[('UP', 'Up', ''), ('DOWN', 'Down', '')]
    )

    @classmethod
    def poll(cls, context):
        # Greyed out at the end it cannot travel any further towards
        prefs = get_prefs(context)
        if not prefs or len(prefs.pie_menus) < 2:
            return False
        return True

    def execute(self, context):
        try:
            prefs = get_prefs(context)
            if not prefs:
                return {'CANCELLED'}

            index = prefs.active_pie_index
            if not (0 <= index < len(prefs.pie_menus)):
                return {'CANCELLED'}
            # Past the neighbour in the same section, not the next stored pie,
            # which can belong to any section. The pies stored in between are
            # all other sections', so a single move lands it right next to its
            # neighbour and leaves every other section's order alone.
            new_index = section_neighbour(prefs.pie_menus, index,
                                          -1 if self.direction == 'UP' else 1)
            if new_index is None:
                return {'CANCELLED'}

            prefs.pie_menus.move(index, new_index)
            # Keep the selection on the menu that moved, not on the row index
            prefs.active_pie_index = new_index
            # Not cosmetic to the registration, whatever the list shows: each
            # pie's menu draws from the stored pie it was built from, and a
            # Quick Tap item carries its pie's index -- after a move both
            # pointed at the neighbour until something else rebuilt
            register_pie_menus()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to move pie menu: {str(e)}")

        return {'FINISHED'}

