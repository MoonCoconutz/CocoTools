"""Icons CocoPies loads itself, rather than taking from Blender.

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

# Sculpt brush icons, which are a third kind again. They are triangle geometry
# rather than images, and load through bpy.app.icons instead of the preview
# collection -- so they need no GPU and, unlike a preview, still resolve under
# --background. Blender dropped these icons from its built-in set when brushes
# became assets in 4.3; the built-in set now has three brush icons in total,
# which is not enough to tell thirty-odd sculpt brushes apart.
BRUSH_PREFIX = "brush:"

_LOADABLE = (".png", ".jpg", ".jpeg")

# Filled on register; None while the addon is not registered
_previews = None
_custom_names = []
_brush_icons = {}


def icons_dir():
    """Folder the slot arrow PNGs ship in, inside this package"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def custom_icon_dirs():
    """Folders scanned for custom icons.

    Only one, inside the addon, so everything CocoPies owns stays within its own
    folder rather than scattering directories through Blender's scripts
    directory. The trade-off is that reinstalling the addon replaces the folder
    along with the rest of the package.
    """
    return [os.path.join(icons_dir(), "custom")]


def brush_icons_dir():
    """Folder the sculpt brush icon geometry ships in"""
    return os.path.join(icons_dir(), "brushes")


def _load_brush_icons():
    """Load icons/brushes/*.dat, keyed by the last dot-separated name part.

    brush.sculpt.draw_sharp.dat becomes "draw_sharp", matching how Blender's
    own icon files are named, so a slot refers to it as brush:draw_sharp.
    """
    loaded = {}
    folder = brush_icons_dir()
    if not os.path.isdir(folder):
        return loaded
    for filename in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(filename)
        if ext.lower() != ".dat":
            continue
        try:
            icon_id = bpy.app.icons.new_triangles_from_file(
                os.path.join(folder, filename))
        except Exception as e:
            print(f"CocoPies: could not load brush icon {filename}: {e}")
            continue
        if icon_id:
            loaded[stem.split(".")[-1]] = icon_id
    return loaded


def _release_brush_icons():
    global _brush_icons
    for icon_id in _brush_icons.values():
        try:
            bpy.app.icons.release(icon_id)
        except Exception:
            pass
    _brush_icons = {}


def _load_slot_arrows(collection):
    loaded = 0
    folder = icons_dir()
    for position in range(8):
        path = os.path.join(folder, f"slot_{position}.png")
        if not os.path.exists(path):
            print(f"CocoPies: slot icon missing: {path}")
            continue
        try:
            collection.load(f"slot_{position}", path, 'IMAGE')
            loaded += 1
        except Exception as e:
            print(f"CocoPies: could not load slot icon {position}: {e}")
    return loaded


# What a file actually is, read from its first bytes. Renaming an image does
# not convert it, and Blender loads a mislabelled file as a blank preview with
# no error -- which looks like the addon losing the icon rather than the file
# being the wrong format.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x00\x00\x01\x00", "ICO"),
    (b"\x00\x00\x02\x00", "CUR"),
    (b"GIF8", "GIF"),
    (b"BM", "BMP"),
    (b"RIFF", "WEBP"),
)


def _real_format(path):
    """The format a file really is, by its header, or None if unrecognised"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except Exception:
        return None
    for magic, name in _MAGIC:
        if head.startswith(magic):
            return name
    return None


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

            actual = _real_format(os.path.join(folder, filename))
            if actual not in ("PNG", "JPEG"):
                print(f"CocoPies: {filename} is named like an image but is "
                      f"{actual or 'an unrecognised format'} inside, so it "
                      f"would load blank -- convert it to a real PNG")
                continue
            try:
                collection.load(CUSTOM_PREFIX + stem,
                                os.path.join(folder, filename), 'IMAGE')
                seen.add(stem)
                names.append(stem)
            except Exception as e:
                print(f"CocoPies: could not load custom icon {filename}: {e}")
    return names


def register_previews():
    """Load the slot arrows, custom icons and brush icons.

    Safe when any of the files are missing -- each kind degrades on its own.
    """
    global _previews, _custom_names, _brush_icons

    unregister_previews()

    # Independent of the preview collection: these come from bpy.app.icons, so
    # they survive a collection that fails to create at all.
    _brush_icons = _load_brush_icons()

    try:
        collection = bpy.utils.previews.new()
    except Exception as e:
        print(f"CocoPies: could not create the icon preview collection: {e}")
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
    _release_brush_icons()
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


def brush_icon_names():
    """Names of the sculpt brush icons currently loaded, without the prefix"""
    return sorted(_brush_icons)


def is_brush_icon(icon_ref):
    return bool(icon_ref) and icon_ref.startswith(BRUSH_PREFIX)


def brush_icon_id(name):
    """icon_value for a brush icon by bare name, or 0 if it is not loaded"""
    return _brush_icons.get(name, 0)


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
    if is_brush_icon(icon_ref):
        icon_id = brush_icon_id(icon_ref[len(BRUSH_PREFIX):])
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
