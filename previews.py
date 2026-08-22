"""Icons CocoPie loads itself, rather than taking from Blender.

Two kinds live here:

* the eight slot arrows, because Blender ships no diagonal arrow -- its whole
  arrow set is cardinal only, so half a pie's directions have nothing to point
  at;
* whatever the user drops into a custom icons folder, so a pie slot can carry
  artwork Blender does not have at all.

Both go through one preview collection, which is the same route MACHIN3tools
and MESHmachine take for their custom icons.
"""

import os

import bpy
import bpy.utils.previews

from .items import POSITION_ARROWS
from .icons import safe_icon

# How a custom icon is written into an item's `icon` field, to tell it apart
# from one of Blender's own identifiers
CUSTOM_PREFIX = "custom:"

_LOADABLE = (".png", ".jpg", ".jpeg")

# Filled on register; None while the addon is not registered
_previews = None
_custom_names = []


def icons_dir():
    """Folder the slot arrow PNGs ship in, inside this package"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def custom_icon_dirs():
    """Folders scanned for custom icons.

    Only one, inside the addon, so everything CocoPie owns stays within its own
    folder rather than scattering directories through Blender's scripts
    directory. The trade-off is that reinstalling the addon replaces the folder
    along with the rest of the package.
    """
    return [os.path.join(icons_dir(), "custom")]


def _load_slot_arrows(collection):
    loaded = 0
    folder = icons_dir()
    for position in range(8):
        path = os.path.join(folder, f"slot_{position}.png")
        if not os.path.exists(path):
            print(f"CocoPie: slot icon missing: {path}")
            continue
        try:
            collection.load(f"slot_{position}", path, 'IMAGE')
            loaded += 1
        except Exception as e:
            print(f"CocoPie: could not load slot icon {position}: {e}")
    return loaded


def _load_custom(collection):
    names, seen = [], set()
    for folder in custom_icon_dirs():
        if not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(filename)
            # seen guards against the same name in two folders, harmless while
            # there is only one but kept so adding another cannot double-load
            if ext.lower() not in _LOADABLE or stem in seen:
                continue
            try:
                collection.load(CUSTOM_PREFIX + stem,
                                os.path.join(folder, filename), 'IMAGE')
                seen.add(stem)
                names.append(stem)
            except Exception as e:
                print(f"CocoPie: could not load custom icon {filename}: {e}")
    return names


def register_previews():
    """Load the slot arrows and any custom icons. Safe when files are missing."""
    global _previews, _custom_names

    unregister_previews()

    try:
        collection = bpy.utils.previews.new()
    except Exception as e:
        print(f"CocoPie: could not create the icon preview collection: {e}")
        return

    arrows = _load_slot_arrows(collection)
    _custom_names = _load_custom(collection)

    if arrows or _custom_names:
        _previews = collection
    else:
        try:
            bpy.utils.previews.remove(collection)
        except Exception:
            pass


def unregister_previews():
    global _previews, _custom_names
    if _previews is not None:
        try:
            bpy.utils.previews.remove(_previews)
        except Exception:
            pass
        _previews = None
    _custom_names = []


def _preview_id(key):
    if _previews is None:
        return 0
    entry = _previews.get(key)
    return entry.icon_id if entry else 0


def slot_icon_id(position):
    """icon_value for a slot direction, or 0 when the icons are unavailable"""
    return _preview_id(f"slot_{position}")


def custom_icon_names():
    """Names of the custom icons currently loaded, without the prefix"""
    return list(_custom_names)


def is_custom_icon(icon_ref):
    return bool(icon_ref) and icon_ref.startswith(CUSTOM_PREFIX)


def custom_icon_id(name):
    """icon_value for a custom icon by bare name, or 0 if it is not loaded"""
    return _preview_id(CUSTOM_PREFIX + name)


def icon_args(icon_ref, fallback='BLANK1'):
    """Keyword arguments drawing an item's icon, custom or built-in.

    Custom icons draw through icon_value and Blender's own through icon, so
    every caller has to pass whichever applies rather than a bare name. A
    custom icon whose file has since gone falls back rather than breaking the
    draw, the same way an unknown built-in name does.
    """
    if is_custom_icon(icon_ref):
        icon_id = custom_icon_id(icon_ref[len(CUSTOM_PREFIX):])
        return {"icon_value": icon_id} if icon_id else {"icon": fallback}
    return {"icon": safe_icon(icon_ref, fallback)}


def slot_button_args(position):
    """Keyword arguments drawing a slot's arrow, as an icon where possible.

    Falls back to the text glyph if the PNGs could not be loaded, so a missing
    or unreadable icons/ folder costs the look but never the function.
    """
    icon = slot_icon_id(position)
    if icon:
        return {"text": "", "icon_value": icon}
    return {"text": POSITION_ARROWS.get(position, '?')}
