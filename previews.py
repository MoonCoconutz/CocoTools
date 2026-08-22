"""Custom arrow icons for the eight pie slots.

Blender ships no diagonal arrow icon -- its whole arrow set (TRIA_*, EVENT_*,
RIGHTARROW and friends) is cardinal only -- so half a pie's directions have no
built-in icon to point at. The eight arrows are shipped as PNGs in icons/ and
loaded into a preview collection instead, which is the same route MACHIN3tools
and MESHmachine take for their custom icons.
"""

import os

import bpy
import bpy.utils.previews

from .items import POSITION_ARROWS

# Filled on register; None while the addon is not registered
_slot_previews = None


def icons_dir():
    """Folder the slot arrow PNGs ship in, inside this package"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def register_previews():
    """Load the slot arrows. Safe to call when the files are missing."""
    global _slot_previews

    unregister_previews()

    try:
        collection = bpy.utils.previews.new()
    except Exception as e:
        print(f"CocoPie: could not create the icon preview collection: {e}")
        return

    folder = icons_dir()
    loaded = 0
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

    _slot_previews = collection if loaded else None
    if not loaded:
        try:
            bpy.utils.previews.remove(collection)
        except Exception:
            pass


def unregister_previews():
    global _slot_previews
    if _slot_previews is not None:
        try:
            bpy.utils.previews.remove(_slot_previews)
        except Exception:
            pass
        _slot_previews = None


def slot_icon_id(position):
    """icon_value for a slot direction, or 0 when the icons are unavailable"""
    if _slot_previews is None:
        return 0
    entry = _slot_previews.get(f"slot_{position}")
    return entry.icon_id if entry else 0


def slot_button_args(position):
    """Keyword arguments drawing a slot's arrow, as an icon where possible.

    Falls back to the text glyph if the PNGs could not be loaded, so a missing
    or unreadable icons/ folder costs the look but never the function.
    """
    icon = slot_icon_id(position)
    if icon:
        return {"text": "", "icon_value": icon}
    return {"text": POSITION_ARROWS.get(position, '?')}
