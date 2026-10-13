# Support Blender's "Reload Scripts" (F3 > Reload Scripts) during development.
if "bpy" in locals():
    import importlib

    importlib.reload(nodes)
    importlib.reload(shapes)
    importlib.reload(look)
    importlib.reload(cloud)
    importlib.reload(previews)
    importlib.reload(field)
    importlib.reload(operators)
    importlib.reload(ui)
else:
    from . import nodes, shapes, look, cloud, previews, field, operators, ui

import bpy  # noqa: E402

_modules = (look, cloud, previews, field, operators, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
