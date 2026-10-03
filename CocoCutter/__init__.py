# Support Blender's "Reload Scripts" (F3 > Reload Scripts) during development.
if "bpy" in locals():
    import importlib

    importlib.reload(nodes)
    importlib.reload(cutter)
    importlib.reload(operators)
    importlib.reload(prefs)
    importlib.reload(ui)
else:
    from . import nodes, cutter, operators, prefs, ui

import bpy  # noqa: E402

_modules = (cutter, operators, prefs, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
