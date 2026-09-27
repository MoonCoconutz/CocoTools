"""Keymaps as a diff against stock Blender + add-ons, not as a preset copy.

A keymap preset is a copy of whole keymaps, add-on items included. Imported on
another machine those copies sit next to the add-on's own registration, so
every add-on shortcut you touched turns up twice. Blender itself avoids this on
the machine where the edit was made by storing the user keymap as a diff
against default+addon; that link is what an export throws away.

This module keeps it. Export compares `keyconfigs.user` (what actually fires)
with `keyconfigs.default` + `keyconfigs.addon` and records only three kinds of
change per keymap: an item modified (other key, switched off, other
settings), an item removed, an item added. Import finds the matching item on
the target machine and edits it in place, so nothing is duplicated.

The base is the *stock* keyconfig, not `keyconfigs.active`: with a preset such
as MyPreset loaded, `is_user_modified` is relative to that preset, and its own
changes would never make it into the backup.

Export, import, the reset pass and a single revert all go through one
pairing (_pair): every user item is matched with the stock or add-on item it
is a version of. Import pairs this machine's items the same way and edits the
one paired with the backup's stock item, so it is found whatever this machine
did to it, and the report can say what it was here before.
"""

import json

import bpy


KEY_FIELDS = (
    "type", "value", "any", "shift", "ctrl", "alt", "oskey", "hyper",
    "key_modifier", "direction", "repeat", "active",
)

_MENU_CALLERS = {"wm.call_menu", "wm.call_menu_pie", "wm.call_panel"}

_MAP_TYPES = ('KEYBOARD', 'MOUSE', 'NDOF', 'TEXTINPUT', 'TIMER')


def _jsonable(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, set):
        return sorted(value)
    try:
        return [_jsonable(v) for v in value]
    except TypeError:
        return str(value)


# ---------------------------------------------------------------------------
# Reading items

def _read_props(ptr):
    """Explicitly set properties as plain JSON values, nested operator groups
    included: a macro keeps its settings there (Rip Move's MESH_OT_rip)."""
    out = {}
    for prop in ptr.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type" or prop.type == 'COLLECTION':
            continue
        try:
            if not ptr.is_property_set(ident):
                continue
            value = getattr(ptr, ident)
        except Exception:
            continue
        if prop.type == 'POINTER':
            nested = _read_props(value) if value is not None else {}
            if nested:
                out[ident] = nested
        else:
            out[ident] = _jsonable(value)
    return out


def item_props(kmi):
    ptr = kmi.properties
    return _read_props(ptr) if ptr is not None else {}


def item_key(kmi):
    return {f: _jsonable(getattr(kmi, f)) for f in KEY_FIELDS}


def _key_equal(a, b):
    return all(a[f] == b[f] for f in KEY_FIELDS if f in a and f in b)


def _without_active(key):
    return {f: v for f, v in key.items() if f != "active"}


def _props_within(have, want):
    """True when `have` sets nothing that `want` does not set the same way.

    `have` may lack settings: a keymap preset's copy of an add-on item loses
    the ones it stored before the add-on registered its operator (measured:
    Zen UV's Sticky UV Editor). A lost setting is not an edit; a changed or
    added one is (measured: Delete on X with its confirm switched off).
    """
    for name, value in have.items():
        if name not in want:
            return False
        other = want[name]
        if isinstance(value, dict) and isinstance(other, dict):
            if not _props_within(value, other):
                return False
        elif value != other:
            return False
    return True


def _identity(cmd, props):
    """What an item does, whatever key it is on."""
    if "propvalue" in cmd:
        return ("modal", cmd["propvalue"])
    return (cmd["idname"], json.dumps(props, sort_keys=True))


def _cmd(spec):
    return {"propvalue": spec["propvalue"]} if "propvalue" in spec else {"idname": spec["idname"]}


def _spec_identity(spec):
    return _identity(_cmd(spec), spec.get("props", {}))


class _Item:
    """One keymap item, read once."""
    __slots__ = ("kmi", "modal", "origin", "cmd", "key", "props", "ident")

    def __init__(self, kmi, modal, origin=None):
        self.kmi = kmi
        self.modal = modal
        self.origin = origin
        self.cmd = {"propvalue": kmi.propvalue} if modal else {"idname": kmi.idname}
        self.refresh()

    def refresh(self):
        self.key = item_key(self.kmi)
        self.props = {} if self.modal else item_props(self.kmi)
        self.ident = _identity(self.cmd, self.props)

    def state(self):
        return {"key": self.key, "props": self.props}


def _user_items(km):
    return [_Item(kmi, km.is_modal) for kmi in km.keymap_items]


def _base_items(kcs, km):
    """The stock and add-on items `km` is merged from."""
    out = []
    for kc, origin in ((kcs.default, "blender"), (kcs.addon, "addon")):
        src = kc.keymaps.find(km.name, space_type=km.space_type, region_type=km.region_type)
        if src is not None:
            out.extend(_Item(kmi, km.is_modal, origin) for kmi in src.keymap_items)
    return out


def _same_key_but_active(a, b):
    return _key_equal(_without_active(a), _without_active(b))


def _pair(users, bases, modal):
    """Pair each user item with the stock or add-on item it is a version of.

    Same command and properties first: exact key, then the same key switched
    on or off, then keymap order. So an unchanged item is never mistaken for
    a moved one when a command sits on several keys (G, R and S all run
    transform operators; wm.call_menu sits on dozens), and a switched-off
    item stays the stock item it was, however the keymap is ordered (measured:
    View Center moved to F with a switched-off copy left on Button4 paired
    either way round). Then what is left pairs by command and key, ignoring
    properties and on/off: a user copy can carry other properties than the
    item it came from -- edited in the keymap editor, or lost by a keymap
    preset -- and it is still one item. Recorded as "remove + add" it would,
    on import, remove the add-on's merged item: the permanent "user deleted
    this" entry.

    Returns (pairs, unpaired user items, unpaired stock/add-on items).
    """
    groups = {}
    for u in users:
        groups.setdefault(u.ident, ([], []))[0].append(u)
    for b in bases:
        groups.setdefault(b.ident, ([], []))[1].append(b)
    pairs, left_users, left_bases = [], [], []
    for group_users, group_bases in groups.values():
        for same in (_key_equal, _same_key_but_active):
            for u in list(group_users):
                for b in group_bases:
                    if same(u.key, b.key):
                        pairs.append((u, b))
                        group_users.remove(u)
                        group_bases.remove(b)
                        break
        while group_users and group_bases:
            pairs.append((group_users.pop(0), group_bases.pop(0)))
        left_users.extend(group_users)
        left_bases.extend(group_bases)
    if not modal:
        for u in list(left_users):
            for b in left_bases:
                if u.cmd == b.cmd and _same_key_but_active(u.key, b.key):
                    pairs.append((u, b))
                    left_users.remove(u)
                    left_bases.remove(b)
                    break
    return pairs, left_users, left_bases


# ---------------------------------------------------------------------------
# Export

def _spec(item):
    spec = {"key": item.key, **item.cmd}
    if "idname" in item.cmd:
        spec["props"] = item.props
        spec["owner"] = item_owner(item.cmd["idname"], item.props)
    if item.origin:
        spec["origin"] = item.origin
    return spec


def _changes(kcs, km):
    """How one user keymap differs from stock + add-ons:
    [(kind, spec, user item, stock item)], kind "modified", "removed" or "added"."""
    pairs, extra_users, extra_bases = _pair(_user_items(km), _base_items(kcs, km), km.is_modal)
    out = []
    for u, b in pairs:
        edited = not _props_within(u.props, b.props)
        if edited or not _key_equal(u.key, b.key):
            spec = _spec(b)
            spec["new_key"] = u.key
            if edited:
                spec["new_props"] = u.props
            out.append(("modified", spec, u, b))
    out.extend(("removed", _spec(b), None, b) for b in extra_bases)
    # An added item that is switched off does nothing. In practice these are
    # switched-off add-on copies a keymap preset baked in, which never
    # disabled anything in the first place.
    out.extend(("added", _spec(u), u, None) for u in extra_users if u.key["active"])
    return out


def export_keymaps():
    """Return the diff of every keymap, plus the keyconfig preferences."""
    kcs = bpy.context.window_manager.keyconfigs
    out = {"keymaps": [], "keyconfig_prefs": {}}

    kc_prefs = kcs.default.preferences
    if kc_prefs is not None:
        for prop in kc_prefs.bl_rna.properties:
            ident = prop.identifier
            # bl_idname reads back as garbage ("\x06"), and is not a setting.
            if ident == "rna_type" or ident.startswith("bl_") or prop.is_readonly:
                continue
            out["keyconfig_prefs"][ident] = _jsonable(getattr(kc_prefs, ident))

    for km in kcs.user.keymaps:
        changes = _changes(kcs, km)
        if not changes:
            continue
        entry = {"name": km.name, "space_type": km.space_type, "region_type": km.region_type,
                 "modal": km.is_modal, "modified": [], "removed": [], "added": []}
        for kind, spec, _user, _base in changes:
            entry[kind].append(spec)
        out["keymaps"].append(entry)
    return out


def item_owner(idname, props):
    """The add-on a shortcut belongs to (its id), or "" for Blender itself.

    A keymap item records nothing about who made it, but a registered Python
    class remembers its module. The operator is tried first; for Blender's
    generic wm.call_menu* the menu or panel it opens is what tells add-ons
    apart. C operators have no Python class and Blender's own Python lives in
    bl_ui / bl_operators, so both read as Blender. Recorded at export time,
    because on the target machine the add-on may not be installed at all.
    """
    cls = None
    if idname in _MENU_CALLERS and props.get("name"):
        cls = getattr(bpy.types, props["name"], None)
    elif "." in idname:
        mod, op = idname.split(".", 1)
        cls = getattr(bpy.types, f"{mod.upper()}_OT_{op}", None)
    module = getattr(cls, "__module__", "") or ""
    if not module:
        return ""
    for key in bpy.context.preferences.addons.keys():
        if module == key or module.startswith(key + "."):
            return key.rsplit(".", 1)[-1]
    parts = module.split(".")
    if parts[0] in {"bl_ui", "bl_operators", "bpy"}:
        return ""
    return parts[2] if parts[0] == "bl_ext" and len(parts) > 2 else parts[0]


# ---------------------------------------------------------------------------
# Writing items

def _set_type(kmi, event_type):
    """Set the key, switching the item's map_type first when it has to.

    An item's `type` only accepts events of its current map_type: a mouse
    item refuses "F" outright. The keymap editor switches map_type for you;
    RNA does not, and the refusal was swallowed, so moving Fill Tool's Middle
    Mouse item to F (or back) silently did nothing.
    """
    try:
        kmi.type = event_type
        return
    except Exception:
        pass
    for map_type in _MAP_TYPES:
        try:
            kmi.map_type = map_type
            kmi.type = event_type
            return
        except Exception:
            continue


def _set_key(kmi, key):
    for f in KEY_FIELDS:
        if f not in key:
            continue
        if f == "type":
            _set_type(kmi, key["type"])
            continue
        try:
            setattr(kmi, f, key[f])
        except Exception:
            pass


def _write_props(ptr, props):
    """Leave exactly `props` set: what the backup sets, and nothing else."""
    for prop in ptr.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type" or prop.type == 'COLLECTION':
            continue
        try:
            if ident not in props:
                if ptr.is_property_set(ident):
                    ptr.property_unset(ident)
                continue
            value = props[ident]
            if prop.type == 'POINTER':
                if isinstance(value, dict):
                    _write_props(getattr(ptr, ident), value)
                continue
            if prop.type == 'ENUM' and prop.is_enum_flag:
                # A list is refused without an error; the item then never
                # matched its spec and every import added it again.
                value = set(value)
            setattr(ptr, ident, value)
        except Exception:
            continue


def _set_state(kmi, key, props):
    if props is not None and kmi.properties is not None:
        _write_props(kmi.properties, props)
    # Writing a key field also marks the keymap as edited. Properties written
    # alone are not: they stay in memory, is_user_modified stays False, and
    # they are gone after a restart (measured on 5.2). So the key comes last,
    # and always.
    _set_key(kmi, key)


def _create(km, cmd, key, props):
    try:
        if "propvalue" in cmd:
            kmi = km.keymap_items.new_modal(cmd["propvalue"], key["type"], key["value"])
        else:
            kmi = km.keymap_items.new(cmd["idname"], key["type"], key["value"])
    except Exception:
        return None
    _set_state(kmi, key, props)
    return kmi


def _command_exists(spec):
    """False for a shortcut whose operator, or the menu or panel it opens, is
    not registered: it belongs to an add-on that is not running here.
    (keymap_items.new() accepts an unknown operator without complaint.)"""
    if "propvalue" in spec:
        return True
    try:
        mod, op = spec["idname"].split(".", 1)
        getattr(getattr(bpy.ops, mod), op).get_rna_type()
    except Exception:
        return False
    name = spec.get("props", {}).get("name") if spec["idname"] in _MENU_CALLERS else None
    return not name or hasattr(bpy.types, name)


# ---------------------------------------------------------------------------
# Import

def _entry(word, keymap, owner, what, event, before="", after="", undo=None):
    return {"word": word, "owner": owner, "keymap": keymap, "what": what, "event": event,
            "before": before, "after": after, "undo": undo}


def _spec_entry(word, keymap, spec, km, event, before="", after="", undo=None):
    return _entry(word, keymap, spec.get("owner", ""), describe(spec, km), event, before, after, undo)


def _not_here(spec):
    """Why a shortcut from the backup has nothing to act on here."""
    owner = spec.get("owner", "")
    if not _command_exists(spec):
        return f"Skipped: {owner} is not enabled here" if owner else "Skipped: its command does not exist here"
    if spec.get("origin") == "addon":
        return f"Skipped: {owner or 'its add-on'} does not have this shortcut here"
    return "Skipped: not in this Blender's own keymap"


def _take_base(bases, spec, taken):
    ident = _spec_identity(spec)
    for b in bases:
        if id(b) not in taken and b.ident == ident and _key_equal(b.key, spec["key"]):
            taken.add(id(b))
            return b
    return None


def _base_ref(item):
    return {**item.cmd, "key": item.key, "props": item.props}


def _undo(loc, cmd, base, before, after):
    """How to put one shortcut back: the item paired with `base` (or, without
    one, an added item in state `after`) goes back to state `before`. A state
    of None means the item did not exist."""
    return {"loc": loc, "cmd": cmd, "base": base, "before": before, "after": after}


def _known_props(rna, props):
    """`props` without the settings the operator `rna` does not have."""
    out = {}
    for name, value in props.items():
        prop = rna.properties.get(name)
        if prop is None or prop.type == 'COLLECTION':
            continue
        if prop.type == 'POINTER':
            if isinstance(value, dict):
                nested = _known_props(prop.fixed_type, value)
                if nested:
                    out[name] = nested
        else:
            out[name] = value
    return out


def _normalized(spec):
    """A backup spec as this Blender can hold it.

    A setting this Blender's operator does not have can never be written, so
    the item would never compare equal to its spec: every import added it
    again and the reset pass took it away. Dropped here, once, both sides
    compare what can exist.
    """
    if "propvalue" in spec:
        return spec
    try:
        mod, op = spec["idname"].split(".", 1)
        rna = getattr(getattr(bpy.ops, mod), op).get_rna_type()
    except Exception:
        return spec
    spec = {**spec, "props": _known_props(rna, spec.get("props", {}))}
    if "new_props" in spec:
        new_props = _known_props(rna, spec["new_props"])
        if _props_within(new_props, spec["props"]):
            del spec["new_props"]
        else:
            spec["new_props"] = new_props
    return spec


def import_keymaps(data, reset_extra=True):
    """Apply a diff from export_keymaps() to this machine's user keyconfig.

    Safe to run twice: whatever is already as in the backup is logged as
    ALREADY and left alone. Returns one dict per shortcut: what happened in
    words, the key before and after on this machine, the add-on it belongs
    to, and an `undo` recipe for apply_undo().
    """
    kcs = bpy.context.window_manager.keyconfigs
    data = {**data, "keymaps": [
        {**e, **{kind: [_normalized(s) for s in e.get(kind, [])] for kind in ("modified", "removed", "added")}}
        for e in data.get("keymaps", [])]}
    entries = []
    _apply_keyconfig_prefs(kcs, data.get("keyconfig_prefs", {}), entries)
    # Keyconfig preferences rebuild the stock keymap, and add-ons switched on
    # just before this registered theirs: the user keyconfig has to be
    # re-merged before anything is looked up in it.
    kcs.update()
    for entry in data.get("keymaps", []):
        _apply_entry(kcs, entry, reset_extra, entries)
    if reset_extra:
        _reset_changes_not_in(data, kcs, entries)
    return entries


def _apply_keyconfig_prefs(kcs, values, entries):
    kc_prefs = kcs.default.preferences
    if kc_prefs is None:
        return
    props = kc_prefs.bl_rna.properties
    for name, value in values.items():
        prop = props.get(name)
        # 1.0 backups carry bl_idname, read back as garbage: never write it.
        if prop is None or prop.is_readonly or name.startswith("bl_"):
            continue
        old = _jsonable(getattr(kc_prefs, name))
        if old == value:
            continue
        try:
            setattr(kc_prefs, name, value)
        except Exception as e:
            entries.append(_entry("FAILED", "Keymap settings", "", prop.name, f"Could not set it: {e}"))
            continue
        entries.append(_entry("CHANGED", "Keymap settings", "", prop.name, "Setting changed",
                              str(old), str(value)))


def _apply_entry(kcs, entry, reset_extra, entries):
    name = entry["name"]
    specs = [(kind, spec) for kind in ("modified", "removed", "added") for spec in entry.get(kind, [])]
    km = kcs.user.keymaps.find(name, space_type=entry["space_type"], region_type=entry["region_type"])
    if km is None:
        for _kind, spec in specs:
            entries.append(_spec_entry("SKIPPED", name, spec, None, "Skipped: its keymap does not exist here"))
        return
    loc = [name, entry["space_type"], entry["region_type"]]
    users = _user_items(km)
    bases = _base_items(kcs, km)
    pairs, _extra_users, _extra_bases = _pair(users, bases, km.is_modal)
    user_of = {id(b): u for u, b in pairs}
    paired = {id(u) for u, _b in pairs}
    taken = set()
    for kind, spec in specs:
        if kind == "added":
            _apply_added(km, loc, spec, users, paired, entries)
            continue
        base = _take_base(bases, spec, taken)
        user = user_of.get(id(base)) if base is not None else None
        if kind == "modified":
            _apply_modified(km, loc, spec, base, user, reset_extra, entries)
        else:
            _apply_removed(km, loc, spec, base, user, users, entries)


def _apply_modified(km, loc, spec, base, user, reset_extra, entries):
    name = loc[0]
    want_key = spec["new_key"]
    if base is None:
        entries.append(_spec_entry("SKIPPED", name, spec, km, _not_here(spec),
                                   key_label(spec["key"]), key_label(want_key)))
        return
    # Settings: the backup's when it changed them. Otherwise stock when this
    # import restores exactly, or whatever this machine has when it merges.
    if "new_props" in spec:
        want_props = spec["new_props"]
    elif reset_extra:
        want_props = base.props
    else:
        want_props = None

    if user is None:
        # Deleted on this machine, changed in the backup: bring it back so.
        kmi = _create(km, base.cmd, want_key, base.props if want_props is None else want_props)
        if kmi is None:
            entries.append(_spec_entry("FAILED", name, spec, km, "Could not bring it back",
                                       "", key_label(want_key)))
            return
        after = _Item(kmi, km.is_modal)
        entries.append(_spec_entry("CHANGED", name, spec, km, "Brought back and changed", "",
                                   key_label(after.key),
                                   _undo(loc, base.cmd, _base_ref(base), None, after.state())))
        return

    if _key_equal(user.key, want_key) and (
            want_props is None or user.props == want_props
            or ("new_props" not in spec and _props_within(user.props, want_props))):
        entries.append(_spec_entry("ALREADY", name, spec, km, "Already as in the backup"))
        return
    before = user.state()
    _set_state(user.kmi, want_key, want_props)
    user.refresh()
    if user.state() == before:
        entries.append(_spec_entry("SKIPPED", name, spec, km, "Skipped: Blender refused the change",
                                   key_label(before["key"]), key_label(want_key)))
        return
    entries.append(_spec_entry("CHANGED", name, spec, km,
                               change_event(before["key"], user.key, before["props"] != user.props),
                               key_label(before["key"]), key_label(user.key),
                               _undo(loc, base.cmd, _base_ref(base), before, user.state())))


def _apply_removed(km, loc, spec, base, user, users, entries):
    name = loc[0]
    if base is None:
        if _command_exists(spec):
            entries.append(_spec_entry("ALREADY", name, spec, km, "Not in this keymap here"))
        else:
            entries.append(_spec_entry("SKIPPED", name, spec, km, _not_here(spec), key_label(spec["key"])))
        return
    if user is None:
        entries.append(_spec_entry("ALREADY", name, spec, km, "Already removed"))
        return
    before = user.state()
    km.keymap_items.remove(user.kmi)
    users.remove(user)
    entries.append(_spec_entry("REMOVED", name, spec, km, "Removed, as in the backup",
                               key_label(before["key"]), "",
                               _undo(loc, base.cmd, _base_ref(base), before, None)))


def _apply_added(km, loc, spec, users, paired, entries):
    name = loc[0]
    cmd, key, props = _cmd(spec), spec["key"], spec.get("props", {})
    for u in users:
        if u.cmd != cmd or not _key_equal(u.key, key):
            continue
        # The same item, or a stock/add-on one it is a copy of that lost
        # settings (a preset's baked copy): adding it would make a duplicate.
        if u.props == props or (id(u) in paired and _props_within(props, u.props)):
            entries.append(_spec_entry("ALREADY", name, spec, km, "Already added"))
            return
    if not _command_exists(spec):
        entries.append(_spec_entry("SKIPPED", name, spec, km, _not_here(spec), "", key_label(key)))
        return
    kmi = _create(km, cmd, key, props)
    if kmi is None:
        entries.append(_spec_entry("FAILED", name, spec, km, "Could not add it", "", key_label(key)))
        return
    added = _Item(kmi, km.is_modal)
    users.append(added)
    entries.append(_spec_entry("ADDED", name, spec, km, "Added, from the backup", "", key_label(added.key),
                               _undo(loc, cmd, None, None, added.state())))


def _change_key(keymap_name, kind, spec):
    """What makes two recorded changes the same change (owner is only a label)."""
    return (keymap_name, kind, json.dumps(_spec_identity(spec)),
            json.dumps(spec["key"], sort_keys=True),
            json.dumps(spec.get("new_key"), sort_keys=True),
            json.dumps(spec.get("new_props"), sort_keys=True))


def _reset_changes_not_in(data, kcs, entries):
    """Undo every shortcut change on this machine that the backup does not have.

    Applying a diff only touches what the diff names, so a shortcut edited
    after the export (measured: Eyedropper Colorband moved E -> F, View2D
    Scroller Activate switched off) survived the import and the report said
    nothing about it. Restoring means the result equals the backup, so what
    is left over is compared again and put back to stock. A shortcut whose
    command is not registered belongs to an add-on that is not running here
    and is left alone.

    A deleted stock item comes back at the end of its keymap: there is no
    API to put an item back where it was.
    """
    wanted = {_change_key(e["name"], kind, spec)
              for e in data.get("keymaps", [])
              for kind in ("modified", "removed", "added")
              for spec in e.get(kind, [])}
    for km in kcs.user.keymaps:
        changes = [(kind, spec, u, b) for kind, spec, u, b in _changes(kcs, km)
                   if _change_key(km.name, kind, spec) not in wanted and _command_exists(spec)]
        loc = [km.name, km.space_type, km.region_type]
        for kind, spec, u, b in changes:
            if kind == "modified":
                before = u.state()
                _set_state(u.kmi, b.key, b.props)
                u.refresh()
                entries.append(_spec_entry(
                    "RESET", km.name, spec, km,
                    change_event(before["key"], u.key, before["props"] != u.props),
                    key_label(before["key"]), key_label(u.key),
                    _undo(loc, b.cmd, _base_ref(b), before, u.state())))
            elif kind == "added":
                before = u.state()
                km.keymap_items.remove(u.kmi)
                entries.append(_spec_entry(
                    "RESET", km.name, spec, km, "Removed (you had added it)",
                    key_label(before["key"]), "", _undo(loc, u.cmd, None, before, None)))
            else:
                kmi = _create(km, b.cmd, b.key, b.props)
                if kmi is None:
                    continue
                after = _Item(kmi, km.is_modal)
                entries.append(_spec_entry(
                    "RESET", km.name, spec, km, "Brought back (you had deleted it)",
                    "", key_label(after.key), _undo(loc, b.cmd, _base_ref(b), None, after.state())))


def apply_undo(undo):
    """Put one shortcut back as it was before the import touched it.

    Returns None on success, or a short reason it could not be done.
    """
    name, space, region = undo["loc"]
    kcs = bpy.context.window_manager.keyconfigs
    km = kcs.user.keymaps.find(name, space_type=space, region_type=region)
    if km is None:
        return "its keymap is gone"
    cmd, before, after = undo["cmd"], undo["before"], undo["after"]
    users = _user_items(km)
    user = None
    if undo["base"] is not None:
        bases = _base_items(kcs, km)
        pairs, _extra_users, _extra_bases = _pair(users, bases, km.is_modal)
        base = _take_base(bases, undo["base"], set())
        if base is None:
            return "its stock shortcut is gone"
        user = next((u for u, b in pairs if b is base), None)
    elif after is not None:
        user = next((u for u in users if u.cmd == cmd and _key_equal(u.key, after["key"])
                     and u.props == after["props"]), None)

    if after is None:
        if user is not None:
            return "it is already back"
        return None if _create(km, cmd, before["key"], before["props"]) else "could not re-create it"
    if user is None or not (_key_equal(user.key, after["key"]) and user.props == after["props"]):
        return "it was changed again since"
    if before is None:
        km.keymap_items.remove(user.kmi)
    else:
        _set_state(user.kmi, before["key"], before["props"])
    return None


# ---------------------------------------------------------------------------
# Words for the report

def change_event(before, after, settings=False):
    """`Key changed`, `Switched off`, `Key changed and settings changed`..."""
    parts = []
    if not _key_equal(_without_active(before), _without_active(after)):
        parts.append("key changed")
    on_before, on_after = before.get("active", True), after.get("active", True)
    if on_before and not on_after:
        parts.append("switched off")
    elif on_after and not on_before:
        parts.append("switched on")
    if settings:
        parts.append("settings changed")
    if not parts:
        return "Changed"
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return text[0].upper() + text[1:]


def key_label(key):
    """`Alt+F`, `Left Mouse (Double Click)`, `Esc (any modifier)`. On/off is
    told by change_event(), so it is not repeated here."""
    events = bpy.types.Event.bl_rna.properties["type"].enum_items

    def event_name(ident):
        item = events.get(ident)
        return item.name if item is not None else str(ident)

    if key.get("any"):
        text = f"{event_name(key.get('type'))} (any modifier)"
    else:
        mods = [label for label, field in (("Ctrl", "ctrl"), ("Shift", "shift"), ("Alt", "alt"),
                                           ("OS", "oskey"), ("Hyper", "hyper")) if key.get(field)]
        if key.get("key_modifier") not in (None, "NONE"):
            mods.append(event_name(key["key_modifier"]))
        text = "+".join(mods + [event_name(key.get("type"))])
    value = key.get("value")
    if value not in (None, "PRESS", "ANY"):
        detail = value.replace("_", " ").title()
        if value == "CLICK_DRAG" and key.get("direction") not in (None, "ANY"):
            detail += " " + key["direction"].replace("_", " ").title()
        text += f" ({detail})"
    return text


def describe(spec, km=None):
    """What the shortcut does, in words: `Make Edge/Face`, the menu's title for
    a call_menu item, the modal action's own name (`Cancel`), or a generic
    operator with what it acts on (`Context Toggle (space_data.show_region_ui)`)."""
    if "propvalue" in spec:
        if km is not None:
            for item in km.modal_event_values:
                if item.identifier == spec["propvalue"]:
                    return item.name
        return spec["propvalue"].replace("_", " ").title()
    idname = spec["idname"]
    props = spec.get("props", {})
    if idname in _MENU_CALLERS and props.get("name"):
        cls = getattr(bpy.types, props["name"], None)
        return f"{getattr(cls, 'bl_label', '') or props['name']} (menu)"
    try:
        mod, op = idname.split(".", 1)
        title = getattr(getattr(bpy.ops, mod), op).get_rna_type().name or idname
    except Exception:
        title = idname
    detail = props.get("data_path") or (props.get("name") if idname == "wm.tool_set_by_id" else None)
    return f"{title} ({detail})" if isinstance(detail, str) and detail else title
