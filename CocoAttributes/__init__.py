# Support Blender's "Reload Scripts" (F3 > Reload Scripts) during development.
if "bpy" in locals():
    import importlib

    importlib.reload(common)
    importlib.reload(lists)
    importlib.reload(operators)
    importlib.reload(ui)
else:
    from . import common, lists, operators, ui

import bpy  # noqa: E402

_modules = (lists, operators, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
