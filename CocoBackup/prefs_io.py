"""Preferences and add-on settings as plain JSON, walked through RNA.

Nothing here knows any particular setting: it reads every property RNA
exposes and writes the same ones back, so a Blender release that adds a
preference is covered without a code change. What it leaves out is on
purpose:

- `system`, `apps`, `experimental`, `extensions`, `asset_libraries`: GPU,
  memory, repositories and library locations belong to the machine, not the
  person.
- any file or directory path, anywhere in core preferences, for the same
  reason.
- pointers to datablocks (objects, images...), which cannot travel in a
  preferences file at all.
"""

import bpy


CORE_SECTIONS = ("view", "edit", "inputs", "keymap", "filepaths")
PATH_SUBTYPES = {"FILE_PATH", "DIR_PATH", "FILE_NAME"}


def _is_id_pointer(prop):
    fixed = getattr(prop, "fixed_type", None)
    cls = getattr(bpy.types, fixed.identifier, None) if fixed is not None else None
    return isinstance(cls, type) and issubclass(cls, bpy.types.ID)


def _plain(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, set):
        return sorted(value)
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return None


def dump(struct, skip_paths, _depth=0):
    """Serialize an RNA struct to a dict.

    Bounded by depth, not by a seen-set of as_pointer(): a nested struct at
    offset 0 shares its parent's address, and a seen-set silently dropped
    whole theme sections that way.
    """
    if _depth > 16:
        return {}

    out = {}
    for prop in struct.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type":
            continue
        try:
            if prop.type == "POINTER":
                if _is_id_pointer(prop):
                    continue
                value = getattr(struct, ident)
                if value is not None:
                    out[ident] = dump(value, skip_paths, _depth + 1)
            elif prop.type == "COLLECTION":
                out[ident] = [dump(item, skip_paths, _depth + 1) for item in getattr(struct, ident)]
            else:
                if prop.is_readonly:
                    continue
                if skip_paths and prop.subtype in PATH_SUBTYPES:
                    continue
                out[ident] = _plain(getattr(struct, ident))
        except Exception:
            continue
    return out


def load(struct, data, report, path="", quiet=False):
    """Write a dict from dump() back onto an RNA struct.

    Every value that actually changes is logged as `path: old -> new` in
    report["log"], which is what the import report file shows. `quiet` is for
    the items of a rebuilt collection, logged once as a whole instead.
    """
    props = struct.bl_rna.properties
    for ident, value in data.items():
        prop = props.get(ident)
        if prop is None:
            continue
        try:
            if prop.type == "POINTER":
                target = getattr(struct, ident)
                if target is not None and isinstance(value, dict):
                    load(target, value, report, f"{path}.{ident}", quiet)
            elif prop.type == "COLLECTION":
                _load_collection(getattr(struct, ident), value, report, f"{path}.{ident}", quiet)
            else:
                if prop.is_readonly:
                    continue
                current = _plain(getattr(struct, ident))
                if current == value:
                    continue
                if prop.type == "ENUM" and getattr(prop, "is_enum_flag", False):
                    value = set(value)
                setattr(struct, ident, value)
                report["set"] += 1
                if not quiet:
                    report["log"].append(f"CHANGED   {path}.{ident}: {_short(current)} -> {_short(value)}")
        except Exception as e:
            report["failed"].append(f"{path}.{ident}: {e}")
            report["log"].append(f"FAILED    {path}.{ident}: {e}")


def _load_collection(coll, items, report, path, quiet):
    # A CollectionProperty an add-on defined can be rebuilt; one Blender owns
    # (themes, ui_styles) has fixed members, which are updated in place.
    if hasattr(coll, "add") and hasattr(coll, "clear"):
        # Rebuilding fires every update callback on the way (CocoPies
        # re-registers its pies), so an unchanged list is left alone.
        if [dump(item, skip_paths=False) for item in coll] == items:
            return
        before = len(coll)
        coll.clear()
        for i, item_data in enumerate(items):
            load(coll.add(), item_data, report, f"{path}[{i}]", quiet=True)
        if not quiet:
            report["log"].append(f"REBUILT   {path}: {before} -> {len(items)} entries")
    else:
        for i, (item, item_data) in enumerate(zip(coll, items)):
            load(item, item_data, report, f"{path}[{i}]", quiet)


def _short(value):
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(_short(v) for v in value) + ")"
    return repr(value)


def _addon_id(module):
    """`bl_ext.<repo>.CocoPies` and a legacy `CocoPies` are the same add-on."""
    return module.rsplit(".", 1)[-1]


def export_preferences():
    prefs = bpy.context.preferences
    core = {}
    for section in CORE_SECTIONS:
        struct = getattr(prefs, section, None)
        if struct is not None:
            core[section] = dump(struct, skip_paths=True)
    # Themes are exported by themes_io as whole themes, not as values here.
    return {"core": core}


def export_addons():
    out = {}
    for addon in bpy.context.preferences.addons:
        entry = {"module": addon.module}
        ap = getattr(addon, "preferences", None)
        if ap is not None:
            entry["preferences"] = dump(ap, skip_paths=False)
        out[_addon_id(addon.module)] = entry
    return out


def import_preferences(data):
    prefs = bpy.context.preferences
    report = {"set": 0, "failed": [], "log": []}
    for section, values in data.get("core", {}).items():
        if section not in CORE_SECTIONS:
            continue
        struct = getattr(prefs, section, None)
        if struct is not None:
            load(struct, values, report, f"Preferences.{section}")
    return report


def import_addons(data):
    """Apply stored add-on settings to the add-ons enabled here.

    Add-ons that are not enabled are only reported. Enabling or installing one
    is decided by the user in the import dialog (addons_resolve), before this
    runs; it is never done from here.
    """
    report = {"set": 0, "failed": [], "applied": [], "missing": [], "log": []}
    here = {_addon_id(a.module): a for a in bpy.context.preferences.addons}
    for addon_id, entry in data.items():
        addon = here.get(addon_id)
        if addon is None:
            report["missing"].append(addon_id)
            continue
        ap = getattr(addon, "preferences", None)
        values = entry.get("preferences")
        if ap is None or not values:
            continue
        load(ap, values, report, f"{addon_id}")
        report["applied"].append(addon_id)
    return report
