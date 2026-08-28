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
