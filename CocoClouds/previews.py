"""The pictures of the cloud types, for the menus and the panel that add one.

previews/<GENUS>.png, one for each of cloud.TYPES (the genera), rendered once by the
probe make_previews.py (in the vault) and shipped with the add-on. Blender
loads them as icons of its own kind, which live from register() to
unregister(). A type without a picture gets no icon and still works.
"""
import os

import bpy
import bpy.utils.previews

from . import cloud

FOLDER = os.path.join(os.path.dirname(__file__), "previews")

_icons = None
# The types as an EnumProperty's items, each with its picture. Kept here:
# Blender does not hold on to the strings a callback hands it.
_items = []


def icon(ident):
    """The icon of a type's picture, 0 without one."""
    return _icons[ident].icon_id if _icons is not None and ident in _icons else 0


def type_items(_self, _context):
    return _items


# The chooser. Blender draws an enum as pictures to pick from
# (template_icon_view), and there alone a picture is what is clicked: a
# button does not enlarge its icon, and nothing can be laid over a picture.
# It is made to choose a value, though, and here a click is to add a cloud.
# So the value is a property with a setter of its own that adds the cloud,
# each time, the same type twice too; what it reads back is the type added
# last, which is the picture the chooser shows while closed.
_last = 0


def _chosen(_self):
    return _last


def _choose(_self, value):
    global _last
    _last = value
    # With undo: from Python an operator leaves no undo step and no panel
    # to redo it in unless told to.
    bpy.ops.cococlouds.add('EXEC_DEFAULT', True, type=cloud.TYPES[value][0])


# The same for the type of what is selected (the operator Cloud Type): it
# reads the type the active object has as a cloud, and for a mesh that is
# no cloud yet, or a cloud whose settings are no type's, the type picked
# last.
def _type(_self):
    ob = bpy.context.active_object
    kind = cloud.type_of(ob) if ob is not None else None
    return next((i for i, t in enumerate(cloud.TYPES) if kind and t[0] == kind[0]), _last)


def _set_type(_self, value):
    global _last
    _last = value
    bpy.ops.cococlouds.set_type('EXEC_DEFAULT', True, type=cloud.TYPES[value][0])


def register():
    global _icons
    _icons = bpy.utils.previews.new()
    for ident, *_rest in cloud.TYPES:
        path = os.path.join(FOLDER, ident + ".png")
        if os.path.isfile(path):
            _icons.load(ident, path, 'IMAGE')
    _items[:] = [(ident, label, description, icon(ident), index)
                 for index, (ident, label, description, _settings) in enumerate(cloud.TYPES)]
    bpy.types.WindowManager.cococlouds_add = bpy.props.EnumProperty(
        name="Add Cloud", description="Add a new cloud of this type at the 3D cursor",
        items=type_items, get=_chosen, set=_choose, options={'SKIP_SAVE'})
    bpy.types.WindowManager.cococlouds_type = bpy.props.EnumProperty(
        name="Cloud Genus", description=("Give the selected meshes this genus: every Deform setting becomes "
                                         "the genus's. A mesh of yours keeps its shape"),
        items=type_items, get=_type, set=_set_type, options={'SKIP_SAVE'})


def unregister():
    global _icons
    del bpy.types.WindowManager.cococlouds_add
    del bpy.types.WindowManager.cococlouds_type
    _items.clear()
    if _icons is not None:
        bpy.utils.previews.remove(_icons)
        _icons = None
