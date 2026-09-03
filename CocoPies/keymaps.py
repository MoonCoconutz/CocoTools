"""Registering the pie menu classes and their keyboard shortcuts."""

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
    COCOPIE_KEYMAP_IDNAMES, invalidate_external_shortcut_index,
    apply_suppressions, restore_suppressions,
    pie_scope_types,
)
from .menus import execute_script, create_pie_menu_class


registered_pie_classes = []
registered_keymaps = []


# A key like "0" is stored as-is, but Blender's key identifiers spell number
# keys out ("ZERO".."NINE"); resolving it once here keeps register_pie_menus
# and the tap/hold keymap item in agreement about what event.type to expect.
_KEY_NAME_MAPPING = {
    '0': 'ZERO', '1': 'ONE', '2': 'TWO', '3': 'THREE', '4': 'FOUR',
    '5': 'FIVE', '6': 'SIX', '7': 'SEVEN', '8': 'EIGHT', '9': 'NINE',
}


def _resolve_key(key):
    return _KEY_NAME_MAPPING.get(key, key)


def _add_keymap_item(km, key, pie_data, pie_index):
    """Create this pie's keymap item(s). Returns a list of (km, kmi).

    Quick Tap used to be one item on PRESS driving a modal operator that
    timed hold-vs-tap by hand (COCOPIE_OT_hold_or_tap, kept registered but
    no longer bound -- see below). It is now two ordinary keymap items, the
    same pair the keymap editor would show:

        CLICK_DRAG -> wm.call_menu_pie      (hold and move: the pie)
        CLICK      -> the tap action        (press and release: the command)

    Blender resolves those two natively, so the pie opens the instant the
    drag threshold is crossed instead of after a fixed 0.2s of holding
    still -- which also removes the failure where moving faster than the
    timer got you a tap when you wanted the pie. The trade is that the
    decision is now distance-based rather than time-based, so holding the
    key without moving no longer opens anything; that is precisely what
    CLICK_DRAG means everywhere else in Blender, which is the point.
    """
    modifiers = dict(
        any=pie_data.any_modifier,
        shift=pie_data.shift,
        ctrl=pie_data.ctrl,
        alt=pie_data.alt,
        oskey=pie_data.oskey,
    )
    items = []

    if pie_data.tap_toggle:
        # Drag first, matching how Blender's own keymaps order a drag/click
        # pair. Ordering does not decide the winner here -- the event system
        # does -- but keeping the same order makes the keymap editor read
        # the way a built-in one does.
        drag = km.keymap_items.new(
            'wm.call_menu_pie', key, 'CLICK_DRAG', **modifiers)
        drag.properties.name = pie_data.idname
        items.append((km, drag))

        if pie_data.tap_action == 'COMMAND':
            # No command means no item, so the key falls through to whatever
            # Blender itself binds rather than being swallowed by an
            # operator that would only cancel. A half-configured Quick Tap
            # therefore behaves like no Quick Tap at all on the tap side.
            if pie_data.tap_command:
                tap = km.keymap_items.new(
                    'cocopie.execute_command', key, 'CLICK', **modifiers)
                tap.properties.command = pie_data.tap_command
                items.append((km, tap))
        else:
            tap = km.keymap_items.new(
                'cocopie.tap_toggle_direction', key, 'CLICK', **modifiers)
            tap.properties.pie_index = pie_index
            items.append((km, tap))
    else:
        kmi = km.keymap_items.new(
            'wm.call_menu_pie', key, pie_data.event_value, **modifiers)
        kmi.properties.name = pie_data.idname
        items.append((km, kmi))

    return items


def _apply_suppressions_deferred():
    """Timer callback: suppress once the keyconfig has settled. Never repeats."""
    try:
        prefs = get_prefs()
        if prefs is not None:
            suppressed = apply_suppressions(prefs)
            if suppressed:
                _debug(f"Suppressed {suppressed} conflicting keymap item(s)")
    except Exception as e:
        print(f"CocoPies: Could not apply shortcut suppressions: {e}")
    return None


def _schedule_suppressions():
    """Queue the suppression pass for after Blender's own keymap merge.

    Re-scheduling is harmless -- apply_suppressions is idempotent -- but a
    pending timer is dropped on unregister so a disabled addon cannot switch
    something off a moment after being told to stop.
    """
    if bpy.app.timers.is_registered(_apply_suppressions_deferred):
        return
    bpy.app.timers.register(_apply_suppressions_deferred, first_interval=0.2)


def _cancel_scheduled_suppressions():
    if bpy.app.timers.is_registered(_apply_suppressions_deferred):
        try:
            bpy.app.timers.unregister(_apply_suppressions_deferred)
        except Exception:
            pass


def register_pie_menus():
    """Register all pie menus and their keymaps"""
    global registered_pie_classes, registered_keymaps

    unregister_pie_menus()

    # Everyone else's shortcuts are cached for the conflict warning; a
    # re-register is the one moment we know the keyconfig has just churned,
    # and is also when another addon has most likely been toggled behind us.
    invalidate_external_shortcut_index()

    try:
        prefs = bpy.context.preferences.addons[ADDON_ID].preferences
    except:
        return
    
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    
    if not kc:
        print("CocoPies: No addon keyconfig found")
        return
    
    for pie_index, pie_data in enumerate(prefs.pie_menus):
        if not pie_data.enabled:
            continue
        
        menu_class = create_pie_menu_class(pie_data)
        
        try:
            bpy.utils.register_class(menu_class)
            registered_pie_classes.append(menu_class)
            _debug(f"Registered menu class: {pie_data.idname}")
            
            key = _resolve_key(pie_data.key)

            # A pie with no key is registered as a menu but gets no keymap
            # item. That is a real configuration, not a broken one: a pie
            # reached only from another pie's slot (a chained sub-pie) has
            # nothing to bind, and keymap_items.new() with an empty type
            # raises. Without this the whole pie lands in the except below and
            # looks like a registration failure.
            if not key:
                _debug(f"No shortcut on {pie_data.idname}; menu only")
                continue

            # A pie can be scoped to several editors at once, so this walks
            # every scope and collects the (keymap name, space type) pairs
            # first. Deduplicated before anything is created: scopes overlap
            # freely -- "Window (Global)" already covers Mesh, so picking both
            # names the same keymap twice -- and keymap_items.new() appends
            # rather than replacing, which would leave the pie bound twice on
            # one key and firing twice per press.
            targets = []
            for scope_type in pie_scope_types(pie_data):
                # KEYMAP_CONFIG is shared with the scope dropdown and the
                # conflict check so the three cannot disagree
                keymap_name, space_type = KEYMAP_CONFIG.get(
                    scope_type, ('Window', 'EMPTY'))
                if scope_type == 'WINDOW':
                    # "Window (Global)" is not one keymap -- it is every 3D
                    # viewport mode keymap
                    for km_name in WINDOW_MODE_KEYMAPS:
                        if (km_name, 'EMPTY') not in targets:
                            targets.append((km_name, 'EMPTY'))
                elif (keymap_name, space_type) not in targets:
                    targets.append((keymap_name, space_type))

            for km_name, space_type in targets:
                try:
                    km = kc.keymaps.new(name=km_name, space_type=space_type)
                    registered_keymaps.extend(
                        _add_keymap_item(km, key, pie_data, pie_index))
                except Exception as e:
                    print(f"CocoPies: Could not register keymap for {km_name}: {e}")

            _debug(f"Registered keymap: {format_shortcut(pie_data)} in "
                  f"{[n for n, _s in targets]} for {pie_data.idname}")
        
        except Exception as e:
            print(f"CocoPies: Error registering pie menu {pie_data.idname}: {e}")
            import traceback
            traceback.print_exc()

    # Push the items just created into the keyconfig Blender dispatches from.
    #
    # keymap_items.new() only populates the *addon* keyconfig. Blender merges
    # that into the user keyconfig on its own schedule, and a pie registered
    # part-way through a session can sit in the addon keyconfig with the
    # dispatch keyconfig never learning about it -- the shortcut then does
    # nothing at all, with no error anywhere. That is what made Mesh Flatten
    # invisible on Alt+X until Blender was restarted, while every other Mesh
    # pie worked. Asking for the update here makes the merge part of
    # registering rather than something to wait for.
    try:
        wm.keyconfigs.update()
    except Exception as e:
        print(f"CocoPies: could not refresh the keyconfig: {e}")

    # Deferred, not called here. Blender merges addon keymaps into the
    # dispatch keyconfig on its own schedule, after register() returns; writing
    # `active = False` into one of those keymaps before that merge has happened
    # stops the merge for that keymap entirely -- measured, on this machine:
    # Mesh and Curve ended up with 0 of their 11 and 7 addon items while
    # Weight Paint, whose keymap nothing suppressed, took all 4 of its own.
    # Un-suppressing afterwards does not undo it; the keymap stays stuck until
    # Blender is restarted. So the edit has to wait for a settled keyconfig.
    _schedule_suppressions()


def unregister_pie_menus():
    """Unregister all pie menus and keymaps.

    Sweeps every keymap CocoPies could have touched for any wm.call_menu_pie
    item that points at one of our menus, or any cocopie.hold_or_tap item
    (Tap to Toggle's keymap item, which would orphan exactly the same way if
    left out of this sweep), rather than trusting only
    registered_keymaps. That list lives at module level, so it is empty again
    every time this module gets freshly re-imported -- which happens on a
    disable/enable cycle that does not reuse the cached module, and on
    Blender's own "Reload Scripts". A fresh-but-empty list makes this function
    believe there is nothing to remove, when a *previous* import may have left
    real keymap items behind. keymap_items.new() always appends; it never
    replaces an existing match, so those orphans do not go away on their own
    -- they keep firing under whatever Trigger and modifiers they were
    created with, stacked underneath whatever the pie is set to now. That is
    what made changing the Trigger look like it was not doing anything: an
    old PRESS entry from an earlier reload was still there, alongside the new
    one, both matching the same key.
    """
    global registered_pie_classes, registered_keymaps

    # Before anything else: whatever CocoPies switched off, it switches back
    # on. A user disabling the addon gets their keymap as they left it, which
    # is the whole reason suppression is stored here instead of applied for
    # good. Failing this must not stop the rest of the teardown, or a bad
    # restore would also leak keymap items.
    _cancel_scheduled_suppressions()
    try:
        prefs = get_prefs()
        if prefs is not None:
            restore_suppressions(prefs)
    except Exception as e:
        print(f"CocoPies: Could not restore suppressed shortcuts: {e}")

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        target_names = {name for name, _space in KEYMAP_CONFIG.values()} | set(WINDOW_MODE_KEYMAPS)
        for km in list(kc.keymaps):
            if km.name not in target_names:
                continue
            stale = [kmi for kmi in km.keymap_items
                    if (kmi.idname == 'wm.call_menu_pie'
                        and kmi.properties.name.startswith('COCOPIE_MT_'))
                    or kmi.idname in COCOPIE_KEYMAP_IDNAMES]
            for kmi in stale:
                try:
                    km.keymap_items.remove(kmi)
                except Exception:
                    pass

    # Still drained for cleanliness; the sweep above is what actually
    # guarantees nothing real is left behind
    for km, kmi in registered_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    registered_keymaps.clear()

    for cls in registered_pie_classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    registered_pie_classes.clear()
