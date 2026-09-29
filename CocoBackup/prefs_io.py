"""Preferences and add-on settings as plain JSON, walked through RNA.

Nothing here knows any particular setting: it reads every property RNA
exposes and writes the same ones back, so a Blender release that adds a
preference is covered without a code change. What it leaves out is on
purpose:

- `system`, `apps`, `experimental`, `extensions`: GPU, memory and
  repositories belong to the machine, not the person.
- any file or directory path, anywhere in core preferences, for the same
  reason, plus the few settings in MACHINE.
- pointers to datablocks (objects, images...), which cannot travel in a
  preferences file at all.
- `bl_*` registration properties: they are not settings, and reading
  `bl_idname` back gives garbage ("\x06" on 5.2).
- add-on settings that describe the machine (MACHINE_ADDON).

Add-on settings do keep their paths, rewritten on import for where things
are on this machine (see `import_addons`).
"""

import fnmatch
import os
import re
import sys

import bpy


CORE_SECTIONS = ("view", "edit", "inputs", "keymap", "filepaths")
PATH_SUBTYPES = {"FILE_PATH", "DIR_PATH", "FILE_NAME"}

# Add-on settings about the machine an add-on runs on, not the person: never
# exported, and dropped from older backups on import. "*" is all of them.
# Cycles holds the render devices (shown under Preferences > System): the
# user's two GPUs arrived on another machine as its device list. UV
# Packmaster holds where it found its engine, what that engine can do and
# the CPU's thread count: imported, they told it the engine was "not
# detected" and switched its operators off until a restart.
MACHINE_ADDON = {
    "cycles": ("*",),
    "uvpackmaster3": ("engine_*", "FEATURE_*", "thread_count", "saved_dev_settings",
                      "enable_vulkan*", "operation_counter", "box_rendering", "boxes_dirty",
                      "*_editing"),
}

# The start of an absolute path: C:\ or C:/, \\server, or /folder (not
# Blender's "//", which is relative to the .blend).
_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]|/[^/\s])")
# An absolute path inside a longer string, between quotes: a CocoPies command
# says execute_script("C:/.../CocoPies/scripts/delete/MeshDeleteNoMenu.py").
_QUOTED_PATH = re.compile(r"""(["'])((?:[A-Za-z]:[\\/]|\\\\[^\\/\s]|/[^/\s])[^"'\n]*)\1""")

# Settings in the core sections that belong to the machine. The asset
# libraries and script folders are collections of paths: written by position
# onto another machine's list they renamed its libraries. The player preset
# and editor arguments go with their (skipped) paths, the online-access flag
# records a question this machine answered, and the keymap preset in use
# travels with the shortcuts instead (keymap_diff.export_preset), file and
# all: switched here by name alone, it would load a different file.
MACHINE = {
    "filepaths": {"asset_libraries", "active_asset_library", "script_directories",
                  "animation_player_preset", "text_editor_args",
                  "use_extension_online_access_handled"},
    "keymap": {"active_keyconfig"},
}


def _is_id_pointer(prop):
    fixed = prop.fixed_type
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
        if ident == "rna_type" or ident.startswith("bl_"):
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


def load(struct, data, report, path="", quiet=False, keep_missing=False):
    """Write a dict from dump() back onto an RNA struct.

    Every value that actually changes is logged as `path: old -> new` in
    report["log"], which is what the import report shows. `quiet` is for
    the items of a rebuilt collection, logged once as a whole instead.

    With `keep_missing`, a setting that is a whole absolute path which does
    not exist on this machine keeps this machine's value: MESHmachine given
    the other machine's plug folder failed to register at the next start,
    and its menu came up full of unknown operators.
    """
    props = struct.bl_rna.properties
    for ident, value in data.items():
        prop = props.get(ident)
        # 1.0 backups carry bl_idname (garbage): never write it back.
        if prop is None or ident.startswith("bl_"):
            continue
        try:
            if prop.type == "POINTER":
                target = getattr(struct, ident)
                if target is not None and isinstance(value, dict):
                    load(target, value, report, f"{path}.{ident}", quiet, keep_missing)
            elif prop.type == "COLLECTION":
                _load_collection(getattr(struct, ident), value, report, f"{path}.{ident}", quiet,
                                 keep_missing)
            else:
                if prop.is_readonly:
                    continue
                current = _plain(getattr(struct, ident))
                if current == value:
                    continue
                if keep_missing and prop.type == "STRING" and is_missing_path(value):
                    report["log"].append(f"KEPT      {path}.{ident}: {value} is not on this machine")
                    continue
                if prop.type == "ENUM" and prop.is_enum_flag:
                    value = set(value)
                setattr(struct, ident, value)
                report["set"] += 1
                if not quiet:
                    report["log"].append(f"CHANGED   {path}.{ident}: {_short(current)} -> {_short(value)}")
        except Exception as e:
            report["failed"].append(f"{path}.{ident}: {e}")
            report["log"].append(f"FAILED    {path}.{ident}: {e}")


def _load_collection(coll, items, report, path, quiet, keep_missing=False):
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
            load(item, item_data, report, f"{path}[{i}]", quiet, keep_missing)


def _short(value):
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(_short(v) for v in value) + ")"
    return repr(value)


def _addon_id(module):
    """`bl_ext.<repo>.CocoPies` and a legacy `CocoPies` are the same add-on."""
    return module.rsplit(".", 1)[-1]


def addon_dir(module):
    """The folder an enabled add-on runs from, or ""."""
    path = getattr(sys.modules.get(module), "__file__", None)
    return os.path.dirname(os.path.abspath(path)) if path else ""


def _machine_only(addon_id, ident):
    return any(fnmatch.fnmatchcase(ident, pattern) for pattern in MACHINE_ADDON.get(addon_id, ()))


def is_missing_path(value):
    """True for a string that is a whole absolute path to nothing here."""
    return (isinstance(value, str) and "\n" not in value and bool(_ABSOLUTE.match(value))
            and not os.path.exists(value))


# ---------------------------------------------------------------------------
# Moving paths from the machine a backup was made on to this one

def _strings(value, where=""):
    """(where, text) for every string inside a dump()."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{where}.{key}" if where else key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _strings(item, f"{where}[{i}]")
    elif isinstance(value, str):
        yield where, value


def _guess_addon_dir(addon_id, values):
    """Where an add-on lived on the backup's machine, for backups that do not
    say: a path in its own settings, up to a folder named after it (CocoPies'
    commands name .../CocoPies/scripts/..., MESHmachine its assets folder)."""
    folder = re.compile(r"[\\/]" + re.escape(addon_id) + r"(?=[\\/])", re.IGNORECASE)
    for _where, text in _strings(values):
        for match in folder.finditer(text):
            head = text[:match.end()]
            head = head[max(head.rfind('"'), head.rfind("'")) + 1:]
            if _ABSOLUTE.match(head):
                return head
    return ""


# For backups that do not say where the machine keeps things: Blender's user
# folder and the home folder, as they appear on Windows, macOS and Linux.
_MACHINE_GUESSES = (
    ("blender_user", r"[A-Za-z]:[\\/]Users[\\/][^\\/\"']+[\\/]AppData[\\/]Roaming[\\/]"
                     r"Blender Foundation[\\/]Blender[\\/]\d+\.\d+"),
    ("blender_user", r"/Users/[^/\"']+/Library/Application Support/Blender/\d+\.\d+"),
    ("blender_user", r"/home/[^/\"']+/\.config/blender/\d+\.\d+"),
    ("home", r"[A-Za-z]:[\\/]Users[\\/][^\\/\"']+"),
    ("home", r"/(?:Users|home)/[^/\"']+"),
)


def _guess_machine(data):
    found = {}
    for key, pattern in _MACHINE_GUESSES:
        if key in found:
            continue
        rx = re.compile(pattern, re.IGNORECASE)
        for _where, text in _strings(data):
            match = rx.search(text)
            if match:
                found[key] = match.group(0)
                break
    return found


def _same_folder(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def path_moves(data, machine=None):
    """How to move a path from the backup's machine to this one: a pattern
    matching any of that machine's folders (each add-on's own, Blender's user
    and install folders, the home folder), most specific first, and what each
    becomes here. None when nothing moves (a backup of this same machine)."""
    here = {_addon_id(a.module): a for a in bpy.context.preferences.addons}
    pairs = []
    for addon_id, entry in data.items():
        addon = here.get(addon_id)
        if addon is not None:
            source = entry.get("dir") or _guess_addon_dir(addon_id, entry.get("preferences"))
            pairs.append((source, addon_dir(addon.module)))
    machine = machine or _guess_machine(data)
    for key, target in (("blender_user", bpy.utils.resource_path('USER')),
                        ("blender_install", bpy.utils.resource_path('LOCAL')),
                        ("home", os.path.expanduser("~"))):
        pairs.append((machine.get(key, ""), target))
    moves = {}
    for source, target in pairs:
        if source and target and not _same_folder(source, target):
            moves.setdefault(source.rstrip("\\/"), target.rstrip("\\/"))
    if not moves:
        return None
    sources = sorted(moves, key=len, reverse=True)
    alternatives = "|".join(
        "(" + r"[\\/]".join(re.escape(part) for part in re.split(r"[\\/]", s)) + ")" for s in sources)
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.compile(f"(?:{alternatives})(?=[\\\\/\"']|$)", flags), [moves[s] for s in sources]


def relocate(value, moves):
    """`value` with every path under one of the backup machine's folders moved
    under the same folder here, keeping the path's own slash style."""
    if moves is None:
        return value
    if isinstance(value, dict):
        return {k: relocate(v, moves) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate(v, moves) for v in value]
    if not isinstance(value, str):
        return value
    pattern, targets = moves

    def moved(match):
        target = targets[match.lastindex - 1]
        return target.replace("/", "\\") if "\\" in match.group(0) else target.replace("\\", "/")
    return pattern.sub(moved, value)


def missing_quoted_paths(values):
    """(where, path) for each quoted absolute path inside a longer string
    (a CocoPies command) that is not on this machine even after moving."""
    for where, text in _strings(values):
        for match in _QUOTED_PATH.finditer(text):
            if not os.path.exists(match.group(2)):
                yield where, match.group(2)


def export_preferences():
    prefs = bpy.context.preferences
    core = {}
    for section in CORE_SECTIONS:
        values = dump(getattr(prefs, section), skip_paths=True)
        for name in MACHINE.get(section, ()):
            values.pop(name, None)
        core[section] = values
    # Themes are exported by themes_io as whole themes, not as values here.
    return {"core": core}


def export_addons():
    """Every enabled add-on: its module, the folder it runs from (so its paths
    can be moved on import) and its settings, less the machine's."""
    out = {}
    for addon in bpy.context.preferences.addons:
        addon_id = _addon_id(addon.module)
        entry = {"module": addon.module}
        folder = addon_dir(addon.module)
        if folder:
            entry["dir"] = folder
        if addon.preferences is not None:
            values = {k: v for k, v in dump(addon.preferences, skip_paths=False).items()
                      if not _machine_only(addon_id, k)}
            if values:
                entry["preferences"] = values
        out[addon_id] = entry
    return out


def export_machine():
    """Where this machine keeps things, which import_addons moves paths from."""
    return {"home": os.path.expanduser("~"),
            "blender_user": bpy.utils.resource_path('USER'),
            "blender_install": bpy.utils.resource_path('LOCAL')}


def import_preferences(data):
    prefs = bpy.context.preferences
    report = {"set": 0, "failed": [], "log": []}
    for section, values in data.get("core", {}).items():
        if section not in CORE_SECTIONS:
            continue
        skip = MACHINE.get(section, set())
        load(getattr(prefs, section), {k: v for k, v in values.items() if k not in skip},
             report, f"Preferences.{section}")
    return report


def import_addons(data, machine=None):
    """Apply stored add-on settings to the add-ons enabled here.

    Add-ons that are not enabled are only reported. Switching one on or
    installing it happens before this runs (addons_resolve), never from here.

    Paths are moved first: one under an add-on's own folder, Blender's user
    folder or the home folder on the backup's machine points at the same place
    here (`machine` says where those were; older backups are read for them).
    A setting that is a path still missing here keeps this machine's value,
    and a missing path inside a command is listed.
    """
    report = {"set": 0, "failed": [], "applied": [], "missing": [], "log": []}
    here = {_addon_id(a.module): a for a in bpy.context.preferences.addons}
    moves = path_moves(data, machine)
    for addon_id, entry in data.items():
        addon = here.get(addon_id)
        if addon is None:
            report["missing"].append(addon_id)
            continue
        values = entry.get("preferences")
        if addon.preferences is None or not values:
            continue
        values = relocate({k: v for k, v in values.items() if not _machine_only(addon_id, k)}, moves)
        load(addon.preferences, values, report, f"{addon_id}", keep_missing=True)
        for where, path in missing_quoted_paths(values):
            report["log"].append(f"MISSING   {addon_id}.{where}: {path} is not on this machine")
        report["applied"].append(addon_id)
    return report
