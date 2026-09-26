"""Themes, handled as whole things rather than hundreds of colour values.

Two kinds travel in a backup:

- theme presets: the .xml files in the user's scripts/presets/interface_theme
  (what Preferences > Themes > Presets lists). Missing ones are installed,
  identical ones skipped, different ones only overwritten if the user says so.
- the active theme: every colour currently in use, which can differ from any
  preset once it has been edited by hand. Applied only if the user says so
  when it differs.

Listing every colour as a changed preference told the user nothing: one theme
edit read as "639 values changed".
"""

import os

import bpy

from . import prefs_io


# Key for "the active theme" in apply()'s overwrite set; presets use their
# file name, and "<" ">" cannot appear in one on Windows. Not a NUL: the key
# travels through a StringProperty, which truncates at NUL, and "\0active"
# arrived as "" -- a ticked "replace the theme in use" was silently kept.
ACTIVE = "<active theme>"


def _preset_dir(create=False):
    return bpy.utils.user_resource('SCRIPTS', path=os.path.join("presets", "interface_theme"),
                                   create=create)


def _theme_label(theme):
    path = getattr(theme, "filepath", "") or ""
    if path:
        return os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    return theme.name


def export_themes():
    presets = {}
    folder = _preset_dir()
    if folder and os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".xml"):
                try:
                    with open(os.path.join(folder, name), encoding="utf-8") as f:
                        presets[name] = f.read()
                except Exception:
                    continue
    theme = bpy.context.preferences.themes[0]
    return {
        "presets": presets,
        "active": {"label": _theme_label(theme), "values": prefs_io.dump(theme, skip_paths=True)},
    }


def classify(data):
    """What importing `data` would do to themes here, before doing anything.

    Returns a list of dicts: kind "preset" or "active", state "missing",
    "same" or "different". Only "different" needs the user's decision.
    """
    out = []
    folder = _preset_dir()
    for name, text in data.get("presets", {}).items():
        path = os.path.join(folder, name) if folder else ""
        if not path or not os.path.exists(path):
            state = "missing"
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    state = "same" if f.read() == text else "different"
            except Exception:
                state = "different"
        out.append({"kind": "preset", "name": name, "state": state})

    active = data.get("active")
    if active:
        current = prefs_io.dump(bpy.context.preferences.themes[0], skip_paths=True)
        out.append({"kind": "active", "name": active.get("label", "theme"),
                    "state": "same" if current == active["values"] else "different"})
    return out


def apply(data, overwrite):
    """Apply themes. `overwrite` is the set of names the user agreed to replace.

    Returns report lines ("INSTALLED", "OVERWRITTEN", "KEPT", "APPLIED"...).
    Unchanged ones produce no line: nothing happened to them.
    """
    lines = []
    folder = _preset_dir(create=True)
    for item in classify(data):
        name = item["name"]
        if item["kind"] == "preset":
            if item["state"] == "same":
                continue
            if item["state"] == "different" and name not in overwrite:
                lines.append(f"KEPT      preset {name}: this machine's version stays")
                continue
            try:
                with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                    f.write(data["presets"][name])
                verb = "INSTALLED" if item["state"] == "missing" else "OVERWROTE"
                lines.append(f"{verb:<9} preset {name}")
            except Exception as e:
                lines.append(f"FAILED    preset {name}: {e}")
        else:
            if item["state"] == "same":
                continue
            if ACTIVE not in overwrite:
                lines.append(f"KEPT      active theme: this machine's colours stay")
                continue
            report = {"set": 0, "failed": [], "log": []}
            prefs_io.load(bpy.context.preferences.themes[0], data["active"]["values"], report, "theme")
            lines.append(f"APPLIED   active theme \"{name}\" ({report['set']} colours)")
    return lines
