"""The pictures of the genera, for the menus and the panel that add one.

previews/<GENUS>.png, one for each of cloud.TYPES (the genera), rendered once by the
probe lookdev_genera.py (in the vault) and shipped with the add-on. A genus without a
picture still works.

They are used twice:

- as icons (bpy.utils.previews), living from register() to unregister(), for
  the Add menu's list and the operators' enums;
- as Image datablocks, for the panel's two choosers. Blender opens pictures to
  click in a grid as wide as asked for only to pick a datablock
  (template_search_preview); its chooser for an enum, template_icon_view, puts
  them eight to a row whatever is asked, which for these is one long row.

So each chooser is a pointer to an Image whose poll lets only these pictures
in, and whose update does what the click is for: add a cloud, or give the
selection a genus. The images are the add-on's, not the user's: they are kept
out of the saved file (a datablock with no users is not written, so their
users, a hidden collection of pointers and the choosers, are let go of just
before a save and taken back after), loaded again after a file is opened, and
removed with the add-on. The chooser shows the image's name under the
picture, and Blender lets it be edited: an image renamed takes its genus's
name back at once (a datablock's name can be made read-only only by linking
it from another file, which puts an L and the file's name on every name in
the grid).
"""
import math
import os

import bpy
import bpy.utils.previews
from bpy.app.handlers import persistent
from bpy.props import CollectionProperty, PointerProperty
from bpy.types import Image, PropertyGroup

from . import cloud

FOLDER = os.path.join(os.path.dirname(__file__), "previews")
# The custom property that marks an image as a genus's picture, holding the genus.
IMAGE_KEY = "cococlouds_genus"
# The grid the choosers open, and how tall the picture they show closed is
# against Blender's own size for it, which takes half the sidebar.
COLUMNS = 3
PICTURE_SCALE = 0.6

_icons = None
# The types as an EnumProperty's items, each with its picture. Kept here:
# Blender does not hold on to the strings a callback hands it.
_items = []


def icon(ident):
    """The icon of a type's picture, 0 without one."""
    return _icons[ident].icon_id if _icons is not None and ident in _icons else 0


def type_items(_self, _context):
    return _items


def rows():
    return math.ceil(len(cloud.TYPES) / COLUMNS)


# ---------------------------------------------------------------- the pictures as images

def _path(ident):
    return os.path.join(FOLDER, ident + ".png")


def _image(ident):
    """The image of a genus's picture, None when it is not loaded."""
    return next((im for im in bpy.data.images if im.get(IMAGE_KEY) == ident), None)


class CocoCloudsPicture(PropertyGroup):
    image: PointerProperty(type=Image)


def ensure_images():
    """Load the pictures that are not loaded, and give each a user, without
    which its name in the chooser would read "0 Cumulus"."""
    held = bpy.context.window_manager.cococlouds_pictures
    have = {item.image for item in held if item.image is not None}
    for ident, label, *_rest in cloud.TYPES:
        if not os.path.isfile(_path(ident)):
            continue
        im = _image(ident)
        if im is None:
            im = bpy.data.images.load(_path(ident), check_existing=False)
            im.name = label
            im[IMAGE_KEY] = ident
        elif os.path.normcase(bpy.path.abspath(im.filepath)) != os.path.normcase(_path(ident)):
            # From a file saved before the add-on was moved or updated.
            im.filepath = _path(ident)
        if im not in have:
            held.add().image = im


def _let_go():
    wm = bpy.context.window_manager
    wm.cococlouds_pictures.clear()
    global _quiet
    _quiet = True
    try:
        wm.cococlouds_add = None
        wm.cococlouds_type = None
    finally:
        _quiet = False


# Who the message bus calls back when an image is renamed.
_owner = object()


def _named(*_args):
    """Give a renamed picture its genus's name back, unless an image of the
    user's has taken that name."""
    labels = {ident: label for ident, label, *_rest in cloud.TYPES}
    for im in bpy.data.images:
        label = labels.get(im.get(IMAGE_KEY))
        if label is None or im.name == label:
            continue
        other = bpy.data.images.get(label)
        if other is None or other == im:
            im.name = label


def _watch_names():
    bpy.msgbus.clear_by_owner(_owner)
    bpy.msgbus.subscribe_rna(key=(Image, "name"), owner=_owner, args=(), notify=_named)


def _ours(_self, image):
    return image.get(IMAGE_KEY) in _genera


_genera = set()


# ---------------------------------------------------------------- the choosers
#
# A click on a picture sets the pointer, and its update does the rest. The
# pointer then shows the picture of the genus added last (Add Cloud) or of
# the active cloud's genus (Cloud Genus). The panel cannot write it while it
# draws, so it asks for it to be put right a moment later (show()).
_quiet = False
_last = None


def _picked(prop, run):
    def update(self, _context):
        global _last
        image = getattr(self, prop)
        if _quiet or image is None:
            return
        _last = image[IMAGE_KEY]
        # With undo: from Python an operator leaves no undo step and no panel
        # to redo it in unless told to.
        run('EXEC_DEFAULT', True, type=_last)
    return update


def _wanted(prop, context):
    """The genus a chooser should show."""
    if prop == "cococlouds_type":
        kind = cloud.type_of(context.active_object)
        if kind is not None:
            return kind[0]
    return _last or cloud.TYPES[0][0]


_pending = set()


def _put_right(window_manager, prop, ident):
    global _quiet
    _pending.discard(prop)
    if _image(ident) is None:
        ensure_images()
    image = _image(ident)
    if image is None or getattr(window_manager, prop) == image:
        return
    _quiet = True
    try:
        setattr(window_manager, prop, image)
    finally:
        _quiet = False
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def show(layout, context, prop):
    """Draw a chooser: a picture that opens the genera's pictures in a grid."""
    wm = context.window_manager
    ident = _wanted(prop, context)
    image = getattr(wm, prop)
    # Put right once: a genus without a picture stays without one.
    if (image is None or image.get(IMAGE_KEY) != ident) and prop not in _pending \
            and (_image(ident) is not None or not wm.cococlouds_pictures):
        _pending.add(prop)
        bpy.app.timers.register(lambda: _put_right(wm, prop, ident), first_interval=0.0)
    row = layout.row()
    row.alignment = 'CENTER'
    row.scale_y = PICTURE_SCALE
    row.template_search_preview(wm, prop, bpy.data, "images", rows=rows(), cols=COLUMNS)


# ---------------------------------------------------------------- saving and loading

@persistent
def _before_save(_path_):
    _let_go()


@persistent
def _after_save(_path_):
    ensure_images()


@persistent
def _after_load(_path_):
    ensure_images()
    # Opening a file drops every subscription.
    _watch_names()


def register():
    global _icons
    _icons = bpy.utils.previews.new()
    for ident, *_rest in cloud.TYPES:
        if os.path.isfile(_path(ident)):
            _icons.load(ident, _path(ident), 'IMAGE')
    _items[:] = [(ident, label, description, icon(ident), index)
                 for index, (ident, label, description, _settings) in enumerate(cloud.TYPES)]
    _genera.update(ident for ident, *_rest in cloud.TYPES)
    bpy.utils.register_class(CocoCloudsPicture)
    wm = bpy.types.WindowManager
    wm.cococlouds_pictures = CollectionProperty(type=CocoCloudsPicture, options={'HIDDEN'})
    wm.cococlouds_add = PointerProperty(
        type=Image, name="Add Cloud", description="Add a new cloud of this genus at the 3D cursor",
        poll=_ours, update=_picked("cococlouds_add", bpy.ops.cococlouds.add))
    wm.cococlouds_type = PointerProperty(
        type=Image, name="Cloud Genus",
        description=("Give the selected meshes and curves this genus: every Deform setting becomes the genus's. "
                     "A shape of yours keeps its shape"),
        poll=_ours, update=_picked("cococlouds_type", bpy.ops.cococlouds.set_type))
    bpy.app.handlers.save_pre.append(_before_save)
    bpy.app.handlers.save_post.append(_after_save)
    bpy.app.handlers.load_post.append(_after_load)
    # bpy.data is out of reach while add-ons are registered at start-up.
    bpy.app.timers.register(lambda: (ensure_images(), _watch_names()) and None, first_interval=0.0)


def unregister():
    global _icons
    bpy.msgbus.clear_by_owner(_owner)
    for handlers, fn in ((bpy.app.handlers.save_pre, _before_save), (bpy.app.handlers.save_post, _after_save),
                         (bpy.app.handlers.load_post, _after_load)):
        if fn in handlers:
            handlers.remove(fn)
    try:
        _let_go()
        for im in [im for im in bpy.data.images if IMAGE_KEY in im]:
            bpy.data.images.remove(im)
    except AttributeError:
        # Blender closing: bpy.data is out of reach, and nothing is saved anyway.
        pass
    wm = bpy.types.WindowManager
    del wm.cococlouds_add
    del wm.cococlouds_type
    del wm.cococlouds_pictures
    bpy.utils.unregister_class(CocoCloudsPicture)
    _genera.clear()
    _items.clear()
    if _icons is not None:
        bpy.utils.previews.remove(_icons)
        _icons = None
