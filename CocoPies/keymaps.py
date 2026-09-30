"""Registering the pie menu classes and their keyboard shortcuts."""

import bpy
import traceback
from collections import Counter
from .items import KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS
from .utils import (
    get_prefs, format_shortcut, _debug,
    COCOPIE_KEYMAP_IDNAMES, invalidate_external_shortcut_index,
    apply_suppressions, restore_suppressions, settle_user_keyconfig,
    binding_identity, suppression_identity, _kmi_menu_name,
    pie_scope_types,
)
from .menus import create_pie_menu_class


registered_pie_classes = []
registered_keymaps = []

# Items written straight into the *dispatch* keyconfig because Blender refused
# to merge them there. See _mirror_missing_items for why that happens and
# _sweep_user_keyconfig for the one order they may be cleaned up in.
repaired_user_keymaps = []


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
    timed hold-vs-tap by hand (cocopie.hold_or_tap, since removed; its idname
    stays in the unregister sweep). It is now two ordinary keymap items, the
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
        # Never the OS key -- it is not an offered modifier (utils.clear_oskey)
        oskey=False,
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


# ---------------------------------------------------------------------------
# Getting a binding into the keyconfig Blender actually dispatches from.
#
# keymap_items.new() writes into `keyconfigs.addon`; Blender merges that into
# `keyconfigs.user`, and only the merged copy fires. That merge is normally
# automatic, and wm.keyconfigs.update() below asks for it explicitly.
#
# It can also be refused, permanently, for one exact binding. Blender stores a
# user keymap as a *diff* against default+addon, and an addon item that is
# removed from the user keyconfig while its addon twin still exists is recorded
# in that diff as "the user deleted this". The entry outlives the addon: from
# then on the merge re-applies the deletion, so the binding never reaches the
# dispatch keyconfig again. Reproduced from scratch on 2026-09-04 -- after such
# a removal, re-adding the addon item and calling keyconfigs.update() brings it
# back False, every time, and restarting Blender does not clear it either. It is
# what left the user's Mesh Flatten pie on Shift+X doing nothing while every
# other pie in the same keymap worked, and why the update() call alone was not
# enough of a fix.
#
# Two conclusions, and both matter:
#   - a binding that did not survive the merge has to be written into the user
#     keyconfig directly (_mirror_missing_items). That is the only route left,
#     and it works and survives later updates.
#   - CocoPies must never remove one of its merged copies while the addon item
#     is still there, or it creates exactly the ghost above -- against itself,
#     next session. _sweep_user_keyconfig therefore runs only after the addon
#     items are gone and the keyconfig has settled, which the same experiment
#     confirms leaves no diff entry behind.


def _binding_props(kmi):
    """The operator properties that distinguish two otherwise identical items"""
    if kmi.idname == 'wm.call_menu_pie':
        return getattr(kmi.properties, 'name', '') or ''
    if kmi.idname == 'cocopie.execute_command':
        return getattr(kmi.properties, 'command', '') or ''
    if kmi.idname == 'cocopie.tap_toggle_direction':
        return getattr(kmi.properties, 'pie_index', -1)
    return ''


def _same_binding(a, b):
    """Whether two keymap items are the same shortcut doing the same thing"""
    return (a.idname == b.idname
            and a.type == b.type
            and a.value == b.value
            and bool(a.any) == bool(b.any)
            and bool(a.shift) == bool(b.shift)
            and bool(a.ctrl) == bool(b.ctrl)
            and bool(a.alt) == bool(b.alt)
            and bool(a.oskey) == bool(b.oskey)
            and _binding_props(a) == _binding_props(b))


def _is_cocopie_item(kmi):
    """Whether a keymap item is one of ours, by content rather than by record"""
    if kmi.idname == 'wm.call_menu_pie':
        try:
            return (kmi.properties.name or '').startswith('COCOPIE_MT_')
        except Exception:
            return False
    return kmi.idname in COCOPIE_KEYMAP_IDNAMES


def _mirror_missing_items():
    """Write into the user keyconfig whatever the merge would not carry there.

    Called after wm.keyconfigs.update(), so anything still missing is missing
    for good (see the note above). Returns how many items had to be repaired --
    normally zero.
    """
    kc_user = getattr(bpy.context.window_manager.keyconfigs, 'user', None)
    if kc_user is None:
        return 0

    repaired = 0
    for km, kmi in registered_keymaps:
        try:
            km_user = kc_user.keymaps.find(
                km.name, space_type=km.space_type, region_type=km.region_type)
            if km_user is None:
                continue
            if any(_same_binding(kmi, other) for other in km_user.keymap_items):
                continue

            clone = km_user.keymap_items.new(
                kmi.idname, kmi.type, kmi.value,
                any=kmi.any, shift=kmi.shift, ctrl=kmi.ctrl,
                alt=kmi.alt, oskey=kmi.oskey)
            if kmi.idname == 'wm.call_menu_pie':
                clone.properties.name = kmi.properties.name
            elif kmi.idname == 'cocopie.execute_command':
                clone.properties.command = kmi.properties.command
            elif kmi.idname == 'cocopie.tap_toggle_direction':
                clone.properties.pie_index = kmi.properties.pie_index
            repaired_user_keymaps.append((km_user, clone))
            repaired += 1
        except Exception as e:
            print(f"CocoPies: could not place {kmi.idname} in {km.name}: {e}")
    return repaired


def _sweep_user_keyconfig():
    """Remove CocoPies items from the dispatch keyconfig.

    ONLY safe once the addon-side items are gone and the keyconfig has settled
    -- removing a merged copy whose addon twin still exists is what creates the
    permanent "user deleted this" entry described above. Callers must sweep the
    addon keyconfig and call wm.keyconfigs.update() first; unregister_pie_menus
    is the only caller and does exactly that.

    Sweeping by content rather than walking repaired_user_keymaps, for the same
    reason the addon sweep does: that list is empty again after any re-import,
    while real items from the previous one are still sitting in the keyconfig.
    """
    kc_user = getattr(bpy.context.window_manager.keyconfigs, 'user', None)
    if kc_user is None:
        return 0

    target_names = {name for name, _space in KEYMAP_CONFIG.values()} | set(WINDOW_MODE_KEYMAPS)
    removed = 0
    for km in list(kc_user.keymaps):
        if km.name not in target_names:
            continue
        for kmi in [item for item in km.keymap_items if _is_cocopie_item(item)]:
            try:
                km.keymap_items.remove(kmi)
                removed += 1
            except Exception:
                pass
    repaired_user_keymaps.clear()
    return removed


def _reread_keymap_preset_once(prefs):
    """Load the active keymap preset from its file again, once per config.

    Up to 1.13.2 CocoPies also wrote suppressions into `keyconfigs.active`, the
    loaded preset, and switched them back on there when unregistered. Blender's
    extension updater unregisters the old version and registers the new one in
    the same session, so the new one found MyPreset's X delete menu on in
    memory although the file has it off, and recorded its "X off" against
    that. After a restart the preset's X was off again, Blender's fallback put
    the saved edit on the Delete-key menu instead, and the Delete key did
    nothing -- measured on 5.2 in an isolated profile. Re-reading the file puts
    the preset back as it is on disk before anything is recorded.

    Nothing to do for "Blender" itself: the old restore left stock switched on,
    which is what stock is.
    """
    if prefs.keymap_preset_reread:
        return
    prefs.keymap_preset_reread = True
    kcs = bpy.context.window_manager.keyconfigs
    active = kcs.active
    if active is None or active == kcs.default:
        return
    path = bpy.utils.preset_find(active.name, "keyconfig")
    if path:
        bpy.utils.keyconfig_set(path)


def _apply_suppressions_deferred():
    """Timer callback: finish the keymap work once the keyconfig has settled.

    Both halves have to wait, and for the same reason -- Blender builds the
    dispatch keyconfig on its own schedule, after register() returns.
    Suppression waits because writing `active` too early stops a keymap
    merging at all (see below). The mirror waits because at Blender's own
    startup the user keyconfig has no keymaps yet when register() runs:
    checking there found nothing to compare against, repaired nothing, and the
    ghosted shortcut stayed dead for the whole session while the same code
    repaired it perfectly on any later rebuild. Measured exactly that way
    before this was moved here.

    Both write into the user keyconfig, so both run between two keyconfig
    updates (utils.settle_user_keyconfig): this one, and the one
    apply_suppressions ends with.

    The first pass in a configuration also puts back what an older CocoPies
    removed (_restore_lost_shortcuts_once). After a keymap preset switch the
    pass first puts back what the switch removed by mistake
    (_repair_after_preset_switch), before any edit of that keymap can make the
    loss permanent.
    """
    global _switch_pending
    prefs = get_prefs()
    try:
        if prefs is not None:
            _reread_keymap_preset_once(prefs)
    except Exception as e:
        print(f"CocoPies: could not re-read the keymap preset: {e}")
    try:
        settle_user_keyconfig()
        if prefs is not None:
            repaired = _restore_lost_shortcuts_once(prefs)
            if repaired:
                print(f"CocoPies: restored {repaired} shortcut(s) an older "
                      f"version removed")
    except Exception as e:
        print(f"CocoPies: could not restore removed shortcuts: {e}")
    try:
        if _switch_pending and prefs is not None:
            _switch_pending = False
            repaired = _repair_after_preset_switch(prefs, _switched_from)
            if repaired:
                print(f"CocoPies: restored {repaired} shortcut(s) the keymap "
                      f"preset switch removed")
    except Exception as e:
        print(f"CocoPies: could not repair after the keymap preset switch: {e}")
    try:
        repaired = _mirror_missing_items()
        if repaired:
            _debug(f"Placed {repaired} shortcut(s) the keyconfig merge skipped")
    except Exception as e:
        print(f"CocoPies: could not place skipped shortcuts: {e}")
    try:
        if prefs is not None:
            suppressed = apply_suppressions(prefs)
            if suppressed:
                _debug(f"Suppressed {suppressed} conflicting keymap item(s)")
    except Exception as e:
        print(f"CocoPies: Could not apply shortcut suppressions: {e}")
    return None


def _schedule_suppressions():
    """Queue the suppression pass for after Blender's own keymap merge.

    Re-scheduling is harmless -- both halves of that callback are idempotent,
    the mirror because it checks for the binding before placing it -- but a
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


# ---------------------------------------------------------------------------
# After a keymap preset switch.
#
# Picking another preset in Preferences > Keymap rebuilds `keyconfigs.user`
# from the new preset plus the addon items, then re-applies the user's saved
# edits. A suppression is one of those edits, so it comes back by itself where
# the new preset has the binding switched on as the old base did. Where the
# old base had it off (MyPreset has X off) nothing was saved, the new preset
# may have it on, and the native binding is live again, stealing the pie's key
# while the panel still shows the box ticked. So the deferred pass runs again.
#
# The other direction needs a repair. Blender re-applies a saved edit by
# content, and when the new preset has no switched-on copy of the item the
# edit was taken against, it falls back to the first item with the same
# operator, properties and on/off on any key. Measured on 5.2, stock ->
# MyPreset: the saved "X delete menu off" took the Delete-key menu in Mesh
# and in Curve, which stayed gone until switching back.
#
# Blender has no handler for a preset switch, and polling on a timer for
# something only the Keymap section can do was not wanted. So the check rides
# on that section's own draw: it redraws right after a switch, and it costs a
# string compare only while it is on screen. draw() may not write data, so it
# only queues the usual deferred pass, which then runs outside the draw.

_last_keyconfig_name = None
# Set by the watcher, read by the next deferred pass: a switch happened, and
# from which preset
_switch_pending = False
_switched_from = None


def _watch_keyconfig_preset(self, context):
    global _last_keyconfig_name, _switch_pending, _switched_from
    try:
        active = context.window_manager.keyconfigs.active
        name = active.name if active is not None else None
    except Exception:
        return
    if name == _last_keyconfig_name:
        return
    first_look = _last_keyconfig_name is None
    previous = _last_keyconfig_name
    _last_keyconfig_name = name
    if first_look:
        return
    _switch_pending = True
    _switched_from = previous
    invalidate_external_shortcut_index()
    _schedule_suppressions()


def _props_key(props):
    """An operator's set properties as a comparable tuple"""
    if props is None:
        return ()
    out = []
    for prop in props.bl_rna.properties:
        ident = prop.identifier
        if ident == 'rna_type':
            continue
        try:
            if not props.is_property_set(ident):
                continue
            value = getattr(props, ident)
        except Exception:
            continue
        if prop.type == 'POINTER':
            # A macro keeps each step's settings in a nested group
            value = _props_key(value)
        elif prop.type == 'COLLECTION':
            value = len(value)
        elif isinstance(value, set):
            value = tuple(sorted(value))
        elif hasattr(value, '__len__') and not isinstance(value, str):
            value = tuple(value)
        out.append((ident, value))
    return tuple(out)


def _content(kmi):
    """Everything that makes two keymap items the same shortcut doing the
    same thing, for comparing a user keymap with what it was built from"""
    return (kmi.idname, kmi.map_type, kmi.type, kmi.value, kmi.any,
            kmi.shift, kmi.ctrl, kmi.alt, kmi.oskey, kmi.hyper,
            kmi.key_modifier, kmi.direction, kmi.repeat, kmi.active,
            _props_key(kmi.properties))


def _base_keymap(kcs, km, kc):
    """km's counterpart in the base keyconfig kc, or in stock where kc has
    none -- the same choice Blender makes when it builds `user`"""
    for source in (kc, kcs.default):
        if source is None:
            continue
        found = source.keymaps.find(
            km.name, space_type=km.space_type, region_type=km.region_type)
        if found is not None:
            return found
    return None


def _repair_after_preset_switch(prefs, previous_name):
    """Put back what a preset switch removed in place of a suppressed item.

    Returns how many items were put back -- normally none.
    """
    kcs = bpy.context.window_manager.keyconfigs
    previous = kcs.get(previous_name) if previous_name else None
    suppressed = {suppression_identity(e) for e in prefs.suppressed_bindings}
    repaired = 0
    for identity in suppressed:
        for km_user in [km for km in kcs.user.keymaps if km.name == identity[0]]:
            repaired += _repair_keymap(kcs, km_user, identity, previous, suppressed)
    if repaired:
        settle_user_keyconfig()
    return repaired


def _repair_keymap(kcs, km_user, identity, previous, suppressed):
    def switched_on(km):
        return km is not None and any(
            k.active and binding_identity(k, km_user.name) == identity
            for k in km.keymap_items)

    # Only an edit saved against a base with the item on can land elsewhere,
    # and only when the new base has no such item on for it to find
    if previous is not None and not switched_on(_base_keymap(kcs, km_user, previous)):
        return 0
    km_base = _base_keymap(kcs, km_user, kcs.active)
    if km_base is None or switched_on(km_base):
        return 0
    return _restore_lost_items(kcs, km_user, km_base, identity, suppressed)


def _restore_lost_shortcuts_once(prefs):
    """Put back, once, what CocoPies up to 1.13.2 deleted from the user keymap.

    Those versions edited the preset under the user's saved edits, and Blender
    then re-applied a saved "X delete menu off" onto the Delete-key menu
    (see utils._iter_matching_items). Save Preferences kept that as an
    ordinary "remove", so fixing the cause brings nothing back: the user's
    Curve Delete key was dead in their own saved preferences on 2026-09-30.

    Once per configuration, like the preset re-read, so a shortcut the user
    removes on purpose later stays removed. Not marked done while `user` is
    still empty, which it can be this early in Blender's startup.
    """
    if prefs.lost_shortcuts_restored:
        return 0
    kcs = bpy.context.window_manager.keyconfigs
    if kcs.user is None or not len(kcs.user.keymaps):
        return 0
    prefs.lost_shortcuts_restored = True
    suppressed = {suppression_identity(e) for e in prefs.suppressed_bindings}
    repaired = 0
    for identity in suppressed:
        for km_user in [km for km in kcs.user.keymaps if km.name == identity[0]]:
            km_base = _base_keymap(kcs, km_user, kcs.active)
            if km_base is not None:
                repaired += _restore_lost_items(
                    kcs, km_user, km_base, identity, suppressed)
    if repaired:
        settle_user_keyconfig()
    return repaired


def _restore_lost_items(kcs, km_user, km_base, identity, suppressed):
    """Put back switched-on items with identity's operator and menu that
    km_user lacks against km_base plus the addon items. Returns how many."""
    def key(k):
        # A suppressed item's on/off is CocoPies' edit, re-applied right after
        # this, so it neither counts as a user edit nor as something lost
        content = _content(k)
        if binding_identity(k, km_user.name) in suppressed:
            content = content[:13] + (None,) + content[14:]
        return content

    # What `user` would hold with no edits at all: the preset's items and the
    # addon items. CocoPies' own are left out; the deferred pass re-places
    # any of those that go missing.
    expected = [k for k in km_base.keymap_items if not _is_cocopie_item(k)]
    km_addon = kcs.addon.keymaps.find(
        km_user.name, space_type=km_user.space_type, region_type=km_user.region_type)
    if km_addon is not None:
        expected += [k for k in km_addon.keymap_items if not _is_cocopie_item(k)]
    have = Counter(key(k) for k in km_user.keymap_items if not _is_cocopie_item(k))
    want = Counter(key(k) for k in expected)
    missing = want - have

    # The fallback's victims: switched-on items running the same operator and
    # menu on another key
    _km, idname, _type, _value, menu = identity[:5]
    lost, budget = [], Counter(missing)
    for k in expected:
        k_key = key(k)
        if (budget[k_key] > 0 and k.active and k.idname == idname
                and _kmi_menu_name(k) == menu
                and binding_identity(k, km_user.name) not in suppressed):
            lost.append(k)
            budget[k_key] -= 1
    if not lost:
        return 0

    if not (have - want) and not (missing - Counter(key(k) for k in lost)):
        # Nothing but the loss sets this keymap apart from the preset, so its
        # own copy loses nothing: Delete comes back as the preset's item, not
        # as one the user added, and no edit is left behind
        km_user.restore_to_default()
    else:
        # Other edits live here too. Keep them and put the lost item back, as
        # an item the keymap editor shows as added
        for k in lost:
            km_user.keymap_items.new_from_item(k)
    return len(lost)


def _scrub_keyconfig_watchers():
    """Remove every copy of the watcher, by name, for the same reload reason
    as __init__._scrub_context_menu_entries."""
    panel = getattr(bpy.types, 'USERPREF_PT_keymap', None)
    if panel is None:
        return None
    draw_funcs = panel._dyn_ui_initialize()
    draw_funcs[:] = [
        fn for fn in draw_funcs
        if not (getattr(fn, '__name__', None) == '_watch_keyconfig_preset'
                and getattr(fn, '__module__', '') == __name__)
    ]
    return panel


def register_keyconfig_watcher():
    global _last_keyconfig_name
    try:
        _last_keyconfig_name = bpy.context.window_manager.keyconfigs.active.name
    except Exception:
        _last_keyconfig_name = None
    panel = _scrub_keyconfig_watchers()
    if panel is not None:
        panel.append(_watch_keyconfig_preset)


def unregister_keyconfig_watcher():
    try:
        _scrub_keyconfig_watchers()
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

    prefs = get_prefs()
    if prefs is None:
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
            # freely -- two scopes can name the same keymap -- and keymap_items.new() appends
            # rather than replacing, which would leave the pie bound twice on
            # one key and firing twice per press.
            targets = []
            for scope_type in pie_scope_types(pie_data):
                # KEYMAP_CONFIG is shared with the scope dropdown and the
                # conflict check so the three cannot disagree
                keymap_name, space_type = KEYMAP_CONFIG.get(
                    scope_type, ('Window', 'EMPTY'))
                if (keymap_name, space_type) not in targets:
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

    # Placing whatever the merge still refuses to carry over is the other half
    # of this, and it cannot happen here -- see _apply_suppressions_deferred,
    # which _schedule_suppressions queues at the end of this function.

    # Deferred, not called here. Blender merges addon keymaps into the
    # dispatch keyconfig on its own schedule, after register() returns; writing
    # `active = False` into one of those keymaps before that merge has happened
    # stops the merge for that keymap entirely -- measured, on this machine:
    # Mesh and Curve ended up with 0 of their 11 and 7 addon items while
    # Weight Paint, whose keymap nothing suppressed, took all 4 of its own.
    # Un-suppressing afterwards does not undo it; the keymap stays stuck until
    # Blender is restarted. So the edit has to wait for a settled keyconfig.
    _schedule_suppressions()


def unregister_pie_menus(restore_suppressed=False):
    """Unregister all pie menus and keymaps.

    restore_suppressed is for a real unregister only (__init__.unregister):
    it switches back on what CocoPies switched off. A rebuild leaves the
    suppressions alone; see the comment below.

    Sweeps every keymap CocoPies could have touched for any wm.call_menu_pie
    item that points at one of our menus, or any item running a CocoPies
    operator (COCOPIE_KEYMAP_IDNAMES -- Quick Tap's tap items, which would
    orphan exactly the same way if left out of this sweep), rather than
    trusting only registered_keymaps. That list lives at module level, so it is empty again
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

    _cancel_scheduled_suppressions()

    # On a real unregister, before anything else: whatever CocoPies switched
    # off, it switches back on. A user disabling the addon gets their keymap
    # as they left it, which is the whole reason suppression is stored here
    # instead of applied for good. Failing this must not stop the rest of the
    # teardown, or a bad restore would also leak keymap items.
    #
    # Not on a rebuild. Up to 1.13.2 every rebuild (any change to any pie)
    # switched the native X delete menus back on here and off again from the
    # deferred pass 0.2 s later. Nothing needed that -- the set of suppressions
    # does not change with the pies -- and the gap was harmful: X opened
    # Blender's menu in it, and an edit made in it (CocoBackup importing
    # shortcuts, measured) was recorded against the switched-on item, which
    # Blender then re-applied onto the Delete-key menu. restore_suppressions
    # settles the keyconfig before and after its writes, so they are recorded
    # before the addon sweep below changes the addon keymap.
    if restore_suppressed:
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

    # Not redundant with the sweep above: that one only recognises menus named
    # COCOPIE_MT_*, and a pie's idname is the user's to edit. This list is the
    # only thing that finds a pie renamed to VIEW3D_MT_something.
    for km, kmi in registered_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    registered_keymaps.clear()

    # Only now, with every addon-side item gone, may the dispatch keyconfig be
    # touched: the update() settles the removals first, so what the sweep takes
    # out is no longer shadowing an addon item and Blender records no "user
    # deleted this" against it. Reversing these two steps is what would leave a
    # ghost entry poisoning the same shortcut next session -- the exact failure
    # this whole path exists to repair.
    try:
        wm.keyconfigs.update()
        removed = _sweep_user_keyconfig()
        if removed:
            _debug(f"Cleared {removed} keymap item(s) from the dispatch keyconfig")
        wm.keyconfigs.update()
    except Exception as e:
        print(f"CocoPies: could not clear the dispatch keyconfig: {e}")

    for cls in registered_pie_classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    registered_pie_classes.clear()
