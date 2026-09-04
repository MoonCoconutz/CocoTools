"""Small shared helpers: locating the preferences, describing shortcuts,
and working out which pies would collide."""

import addon_utils
import bpy
import sys
import os
import json
import re
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
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS, KEYMAP_TYPE_ITEMS,
)

# The key this addon is registered under, and the key its preferences are
# stored against. Taken from the package rather than __name__, which inside a
# submodule would be "CocoPies.utils" and match no registered addon.
ADDON_ID = __package__


def addon_version_string():
    """The addon's version as "v1.9.0", read at call time so both a legacy
    bl_info dict and an extension's blender_manifest.toml resolve the same
    way -- addon_utils.module_bl_info() synthesizes a bl_info-shaped dict
    from the manifest for an extension module, and just returns the real
    thing for a legacy one. Looked up lazily (not imported at module scope)
    because the package __init__ imports this module, so it isn't fully
    loaded yet at import time.
    """
    module = sys.modules.get(ADDON_ID)
    info = addon_utils.module_bl_info(module) if module else None
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


def ensure_keymap_scopes(pie):
    """Guarantee pie.keymap_scopes holds at least one entry, seeding it from
    the pre-multi-scope `keymap_type` field.

    Idempotent, and called defensively before anything reads the scopes --
    same contract as ensure_slot_items(). A pie saved by an older CocoPies (or
    imported from an older preset, or built by defaults.py, which still
    declares a single "keymap_type") arrives with an empty collection; this is
    what silently migrates it, so no stored data has to be rewritten up front.
    """
    if len(pie.keymap_scopes) == 0:
        scope = pie.keymap_scopes.add()
        # Assigning an enum value Blender doesn't know raises, and a preset
        # from a future//hand-edited version could carry one
        try:
            scope.keymap_type = pie.keymap_type
        except TypeError:
            scope.keymap_type = 'WINDOW'
    return pie.keymap_scopes


def normalized_scope(value):
    """A scope this code can actually use, falling back to 'WINDOW'.

    A stored scope can come back as "" or as something KEYMAP_CONFIG has never
    heard of. Blender saves an EnumProperty by integer, so a value that no
    longer lands on a real item reads back as the empty string -- which is
    exactly what happened when an item was once inserted mid-list and
    renumbered everything after it (see items.py). A pie in that state used to
    fall out of the Pie Menus list altogether: its group key matched no
    section, so no section drew it and it was invisible and un-fixable.

    Resolving to 'WINDOW' instead keeps such a pie visible, editable, and
    registered somewhere sane. Applied here rather than at each call site so
    the list, the keymap registration and the conflict check cannot end up
    disagreeing about which scope a pie has.
    """
    return value if value in KEYMAP_CONFIG else 'WINDOW'


def pie_scope_types(pie):
    """Every scope enum value this pie is registered into, de-duplicated and
    in the order the user listed them.

    Never empty, and every entry is a key of KEYMAP_CONFIG -- see
    normalized_scope().
    """
    ensure_keymap_scopes(pie)
    seen = []
    for scope in pie.keymap_scopes:
        value = normalized_scope(scope.keymap_type)
        if value not in seen:
            seen.append(value)
    return seen or ['WINDOW']


def keymap_names_for_pie(pie):
    """Union of the keymap names a pie actually ends up registered in, across
    all of its scopes"""
    names = set()
    for scope_type in pie_scope_types(pie):
        names |= keymap_names_for(scope_type)
    return names


# The Pie Menus list is drawn as one section per editor: a collapsible heading,
# then that editor's pies as plain rows (see draw_left_column and
# draw_pie_row). Grouping is display-only and read-only -- nothing here ever
# reorders prefs.pie_menus. Three earlier attempts at this feature are worth
# not repeating: physically re-sorting the collection with .move() corrupted
# pies' stored data; drawing the section header inside a UIList's draw_item
# made the header part of the first pie's row, so it swallowed that row's
# click and its selection highlight; and one template_list per section drew a
# box around each, which read as stacked panels rather than one list.

# Section order: the Editor dropdown's own order (Window, then Modes, then
# Editors), skipping its bare ("", "Modes", "") heading rows since those
# carry no real scope id.
_GROUP_SCOPE_ORDER = [item[0] for item in KEYMAP_TYPE_ITEMS if item[0]]

# A pie spanning more than one editor belongs to no single one of them, so it
# gets its own section rather than being filed under just the first.
MULTI_GROUP_KEY = 'MULTI'
MULTI_GROUP_LABEL = "Multiple Editors"

# Every section that can ever exist, in display order. Fixed and known up
# front, which is what lets a collapsed section be remembered by key.
GROUP_KEYS = [MULTI_GROUP_KEY] + _GROUP_SCOPE_ORDER


def pie_group_key(pie):
    """Which section this pie belongs in -- a scope id, or MULTI_GROUP_KEY"""
    scopes = pie_scope_types(pie)
    if len(scopes) > 1:
        return MULTI_GROUP_KEY
    return scopes[0] if scopes else 'WINDOW'


def group_key_label(key):
    """The heading text for a section key"""
    if key == MULTI_GROUP_KEY:
        return MULTI_GROUP_LABEL
    return next((item[1] for item in KEYMAP_TYPE_ITEMS if item[0] == key), key)


def pie_group_label(pie):
    """The heading text of the section this pie belongs under"""
    return group_key_label(pie_group_key(pie))


def pie_menu_groups(pie_menus):
    """The sections to draw, as [(key, label, [collection indices])].

    Only sections that actually hold a pie are returned, in GROUP_KEYS
    order; within a section, pies keep their stored order.
    """
    by_key = {}
    for index, pie in enumerate(pie_menus):
        by_key.setdefault(pie_group_key(pie), []).append(index)

    groups = [(key, group_key_label(key), by_key[key])
              for key in GROUP_KEYS if key in by_key]

    # A pie carrying a scope this Blender doesn't know would otherwise be
    # silently dropped from every section, and so from the list entirely
    known = set(GROUP_KEYS)
    for key in by_key:
        if key not in known:
            groups.append((key, group_key_label(key), by_key[key]))

    return groups


def collapsed_group_keys(prefs):
    """Section keys the user has collapsed, as a set.

    Unreadable or missing state means "nothing collapsed" rather than an
    error: a section that fails to open is a section the user cannot reach.
    """
    raw = getattr(prefs, "collapsed_groups", "") or ""
    if not raw:
        return set()
    try:
        keys = json.loads(raw)
    except ValueError:
        return set()
    return set(keys) if isinstance(keys, list) else set()


def set_group_collapsed(prefs, key, collapsed):
    """Collapse or expand one section, keeping the stored list sorted"""
    keys = collapsed_group_keys(prefs)
    if collapsed:
        keys.add(key)
    else:
        keys.discard(key)
    prefs.collapsed_groups = json.dumps(sorted(keys))


def _keymaps_overlap(pie_a, pie_b):
    """Whether either pie's binding is live where the other one's is.

    Compared by the keymaps they actually register into rather than by scope
    name, so a global pie no longer reports a conflict against one scoped to an
    editor it never reaches. A union across each pie's scopes, so two
    multi-scope pies collide as soon as any one of their editors overlaps.

    Ancestors count on both sides, exactly as they do in find_external_conflicts
    -- Blender evaluates a keymap's ancestors too, so a pie in "3D View" fires
    inside Sculpt just as surely as one registered there. A plain name
    intersection missed that, and the mismatch was visible in the panel: the
    Sculpt Brush Select pie on W was warned about Blender's own W binding in
    "3D View" while an identical CocoPies pie in "3D View" drew no warning at
    all. Tested both directions.

    Asymmetric on purpose, hence the two-sided test: a "3D View" binding is
    live in Sculpt, a Sculpt one is not live elsewhere in the 3D View, and
    either way round the two do fight while sculpting. The always-live keymaps
    _ancestor_keymaps() adds ("Window", "Screen", "User Interface"...) cannot
    make this fire spuriously, since keymap_names_for() never returns one of
    them for a real scope -- only the ancestor sets contain them.
    """
    names_a = keymap_names_for_pie(pie_a)
    names_b = keymap_names_for_pie(pie_b)
    return bool(names_a & _ancestor_keymaps(names_b)
                or names_b & _ancestor_keymaps(names_a))


def find_shortcut_conflicts(prefs, pie, index):
    """Names of other *enabled* pie menus that would fight over the same shortcut"""
    if not pie.enabled:
        return []

    # A pie with no key registers no keymap item at all (it is reached from
    # another pie's slot instead), so it can neither take a shortcut from
    # anything nor lose one to it. Without this, every shortcut-less pie
    # reported every other shortcut-less pie as a conflict -- they all match
    # on the empty key.
    if not pie.key:
        return []

    conflicts = []
    for i, other in enumerate(prefs.pie_menus):
        if i == index or not other.enabled or not other.key:
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

        # _values_contend, not equality: PRESS and CLICK_DRAG are different
        # values that compete for the same physical key-down, and Blender
        # resolves PRESS first -- so one CocoPies pie silently swallows the
        # other's key. The external check has always known this; comparing
        # values exactly here meant the same collision was reported when the
        # winner belonged to Blender and passed over when it was another pie.
        if (other.key.upper() == pie.key.upper()
                and modifiers_match
                and _values_contend(pie.event_value, other.event_value)
                and _keymaps_overlap(other, pie)):
            conflicts.append(other.name)
    return conflicts


# Every CocoPies-owned operator that has ever been bound to a keymap item,
# including ones no longer bound by the current code. Items created by an
# older version outlive it -- they sit in the saved keyconfig and keep firing
# -- so a retired idname has to stay in this set, not be dropped from it.
# `cocopie.tap_toggle_direction` is exactly that case: it used to be bound to
# CLICK directly, and those leftovers fired the toggle on a plain tap no
# matter what Tap to Toggle was set to. Used both to sweep stale items on
# unregister and to keep CocoPies out of its own conflict scan.
COCOPIE_KEYMAP_IDNAMES = {
    'cocopie.hold_or_tap',
    'cocopie.tap_toggle_direction',
    'cocopie.execute_command',
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
# family rather than an equality test. Used by both conflict checks -- see
# find_shortcut_conflicts, which compared values exactly until it did.
_PRESS_FAMILY = frozenset({'PRESS', 'CLICK', 'DOUBLE_CLICK', 'CLICK_DRAG', 'ANY'})
_RELEASE_FAMILY = frozenset({'RELEASE', 'ANY'})

# Rebuilt lazily; None means "not scanned yet". The scan walks every keymap in
# the user keyconfig, so it is cached rather than repeated on each redraw.
_external_index = None


def invalidate_external_shortcut_index():
    """Drop the cached scan of everyone else's shortcuts.

    Called whenever CocoPies re-registers, which is also when another addon is
    most likely to have been enabled or disabled behind us.
    """
    global _external_index, _addon_names
    _external_index = None
    # Rebuilt with it: re-registering is also when an addon is most likely to
    # have been enabled or disabled, which is exactly what this map describes.
    _addon_names = None


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


# The property that says which *thing* a generic operator was bound to. Half
# the interesting bindings in a keyconfig run through a handful of operators
# that do nothing on their own -- wm.tool_set_by_id is every tool shortcut,
# wm.call_panel every popup -- so without this a row read "Set Tool by Name",
# naming the operator and not the tool, and gave the user nothing to act on.
_DETAIL_PROPS = {
    'wm.call_menu': 'name',
    'wm.call_menu_pie': 'name',
    'wm.call_panel': 'name',
    'wm.tool_set_by_id': 'name',
    'wm.tool_set_by_name': 'name',
    'wm.context_toggle': 'data_path',
    'wm.context_toggle_enum': 'data_path',
    'wm.context_set_enum': 'data_path',
    'wm.context_cycle_enum': 'data_path',
    'wm.context_menu_enum': 'data_path',
    'wm.context_pie_enum': 'data_path',
    'object.mode_set': 'mode',
    'object.mode_set_with_submode': 'mode',
    'mesh.select_mode': 'type',
}

# Menu and panel ids the detail is pulled from, minus the parts that carry no
# information: every id is <SPACE>_MT_<what> or <SPACE>_PT_<what>, and a pie's
# id ends in _pie. Stripped only to compare against the label, never to display.
_ID_NOISE = re.compile(r'^[A-Z0-9]+_(MT|PT)_|_pie$')


# {module name: the addon's display name}, rebuilt with the shortcut index.
_addon_names = None


def _addon_name_map():
    """Every enabled addon's module name mapped to the name the user knows it by.

    `preferences.addons` is keyed by module name, and module_bl_info() reads the
    display name from either a legacy bl_info or an extension's manifest -- so
    this covers extensions and old-style addons alike. A module missing from
    sys.modules (its repository switched off, say) still gets an entry, falling
    back to the last segment of its module path rather than dropping out.
    """
    global _addon_names
    if _addon_names is None:
        names = {}
        for key in bpy.context.preferences.addons.keys():
            module = sys.modules.get(key)
            info = addon_utils.module_bl_info(module) if module else None
            names[key] = (info or {}).get('name') or key.rpartition('.')[2]
        _addon_names = names
    return _addon_names


def _owner_addon(module_name):
    """The addon a class's __module__ belongs to, or "" for Blender's own.

    Longest prefix wins, since a class lives in a submodule of its addon
    ("bl_ext.user_default.hardops.ui.nodes_menu" belongs to
    "bl_ext.user_default.hardops"). Blender's built-in operators report
    "bpy.types" and its Python UI reports "bl_ui.*"; neither matches an addon
    module, so both correctly come back empty.
    """
    if not module_name:
        return ""
    names = _addon_name_map()
    parts = module_name.split('.')
    for cut in range(len(parts), 0, -1):
        candidate = '.'.join(parts[:cut])
        if candidate in names:
            return names[candidate]
    return ""


def _operator_rna_name(idname):
    """"mesh.delete" -> "MESH_OT_delete", the name it is registered under"""
    category, _dot, name = idname.partition('.')
    return f"{category.upper()}_OT_{name}" if name else ""


def _binding_owner(kmi, detail):
    """Which addon a keymap item leads to -- "" for Blender's own, or unknown.

    A keymap item records nothing about who created it: `keyconfigs.addon`
    holds every addon's items in one undifferentiated list, so "some addon did
    this" was as much as the panel could say. The owner is recoverable anyway,
    because a registered Python class remembers the module it was defined in --
    so the operator's class names the addon directly.

    That fails for exactly the bindings worth naming, though: half an addon's
    shortcuts run through Blender's own wm.call_menu / wm.call_menu_pie, whose
    class is C code belonging to nobody. The menu they point at is the addon's,
    so the detail property is tried second and catches those. Verified against
    this machine's stack: Node Wrangler and HardOps are both found only by that
    second route.
    """
    for name in (_operator_rna_name(kmi.idname), detail):
        if not name:
            continue
        cls = getattr(bpy.types, name, None)
        owner = _owner_addon(getattr(cls, '__module__', "") or "")
        if owner:
            return owner
    return ""


def _kmi_detail(kmi):
    """Which tool/menu/panel/property this binding actually points at, or "".

    Read for display only -- deliberately NOT part of binding_identity(), which
    is what stored suppressions are matched by. Widening that tuple would make
    every suppression the user has already ticked stop matching its binding,
    and it would fail silently: the row would just come back unticked with the
    setting gone.
    """
    prop = _DETAIL_PROPS.get(kmi.idname)
    if not prop:
        return ""
    # An unregistered operator's properties carry nothing at all, and reading
    # a missing one off an arbitrary operator raises rather than returning None
    try:
        value = getattr(kmi.properties, prop, "")
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _label_covers_detail(label, detail):
    """Whether the label already says what the detail would say.

    Blender names a menu binding after the menu ("Face Sets Edit" for
    VIEW3D_MT_sculpt_face_sets_edit_pie), so appending the id there is noise;
    it names a tool binding after the operator ("Set Tool by Name" for
    builtin.select_box), where the id is the whole point. Told apart by asking
    whether the label's words are a subset of the detail's -- true for a label
    derived from the id, false for one that merely shares an operator with it.
    """
    def words(text):
        return {w for w in re.split(r'[^a-z0-9]+', text.lower()) if w}

    label_words = words(label)
    return bool(label_words) and label_words <= words(_ID_NOISE.sub('', detail))


def _build_external_index():
    """Index every non-CocoPies shortcut in the user keyconfig, keyed by key type.

    The user keyconfig is the one Blender actually dispatches from -- it merges
    Blender's defaults, every addon's items and the user's own edits, and its
    `active` flags are the ones that count. CocoPies's own items are mirrored
    into it too, so they are filtered out here or every pie would report a
    conflict with itself.
    """
    index = {}
    wm = bpy.context.window_manager
    kc = merged_keyconfig()
    if kc is None:
        return index

    # Where a binding came from is the useful half of the warning, and it takes
    # both stock keyconfigs to tell apart: present in `default` means Blender
    # ships it, present in `addon` means some addon added it, and neither means
    # the user bound it themselves in the Keymap editor. Absence from `default`
    # alone does not make something an addon's -- a hand-edited binding on a
    # stock operator looks exactly the same from there.
    # Matched on the whole binding, not just the operator id. Generic
    # operators are the reason: wm.call_menu is bound by Blender and by half
    # the addons in a stack, so an idname test labelled Blender's own X delete
    # menu as an add-on's -- misleading anywhere, and actively wrong next to a
    # checkbox offering to switch it off.
    def _identities_in(kc_name):
        found = set()
        other_kc = getattr(wm.keyconfigs, kc_name, None)
        if other_kc is None:
            return found
        for km in other_kc.keymaps:
            for kmi in km.keymap_items:
                found.add(binding_identity(kmi, km.name))
        return found

    default_identities = _identities_in('default')
    addon_identities = _identities_in('addon')

    for km in kc.keymaps:
        for kmi in km.keymap_items:
            # Inactive items are indexed rather than skipped: once CocoPies
            # suppresses one it goes inactive, and dropping it here would take
            # its row -- and its checkbox -- out of the panel, leaving no way
            # to switch it back on. find_external_conflicts filters the ones
            # that are merely disabled from the ones we disabled.
            if not kmi.idname:
                continue
            if kmi.idname in COCOPIE_KEYMAP_IDNAMES:
                continue
            if kmi.idname == 'wm.call_menu_pie':
                menu_name = getattr(kmi.properties, 'name', '') or ''
                if menu_name.startswith('COCOPIE_MT_'):
                    continue
            # Blender first: an addon shipping a binding identical to a stock
            # one does not make the stock one the addon's.
            item_identity = binding_identity(kmi, km.name)
            if item_identity in default_identities:
                source = "Blender"
            elif item_identity in addon_identities:
                source = "Add-on"
            else:
                source = "Custom"

            label = _keymap_item_label(kmi)
            detail = _kmi_detail(kmi)
            index.setdefault(kmi.type, []).append({
                'idname': kmi.idname,
                'label': label,
                'detail': "" if _label_covers_detail(label, detail) else detail,
                'owner': _binding_owner(kmi, detail),
                'keymap': km.name,
                'value': kmi.value,
                'menu': _kmi_menu_name(kmi),
                'active': kmi.active,
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
    """Shortcuts outside CocoPies -- Blender's own or another addon's -- that
    would fight this pie for its key.

    This is the blind spot the pie-vs-pie check leaves: it only ever compared
    CocoPies menus against each other, so a third-party binding on the same key
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

    live_keymaps = _ancestor_keymaps(keymap_names_for_pie(pie))

    prefs = get_prefs()
    suppressed = set()
    if prefs is not None:
        suppressed = {suppression_identity(e) for e in prefs.suppressed_bindings}

    hits = []
    seen = set()
    for other in candidates:
        if other['keymap'] not in live_keymaps:
            continue

        identity = (other['keymap'], other['idname'], pie.key.upper(),
                    other['value'], other['menu'], other['any'],
                    other['shift'], other['ctrl'], other['alt'], other['oskey'])
        is_suppressed = identity in suppressed
        # Something the user switched off in the Keymap editor is not fighting
        # this pie for anything, so it is not a conflict. One CocoPies switched
        # off still gets a row, ticked, so it can be handed back.
        if not other['active'] and not is_suppressed:
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
        hits.append(dict(other, identity=identity, suppressed=is_suppressed))
        if len(hits) >= limit:
            break

    return hits


# --- Suppressing someone else's shortcut -------------------------------------
#
# See COCOPIE_SuppressedBinding for why this exists at all. The short version:
# a native PRESS binding beats a CLICK/CLICK_DRAG pie on the same key at any
# keymap position, so the only way a Quick Tap pie can own its key is for the
# other item to be switched off while CocoPies is loaded.


def _kmi_menu_name(kmi):
    """properties.name for the menu-calling operators, "" for everything else.

    Reading .properties.name off an arbitrary operator raises rather than
    returning None, and an unregistered operator's properties carry nothing at
    all -- both of which happen while scanning a live keyconfig.
    """
    if kmi.idname not in ('wm.call_menu', 'wm.call_menu_pie'):
        return ""
    try:
        return getattr(kmi.properties, 'name', '') or ""
    except Exception:
        return ""


def binding_identity(kmi, keymap_name):
    """The content-based identity of a keymap item, as a plain tuple"""
    return (
        keymap_name,
        kmi.idname,
        kmi.type,
        kmi.value,
        _kmi_menu_name(kmi),
        bool(kmi.any),
        bool(kmi.shift),
        bool(kmi.ctrl),
        bool(kmi.alt),
        bool(kmi.oskey),
    )


def suppression_identity(entry):
    """The same tuple, read back off a stored COCOPIE_SuppressedBinding"""
    return (
        entry.keymap,
        entry.idname,
        entry.key_type,
        entry.value,
        entry.menu_name,
        bool(entry.any_modifier),
        bool(entry.shift),
        bool(entry.ctrl),
        bool(entry.alt),
        bool(entry.oskey),
    )


def find_suppression(prefs, identity):
    """The stored entry matching this identity, or None"""
    for entry in prefs.suppressed_bindings:
        if suppression_identity(entry) == identity:
            return entry
    return None


def merged_keyconfig():
    """The one keyconfig that holds every binding in play -- what to *read*.

    `keyconfigs.user` is the merged runtime config: Blender's defaults, every
    addon's items and the user's own edits, all in one list, and it is what
    Blender dispatches from.

    NOT `keyconfigs.active`, which is what the conflict scan used to read.
    `active` is the selected keymap *preset*, and a preset is a partial
    keyconfig -- it holds only the keymaps it happened to save. Measured live
    on this machine with the "MyPreset" preset loaded: `active` had 16 keymaps
    and 936 items against `user`'s 293 and 3682. Scanning it went wrong three
    ways at once. It missed live conflicts, because 277 keymaps were never
    looked at -- Blender's own Delete in "User Interface" never showed against
    the Mesh Delete pie. It invented dead ones, reporting a "Sticky UV Editor"
    binding that exists only inside the saved preset file and nowhere in the
    live config, complete with a checkbox offering to switch off something
    that was not running. And it mislabelled what it did find, calling a stock
    Object Mode binding a custom 3D View one, because the preset's copy is
    what got compared against `default`.

    The clinching evidence that `active` is not what fires: with a preset
    loaded it contains no CocoPies keymap items at all, and the pies still
    open.

    Writing is the opposite case and still goes through live_keyconfigs() --
    see there.
    """
    kcs = getattr(bpy.context.window_manager, 'keyconfigs', None)
    if kcs is None:
        return None
    return getattr(kcs, 'user', None) or getattr(kcs, 'active', None)


def live_keyconfigs():
    """The keyconfigs a suppression has to be *written* into.

    Reading is merged_keyconfig()'s job, and only writing needs this list.
    `keyconfigs.user` is NOT reliably the one a write has to land in. Selecting a keymap preset makes
    it `keyconfigs.active` while "Blender user" stays in the list untouched --
    so on a machine running a preset (this one runs "MyPreset"), everything
    read from or written to `user` describes a keyconfig Blender is not
    dispatching from. Suppression aimed there switched off an item nobody was
    consulting, and left the real one enabled and still stealing the key.

    Both are returned, deduplicated: `active` is what counts, and `user` is the
    same object whenever no preset is loaded.
    """
    kcs = getattr(bpy.context.window_manager, 'keyconfigs', None)
    if kcs is None:
        return []
    found = []
    for name in ('active', 'user'):
        kc = getattr(kcs, name, None)
        if kc is not None and not any(kc == seen for seen in found):
            found.append(kc)
    return found


def _iter_matching_items(identities):
    """Walk the live keyconfigs, yielding (identity, kmi) for wanted bindings.

    `default` and `addon` are deliberately not walked: they are the templates
    the active keyconfig is built from, and switching an item off in either
    changes nothing about what fires.
    """
    for kc in live_keyconfigs():
        for km in kc.keymaps:
            for kmi in list(km.keymap_items):
                identity = binding_identity(kmi, km.name)
                if identity in identities:
                    yield identity, kmi


def record_prior_state(prefs, entry):
    """Set entry.restore_on_unregister from the binding's state right now.

    Called once, when a suppression is created -- never again. Deciding this at
    apply time instead looks reasonable and is wrong: suppression switches the
    item off, Save Preferences writes that off-state into userpref.blend, and
    from the next launch onward every apply would see an already-off item,
    conclude the user had disabled it by hand, and decline to restore it. The
    key would then stay dead after CocoPies was disabled -- exactly what
    storing suppressions here instead of applying them permanently is meant to
    prevent. The honest question is "was it on when the box was ticked", and
    that can only be answered at ticking time.
    """
    identity = suppression_identity(entry)
    entry.restore_on_unregister = any(
        kmi.active for _i, kmi in _iter_matching_items({identity}))
    return entry.restore_on_unregister


def apply_suppressions(prefs):
    """Switch off every binding the user has ticked.

    Deliberately does not touch restore_on_unregister; see record_prior_state
    for why that flag is written once at ticking time and read-only after.
    """
    if not len(prefs.suppressed_bindings):
        return 0
    wanted = {suppression_identity(e) for e in prefs.suppressed_bindings}
    touched = 0
    for _identity, kmi in _iter_matching_items(wanted):
        if kmi.active:
            kmi.active = False
            touched += 1
    return touched


def restore_suppressions(prefs):
    """Switch back on everything apply_suppressions switched off.

    Called from unregister, so disabling or uninstalling CocoPies hands the
    user's keymap back exactly as it was found. Note this restores the running
    session only: an `active = False` that reached userpref.blend via Save
    Preferences stays there until preferences are saved again afterwards.
    """
    if not len(prefs.suppressed_bindings):
        return 0
    wanted = {suppression_identity(e): e
              for e in prefs.suppressed_bindings if e.restore_on_unregister}
    if not wanted:
        return 0
    touched = 0
    for _identity, kmi in _iter_matching_items(set(wanted)):
        if not kmi.active:
            kmi.active = True
            touched += 1
    return touched


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
        print(f"CocoPies: {message}")
