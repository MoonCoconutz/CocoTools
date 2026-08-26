bl_info = {
    "name": "CocoSelections",
    "author": "Coco",
    "version": (1, 2, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Sidebar (N) > Coco > Selections",
    "description": "Store named object selections and restore them with one click.",
    "category": "Object",
}

# Support Blender's "Reload Scripts" (F3 > Reload Scripts) during development.
if "bpy" in locals():
    import importlib

    importlib.reload(properties)
    importlib.reload(operators)
    importlib.reload(ui)
else:
    from . import properties, operators, ui

import bpy  # noqa: E402

_modules = (properties, operators, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()


if __name__ == "__main__":
    register()
