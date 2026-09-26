"""Keymaps as a diff against stock Blender + add-ons, not as a preset copy.

A keymap preset is a copy of whole keymaps, add-on items included. Imported on
another machine those copies sit next to the add-on's own registration, so
every add-on shortcut you touched turns up twice. Blender itself avoids this on
the machine where the edit was made by storing the user keymap as a diff
against default+addon; that link is what an export throws away.

This module keeps it. Export compares `keyconfigs.user` (what actually fires)
with `keyconfigs.default` + `keyconfigs.addon` and records only three kinds of
change per keymap: an item modified (other key, switched off...), an item
removed, an item added. Import finds the matching item on the target machine
and edits it in place, so nothing is duplicated.

The base is the *stock* keyconfig, not `keyconfigs.active`: with a preset such
as MyPreset loaded, `is_user_modified` is relative to that preset, and its own
changes would never make it into the backup.
"""

import json

import bpy


KEY_FIELDS = (
    "type", "value", "any", "shift", "ctrl", "alt", "oskey", "hyper",
    "key_modifier", "direction", "repeat", "active",
)


def _key_fields():
    props = bpy.types.KeyMapItem.bl_rna.properties
    return tuple(f for f in KEY_FIELDS if f in props)


def _jsonable(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, set):
        return sorted(value)
    try:
        return [_jsonable(v) for v in value]
    except TypeError:
        return str(value)


def item_props(kmi):
    """Operator properties that were explicitly set, as plain JSON values."""
    props = {}
    ptr = kmi.properties
    if ptr is None:
        return props
    for prop in ptr.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type" or prop.type in {"POINTER", "COLLECTION"}:
            continue
        try:
            if not ptr.is_property_set(ident):
                continue
            props[ident] = _jsonable(getattr(ptr, ident))
        except Exception:
            continue
    return props


def item_identity(kmi, modal):
    """What the item does, independent of which key it is on."""
    if modal:
        return ("modal", kmi.propvalue)
    return (kmi.idname, json.dumps(item_props(kmi), sort_keys=True))


def item_key(kmi):
    return {f: _jsonable(getattr(kmi, f)) for f in _key_fields()}


def _key_equal(a, b):
    return all(a.get(f) == b.get(f) for f in _key_fields() if f in a and f in b)


def _without_active(key):
    return {f: v for f, v in key.items() if f != "active"}


def _item_spec(kmi, modal):
    spec = {"key": item_key(kmi)}
    if modal:
        spec["propvalue"] = kmi.propvalue
    else:
        spec["idname"] = kmi.idname
        spec["props"] = item_props(kmi)
        spec["owner"] = item_owner(spec["idname"], spec["props"])
    return spec


_MENU_CALLERS = {"wm.call_menu", "wm.call_menu_pie", "wm.call_panel"}


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
    else:
        try:
            mod, op = idname.split(".", 1)
            cls = getattr(bpy.types, f"{mod.upper()}_OT_{op}", None)
        except ValueError:
            pass
    module = getattr(cls, "__module__", "") or ""
    if not module or module.split(".")[0] in {"bl_ui", "bl_operators", "bpy", "bpy_types"}:
        return ""
    for key in bpy.context.preferences.addons.keys():
        if module == key or module.startswith(key + "."):
            return key.rsplit(".", 1)[-1]
    parts = module.split(".")
    return parts[2] if parts[0] == "bl_ext" and len(parts) > 2 else parts[0]


def spec_owner(spec):
    """Owner stored in the backup, or worked out here for older backups."""
    if "owner" in spec:
        return spec["owner"]
    if "idname" not in spec:
        return ""
    return item_owner(spec["idname"], spec.get("props", {}))


def _spec_identity(spec):
    if "propvalue" in spec:
        return ("modal", spec["propvalue"])
    return (spec["idname"], json.dumps(spec.get("props", {}), sort_keys=True))


def _find_km(kc, km):
    if kc is None:
        return None
    return kc.keymaps.find(km.name, space_type=km.space_type, region_type=km.region_type)


def _pair(user_items, base_items):
    """Match user items to base items with the same identity.

    Exact key matches first, so an unchanged item is never mistaken for a moved
    one when an operator appears several times on different keys (G, R and S all
    run transform operators; wm.call_menu sits on dozens of keys). What is left
    over pairs up in keymap order.
    """
    pairs = []
    users = list(user_items)
    bases = list(base_items)
    for u in list(users):
        for b in bases:
            if _key_equal(item_key(u), item_key(b)):
                pairs.append((u, b))
                users.remove(u)
                bases.remove(b)
                break
    while users and bases:
        pairs.append((users.pop(0), bases.pop(0)))
    return pairs, users, bases


def export_keymaps():
    """Return the diff of every keymap, plus the keyconfig preferences."""
    kcs = bpy.context.window_manager.keyconfigs
    out = {"keymaps": [], "keyconfig_prefs": {}}

    kc_prefs = getattr(kcs.default, "preferences", None)
    if kc_prefs is not None:
        for prop in kc_prefs.bl_rna.properties:
            if prop.identifier == "rna_type" or prop.is_readonly:
                continue
            out["keyconfig_prefs"][prop.identifier] = _jsonable(getattr(kc_prefs, prop.identifier))

    for km in kcs.user.keymaps:
        modal = km.is_modal
        base = []
        for kc, origin in ((kcs.default, "blender"), (kcs.addon, "addon")):
            src = _find_km(kc, km)
            if src is not None:
                base.extend((kmi, origin) for kmi in src.keymap_items)

        groups = {}
        for kmi in km.keymap_items:
            groups.setdefault(item_identity(kmi, modal), ([], []))[0].append(kmi)
        origin_of = {}
        for kmi, origin in base:
            groups.setdefault(item_identity(kmi, modal), ([], []))[1].append(kmi)
            origin_of[kmi.as_pointer()] = origin

        modified, removed, added = [], [], []
        leftover_users, leftover_bases = [], []
        for users, bases in groups.values():
            pairs, extra_users, extra_bases = _pair(users, bases)
            for u, b in pairs:
                new_key = item_key(u)
                if not _key_equal(new_key, item_key(b)):
                    spec = _item_spec(b, modal)
                    spec["origin"] = origin_of.get(b.as_pointer(), "blender")
                    spec["new_key"] = new_key
                    modified.append(spec)
            leftover_bases.extend(extra_bases)
            leftover_users.extend(extra_users)

        # Second chance for what the identity pass could not pair: same
        # operator on the same key. The user's copy of an add-on item can carry
        # slightly different properties (measured: Zen UV's Sticky UV Editor on
        # Shift+T), and exporting that as "remove + add" would, on import,
        # remove the add-on's merged item -- the permanent "user deleted this"
        # entry. Pairing it turns it back into the edit it really is.
        for u in list(leftover_users):
            for b in leftover_bases:
                if (not modal and u.idname == b.idname
                        and _key_equal(_without_active(item_key(u)), _without_active(item_key(b)))):
                    if item_key(u)["active"] != item_key(b)["active"]:
                        spec = _item_spec(b, modal)
                        spec["origin"] = origin_of.get(b.as_pointer(), "blender")
                        spec["new_key"] = item_key(u)
                        modified.append(spec)
                    leftover_users.remove(u)
                    leftover_bases.remove(b)
                    break

        for b in leftover_bases:
            spec = _item_spec(b, modal)
            spec["origin"] = origin_of.get(b.as_pointer(), "blender")
            removed.append(spec)
        for u in leftover_users:
            # An added item that is switched off does nothing. These are almost
            # always switched-off add-on copies a keymap preset baked in, which
            # never disabled anything in the first place.
            if u.active:
                added.append(_item_spec(u, modal))

        if modified or removed or added:
            out["keymaps"].append({
                "name": km.name,
                "space_type": km.space_type,
                "region_type": km.region_type,
                "modal": modal,
                "modified": modified,
                "removed": removed,
                "added": added,
            })
    return out


_MAP_TYPES = ('KEYBOARD', 'MOUSE', 'NDOF', 'TEXTINPUT', 'TIMER')


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
    for f in _key_fields():
        if f not in key:
            continue
        if f == "type":
            _set_type(kmi, key["type"])
            continue
        try:
            setattr(kmi, f, key[f])
        except Exception:
            pass


def _set_props(kmi, props):
    ptr = kmi.properties
    if ptr is None:
        return
    for name, value in props.items():
        try:
            rna = ptr.bl_rna.properties.get(name)
            if rna is not None and rna.type == "ENUM" and rna.is_enum_flag:
                value = set(value)
            setattr(ptr, name, value)
        except Exception:
            pass


def _find_item(km, spec, key):
    """The item in `km` doing what `spec` does, preferring the one on `key`."""
    ident = _spec_identity(spec)
    candidates = [k for k in km.keymap_items if item_identity(k, km.is_modal) == ident]
    for kmi in candidates:
        if _key_equal(item_key(kmi), key):
            return kmi
    return None


def _find_item_loose(km, spec, key):
    """Same operator on the same key, ignoring properties -- only if unique.

    For a backup made on another Blender version: the operator can keep its
    key while its properties change (measured: every paint mode's brush-size
    wm.radial_control on F, 5.2 -> 4.5). One candidate is unambiguous; two or
    more and guessing could edit the wrong shortcut, so it gives up.
    """
    if "propvalue" in spec:
        return None
    candidates = [k for k in km.keymap_items
                  if k.idname == spec["idname"] and _key_equal(item_key(k), key)]
    return candidates[0] if len(candidates) == 1 else None


def import_keymaps(data, reset_extra=True):
    """Apply a diff from export_keymaps() to this machine's user keyconfig.

    Safe to run twice: every step first checks whether it is already done.
    Returns counts plus "entries": one dict per shortcut touched (or found
    already in place, or skipped), with what happened in words, the key before
    and after, the add-on it belongs to, and an `undo` recipe that
    apply_undo() can replay to revert just that shortcut.
    """
    kcs = bpy.context.window_manager.keyconfigs
    report = {"modified": 0, "removed": 0, "added": 0, "already": 0, "reset": 0,
              "skipped": [], "entries": []}

    def log(word, entry, spec, event, before="", after="", undo=None, km=None):
        report["entries"].append({
            "word": word,
            "owner": spec_owner(spec) if spec else "",
            "keymap": entry["name"] if entry else "Keymap settings",
            "what": describe(spec, km) if spec else "",
            "event": event,
            "before": before,
            "after": after,
            "undo": undo,
        })

    kc_prefs = getattr(kcs.default, "preferences", None)
    if kc_prefs is not None:
        for name, value in data.get("keyconfig_prefs", {}).items():
            try:
                old = getattr(kc_prefs, name)
                if old != value:
                    setattr(kc_prefs, name, value)
                    report["entries"].append({
                        "word": "CHANGED", "owner": "", "keymap": "Keymap settings",
                        "what": kc_prefs.bl_rna.properties[name].name, "event": "Setting changed",
                        "before": str(old), "after": str(value), "undo": None})
            except Exception:
                pass
        # Keyconfig preferences rebuild the default keymap; the user
        # keyconfig has to be re-merged before items are looked up in it.
        kcs.update()

    for entry in data.get("keymaps", []):
        name = entry["name"]
        km = kcs.user.keymaps.find(
            name, space_type=entry["space_type"], region_type=entry["region_type"])
        loc = [name, entry["space_type"], entry["region_type"]]
        if km is None:
            report["skipped"].append(f"{name}: keymap not found")
            continue

        for spec in entry.get("modified", []):
            before, after = spec["key"], spec["new_key"]
            kmi = _find_item(km, spec, before) or _find_item_loose(km, spec, before)
            if kmi is None:
                if (_find_item(km, spec, after) or _find_item_loose(km, spec, after)) is not None:
                    report["already"] += 1
                    log("ALREADY", entry, spec, "Already as in the backup", km=km)
                else:
                    report["skipped"].append(f"{name}: {describe(spec, km)}")
                    why = ("Skipped: its add-on is not enabled here" if spec.get("origin") == "addon"
                           else "Skipped: not found on its original key")
                    log("SKIPPED", entry, spec, why, key_label(before), key_label(after), km=km)
                continue
            _set_key(kmi, after)
            report["modified"] += 1
            log("CHANGED", entry, spec, change_event(before, after),
                key_label(before), key_label(after),
                {"loc": loc, "spec": _undo_spec(spec), "op": "set_key", "find": after, "to": before},
                km=km)

        for spec in entry.get("removed", []):
            key = spec["key"]
            kmi = _find_item(km, spec, key) or _find_item_loose(km, spec, key)
            if kmi is None:
                report["already"] += 1
                log("ALREADY", entry, spec, "Already removed", km=km)
                continue
            km.keymap_items.remove(kmi)
            report["removed"] += 1
            log("REMOVED", entry, spec, "Removed, as in the backup", key_label(key), "",
                {"loc": loc, "spec": _undo_spec(spec), "op": "create", "find": key, "to": key},
                km=km)

        for spec in entry.get("added", []):
            key = spec["key"]
            if _find_item(km, spec, key) is not None:
                report["already"] += 1
                log("ALREADY", entry, spec, "Already added", km=km)
                continue
            if _create(km, spec, key) is None:
                report["skipped"].append(f"{name}: {describe(spec, km)}")
                log("SKIPPED", entry, spec, "Skipped: its command does not exist here",
                    "", key_label(key), km=km)
                continue
            report["added"] += 1
            log("ADDED", entry, spec, "Added, from the backup", "", key_label(key),
                {"loc": loc, "spec": _undo_spec(spec), "op": "remove", "find": key, "to": key},
                km=km)

    if reset_extra:
        _reset_changes_not_in(data, kcs, report, log)
    return report


def _undo_spec(spec):
    return {k: spec[k] for k in ("idname", "props", "propvalue") if k in spec}


def _create(km, spec, key):
    try:
        if "propvalue" in spec:
            kmi = km.keymap_items.new_modal(spec["propvalue"], key["type"], key["value"])
        else:
            kmi = km.keymap_items.new(spec["idname"], key["type"], key["value"])
    except Exception:
        return None
    _set_key(kmi, key)
    _set_props(kmi, spec.get("props", {}))
    return kmi


def apply_undo(undo):
    """Revert one shortcut to how it was before the import touched it.

    Returns None on success, or a short reason it could not be done.
    """
    name, space, region = undo["loc"]
    km = bpy.context.window_manager.keyconfigs.user.keymaps.find(
        name, space_type=space, region_type=region)
    if km is None:
        return "its keymap is gone"
    spec = undo["spec"]
    if undo["op"] == "set_key":
        kmi = _find_item(km, spec, undo["find"]) or _find_item_loose(km, spec, undo["find"])
        if kmi is None:
            return "the shortcut was changed again since"
        _set_key(kmi, undo["to"])
    elif undo["op"] == "remove":
        kmi = _find_item(km, spec, undo["find"])
        if kmi is None:
            return "the shortcut is already gone"
        km.keymap_items.remove(kmi)
    elif undo["op"] == "create":
        if _find_item(km, spec, undo["to"]) is not None:
            return "the shortcut is already there"
        if _create(km, spec, undo["to"]) is None:
            return "could not re-create it"
    return None


def _change_key(entry_name, kind, spec):
    """What makes two recorded changes the same change (owner is only a label)."""
    return (entry_name, kind, json.dumps(_spec_identity(spec)),
            json.dumps(spec["key"], sort_keys=True),
            json.dumps(spec.get("new_key"), sort_keys=True))


def _command_exists(spec):
    """False for a shortcut whose operator is not registered: it belongs to an
    add-on that is not running here, and is not Blender's to reset."""
    if "propvalue" in spec:
        return True
    try:
        mod, op = spec["idname"].split(".", 1)
        getattr(getattr(bpy.ops, mod), op).get_rna_type()
        return True
    except Exception:
        return False


def _reset_changes_not_in(data, kcs, report, log):
    """Undo every shortcut change on this machine that the backup does not have.

    Applying a diff only touches what the diff names, so a shortcut edited
    after the export (measured: Eyedropper Colorband moved E -> F, View2D
    Scroller Activate switched off) survived the import and the report said
    nothing about it. Restoring means the result equals the backup, so what
    is left over is compared again and put back to stock.
    """
    wanted = {_change_key(e["name"], kind, spec)
              for e in data.get("keymaps", [])
              for kind in ("modified", "removed", "added")
              for spec in e.get(kind, [])}
    for entry in export_keymaps()["keymaps"]:
        name = entry["name"]
        entry = {**entry, **{kind: [s for s in entry[kind] if _command_exists(s)]
                             for kind in ("modified", "removed", "added")}}
        km = kcs.user.keymaps.find(
            name, space_type=entry["space_type"], region_type=entry["region_type"])
        if km is None:
            continue
        loc = [name, entry["space_type"], entry["region_type"]]
        for spec in entry["modified"]:
            if _change_key(name, "modified", spec) in wanted:
                continue
            kmi = _find_item(km, spec, spec["new_key"])
            if kmi is None:
                continue
            _set_key(kmi, spec["key"])
            report["reset"] += 1
            log("RESET", entry, spec,
                change_event(spec["new_key"], spec["key"]),
                key_label(spec["new_key"]), key_label(spec["key"]),
                {"loc": loc, "spec": _undo_spec(spec), "op": "set_key",
                 "find": spec["key"], "to": spec["new_key"]}, km=km)
        for spec in entry["added"]:
            if _change_key(name, "added", spec) in wanted:
                continue
            kmi = _find_item(km, spec, spec["key"])
            if kmi is None:
                continue
            km.keymap_items.remove(kmi)
            report["reset"] += 1
            log("RESET", entry, spec, "Removed (you had added it)",
                key_label(spec["key"]), "",
                {"loc": loc, "spec": _undo_spec(spec), "op": "create",
                 "find": spec["key"], "to": spec["key"]}, km=km)
        for spec in entry["removed"]:
            if _change_key(name, "removed", spec) in wanted:
                continue
            if _create(km, spec, spec["key"]) is None:
                continue
            report["reset"] += 1
            log("RESET", entry, spec, "Brought back (you had deleted it)",
                "", key_label(spec["key"]),
                {"loc": loc, "spec": _undo_spec(spec), "op": "remove",
                 "find": spec["key"], "to": spec["key"]}, km=km)


def change_event(before, after):
    """`Key changed`, `Switched off`, `Key changed and switched on`..."""
    moved = not _key_equal(_without_active(before), _without_active(after))
    on_before, on_after = before.get("active", True), after.get("active", True)
    parts = []
    if moved:
        parts.append("Key changed")
    if on_before and not on_after:
        parts.append("switched off" if parts else "Switched off")
    elif on_after and not on_before:
        parts.append("switched on" if parts else "Switched on")
    return " and ".join(parts) or "Changed"


def key_label(key):
    """`Alt+F`, `Left Mouse (Double Click)`, `Esc (any modifier)`. On/off is
    told by change_event(), so it is not repeated here."""
    try:
        name = bpy.types.Event.bl_rna.properties["type"].enum_items[key["type"]].name
    except Exception:
        name = str(key.get("type"))
    if key.get("any"):
        text = f"{name} (any modifier)"
    else:
        mods = [label for label, field in (("Ctrl", "ctrl"), ("Shift", "shift"),
                                           ("Alt", "alt"), ("OS", "oskey")) if key.get(field)]
        text = "+".join(mods + [name])
    if key.get("value") not in (None, "PRESS", "ANY"):
        text += f" ({key['value'].replace('_', ' ').title()})"
    return text


def describe(spec, km=None):
    """What the shortcut does, in words: `Make Edge/Face`, the menu's title for
    a call_menu item, or the modal action's own name (`Cancel`)."""
    if "propvalue" in spec:
        if km is not None:
            for item in getattr(km, "modal_event_values", ()):
                if item.identifier == spec["propvalue"]:
                    return item.name
        return spec["propvalue"].replace("_", " ").title()
    idname = spec["idname"]
    menu = spec.get("props", {}).get("name")
    if menu:
        cls = getattr(bpy.types, menu, None)
        title = getattr(cls, "bl_label", "") if cls else ""
        return f"{title or menu} (menu)"
    try:
        mod, op = idname.split(".", 1)
        return getattr(getattr(bpy.ops, mod), op).get_rna_type().name or idname
    except Exception:
        return idname
