"""Small shared helpers: locating the preferences, describing shortcuts,
and working out which pies would collide."""

import bpy
import sys
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

# The key this addon is registered under, and the key its preferences are
# stored against. Taken from the package rather than __name__, which inside a
# submodule would be "CocoPie.utils" and match no registered addon.
ADDON_ID = __package__


def addon_version_string():
    """The addon's version as "v1.8.0", read from bl_info when it is needed.

    bl_info lives in the package __init__, which imports this module -- so it
    cannot be imported from here. Looking it up at call time sidesteps that:
    by the time anything draws, the package is fully loaded.
    """
    module = sys.modules.get(ADDON_ID)
    info = getattr(module, "bl_info", None) if module else None
    version = info.get("version") if info else None
    return "v" + ".".join(str(v) for v in version) if version else ""


def get_prefs(context=None):
    """Return the addon preferences, or None if the addon isn't registered yet"""
    try:
        return (context or bpy.context).preferences.addons[ADDON_ID].preferences
    except (KeyError, AttributeError):
        return None


def get_pie(context, pie_index):
    """Return the pie menu at pie_index, or None if it's gone"""
    prefs = get_prefs(context)
    if prefs and 0 <= pie_index < len(prefs.pie_menus):
        return prefs.pie_menus[pie_index]
    return None


def get_pie_item(context, pie_index, item_index):
    """Return the item at item_index inside pie_index, or None if it's gone"""
    pie = get_pie(context, pie_index)
    if pie and 0 <= item_index < len(pie.items):
        return pie.items[item_index]
    return None


def oskey_label():
    """What Blender itself calls the OS-key modifier on this platform"""
    if sys.platform == "darwin":
        return "Cmd"
    if sys.platform == "win32":
        return "Win"
    return "OS"


def format_shortcut(pie):
    """Human-readable shortcut, e.g. 'Ctrl + Shift + Q'"""
    parts = []
    if pie.any_modifier:
        # Passing any=True makes Blender itself force shift/ctrl/alt/oskey to
        # -1 (verified against a live KeyMapItem) -- whatever those toggles
        # show becomes moot once Any is on, so the label should not claim they
        # still apply
        parts.append("Any")
    else:
        if pie.shift:
            parts.append("Shift")
        if pie.ctrl:
            parts.append("Ctrl")
        if pie.alt:
            parts.append("Alt")
        if pie.oskey:
            parts.append(oskey_label())
    parts.append(pie.key or "?")
    return " + ".join(parts)

def keymap_names_for(keymap_type):
    """The keymap names a pie with this scope actually ends up registered in"""
    if keymap_type == 'WINDOW':
        return set(WINDOW_MODE_KEYMAPS)
    name, _space = KEYMAP_CONFIG.get(keymap_type, ('Window', 'EMPTY'))
    return {name}


def _keymaps_overlap(a, b):
    """Two pie menus can only collide if they land in a keymap they share.

    Compared by the keymaps they actually register into rather than by scope
    name, so a global pie no longer reports a conflict against one scoped to an
    editor it never reaches.
    """
    return bool(keymap_names_for(a) & keymap_names_for(b))


def find_shortcut_conflicts(prefs, pie, index):
    """Names of other *enabled* pie menus that would fight over the same shortcut"""
    if not pie.enabled:
        return []

    conflicts = []
    for i, other in enumerate(prefs.pie_menus):
        if i == index or not other.enabled:
            continue

        # Any modifier held on either side matches every modifier state on
        # the other, since that is what Blender itself does once any=True is
        # passed to keymap_items.new() -- it forces shift/ctrl/alt/oskey to
        # -1 regardless of what those toggles show, so the specific states
        # are not meaningful to compare while either pie has Any set
        if pie.any_modifier or other.any_modifier:
            modifiers_match = True
        else:
            modifiers_match = (other.ctrl == pie.ctrl
                               and other.shift == pie.shift
                               and other.alt == pie.alt
                               and other.oskey == pie.oskey)

        if (other.key.upper() == pie.key.upper()
                and modifiers_match
                and other.event_value == pie.event_value
                and _keymaps_overlap(other.keymap_type, pie.keymap_type)):
            conflicts.append(other.name)
    return conflicts


# Every CocoPie-owned operator that has ever been bound to a keymap item,
# including ones no longer bound by the current code. Items created by an
# older version outlive it -- they sit in the saved keyconfig and keep firing
# -- so a retired idname has to stay in this set, not be dropped from it.
# `cocopie.tap_toggle_direction` is exactly that case: it used to be bound to
# CLICK directly, and those leftovers fired the toggle on a plain tap no
# matter what Tap to Toggle was set to. Used both to sweep stale items on
# unregister and to keep CocoPie out of its own conflict scan.
COCOPIE_KEYMAP_IDNAMES = {
    'cocopie.hold_or_tap',
    'cocopie.tap_toggle_direction',
}


# Keymaps that are also live wherever the keyed one is. Blender evaluates a
# keymap's ancestors too, so a binding in "Window" fires inside Object Mode
# just as surely as one registered there directly -- which is exactly how a
# third-party Shift+T in "Window" can beat a pie scoped to the mode keymaps
# without either being visible to a same-name comparison.
_ALWAYS_LIVE_KEYMAPS = frozenset({'Window', 'Screen', 'Screen Editing', 'User Interface'})
_KEYMAP_EXTRA_ANCESTORS = {
    'UV Editor': frozenset({'Image', 'Image Generic'}),
}

# Event values that all derive from the same physical key-down, and therefore
# contend for it. Blender resolves PRESS first, so a PRESS binding elsewhere
# swallows the key before a CLICK/CLICK_DRAG pie is ever considered -- they
# genuinely conflict even though the values differ, which is why this is a
# family rather than the exact-equality test used between two CocoPie pies.
_PRESS_FAMILY = frozenset({'PRESS', 'CLICK', 'DOUBLE_CLICK', 'CLICK_DRAG', 'ANY'})
_RELEASE_FAMILY = frozenset({'RELEASE', 'ANY'})

# Rebuilt lazily; None means "not scanned yet". The scan walks every keymap in
# the user keyconfig, so it is cached rather than repeated on each redraw.
_external_index = None


def invalidate_external_shortcut_index():
    """Drop the cached scan of everyone else's shortcuts.

    Called whenever CocoPie re-registers, which is also when another addon is
    most likely to have been enabled or disabled behind us.
    """
    global _external_index
    _external_index = None


def _ancestor_keymaps(keymap_names):
    """Every keymap whose bindings are live in the given ones, ancestors included"""
    live = set(keymap_names) | set(_ALWAYS_LIVE_KEYMAPS)
    for name in keymap_names:
        if name in WINDOW_MODE_KEYMAPS:
            live.add('3D View')
            live.add('3D View Generic')
        live |= _KEYMAP_EXTRA_ANCESTORS.get(name, frozenset())
    return live


def _keymap_item_label(kmi):
    """The most recognisable name for a keymap item.

    `kmi.name` is usually the operator's UI label, but falls back to the raw
    RNA identifier ("PAINT_OT_brush_select") for items whose operator is not
    currently registered. The dotted idname the user sees in tooltips is more
    use than that, so it wins whenever the name is clearly the RNA one.
    """
    name = (kmi.name or "").strip()
    if not name or "_OT_" in name:
        return kmi.idname
    return name


def _build_external_index():
    """Index every non-CocoPie shortcut in the user keyconfig, keyed by key type.

    The user keyconfig is the one Blender actually dispatches from -- it merges
    Blender's defaults, every addon's items and the user's own edits, and its
    `active` flags are the ones that count. CocoPie's own items are mirrored
    into it too, so they are filtered out here or every pie would report a
    conflict with itself.
    """
    index = {}
    wm = bpy.context.window_manager
    kc = getattr(wm.keyconfigs, 'user', None)
    if kc is None:
        return index

    # Where a binding came from is the useful half of the warning, and it takes
    # both stock keyconfigs to tell apart: present in `default` means Blender
    # ships it, present in `addon` means some addon added it, and neither means
    # the user bound it themselves in the Keymap editor. Absence from `default`
    # alone does not make something an addon's -- a hand-edited binding on a
    # stock operator looks exactly the same from there.
    def _idnames_in(kc_name):
        found = set()
        other_kc = getattr(wm.keyconfigs, kc_name, None)
        if other_kc is None:
            return found
        for km in other_kc.keymaps:
            for kmi in km.keymap_items:
                found.add(kmi.idname)
        return found

    default_idnames = _idnames_in('default')
    addon_idnames = _idnames_in('addon')

    for km in kc.keymaps:
        for kmi in km.keymap_items:
            if not kmi.active or not kmi.idname:
                continue
            if kmi.idname in COCOPIE_KEYMAP_IDNAMES:
                continue
            if kmi.idname == 'wm.call_menu_pie':
                menu_name = getattr(kmi.properties, 'name', '') or ''
                if menu_name.startswith('COCOPIE_MT_'):
                    continue
            if kmi.idname in addon_idnames:
                source = "Add-on"
            elif kmi.idname in default_idnames:
                source = "Blender"
            else:
                source = "Custom"

            index.setdefault(kmi.type, []).append({
                'idname': kmi.idname,
                'label': _keymap_item_label(kmi),
                'keymap': km.name,
                'value': kmi.value,
                'any': kmi.any,
                'shift': bool(kmi.shift),
                'ctrl': bool(kmi.ctrl),
                'alt': bool(kmi.alt),
                'oskey': bool(kmi.oskey),
                'source': source,
            })
    return index


def _values_contend(pie_value, other_value):
    """Whether two event values compete for the same physical key press"""
    if pie_value == other_value or 'ANY' in (pie_value, other_value):
        return True
    if pie_value in _PRESS_FAMILY and other_value in _PRESS_FAMILY:
        return True
    return pie_value in _RELEASE_FAMILY and other_value in _RELEASE_FAMILY


def find_external_conflicts(pie, limit=6):
    """Shortcuts outside CocoPie -- Blender's own or another addon's -- that
    would fight this pie for its key.

    This is the blind spot the pie-vs-pie check leaves: it only ever compared
    CocoPie menus against each other, so a third-party binding on the same key
    was invisible in the editor no matter how completely it shadowed the pie.
    """
    global _external_index

    if not pie.enabled or not pie.key:
        return []

    if _external_index is None:
        try:
            _external_index = _build_external_index()
        except Exception:
            # A UI warning is never worth breaking the panel's draw over
            _external_index = {}

    candidates = _external_index.get(pie.key.upper(), ())
    if not candidates:
        return []

    live_keymaps = _ancestor_keymaps(keymap_names_for(pie.keymap_type))

    hits = []
    seen = set()
    for other in candidates:
        if other['keymap'] not in live_keymaps:
            continue

        if pie.any_modifier or other['any']:
            modifiers_match = True
        else:
            modifiers_match = (other['shift'] == bool(pie.shift)
                               and other['ctrl'] == bool(pie.ctrl)
                               and other['alt'] == bool(pie.alt)
                               and other['oskey'] == bool(pie.oskey))
        if not modifiers_match:
            continue

        if not _values_contend(pie.event_value, other['value']):
            continue

        # One operator bound in several keymaps is one problem to report, not
        # nine -- a global pie would otherwise list the same addon per mode
        key = (other['idname'], other['label'])
        if key in seen:
            continue
        seen.add(key)
        hits.append(other)
        if len(hits) >= limit:
            break

    return hits


def ensure_slot_items(pie):
    """Give the pie exactly one item per slot, ordered 0..7.

    A pie has eight directions and always did; the editor now shows them as
    eight fixed rows, so the stored items are made to match one-to-one. Items
    are only added and reordered, never dropped -- if two ever claimed the same
    slot, the later one is moved to the first free slot rather than discarded.

    Idempotent, so it is safe to call on every draw.
    """
    if len(pie.items) == 8 and all(item.position == i for i, item in enumerate(pie.items)):
        return

    claimed = {}
    homeless = []
    for item in pie.items:
        if 0 <= item.position <= 7 and item.position not in claimed:
            claimed[item.position] = item
        else:
            homeless.append(item)

    for position in range(8):
        if position not in claimed and homeless:
            claimed[position] = homeless.pop(0)

    # Snapshot, because the collection is about to be rebuilt underneath us
    snapshot = {
        position: {
            "label": item.label, "command": item.command,
            "icon": item.icon, "enabled": item.enabled,
        }
        for position, item in claimed.items()
    }

    pie.items.clear()
    for position in range(8):
        item = pie.items.add()
        item.position = position
        stored = snapshot.get(position)
        if stored:
            item.label = stored["label"]
            item.command = stored["command"]
            item.icon = stored["icon"]
            item.enabled = stored["enabled"]
        else:
            # An unused direction: present in the table, absent from the pie
            item.label = ""
            item.command = ""
            item.icon = 'NONE'
            item.enabled = True


def slot_is_used(item):
    """An item fills its slot once it has something to run or something to say"""
    return bool(item.command.strip() or item.label.strip())


def find_duplicate_positions(pie):
    """Set of slots claimed by more than one item — the later one wins in the pie"""
    seen = set()
    dupes = set()
    for item in pie.items:
        if item.position in seen:
            dupes.add(item.position)
        seen.add(item.position)
    return dupes

# Flip to True to trace menu and keymap registration in the system console.
# Registration is rebuilt from scratch on every change to a pie's settings, so
# leaving this on floods the console while typing — roughly ten lines per
# keystroke with a handful of pies configured.
DEBUG = False


def _debug(message):
    """Print registration tracing, but only when DEBUG is on"""
    if DEBUG:
        print(f"CocoPie: {message}")
