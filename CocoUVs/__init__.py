# Support Blender's "Reload Scripts" (F3 > Reload Scripts) during development.
if "bpy" in locals():
    import importlib

    importlib.reload(common)
    importlib.reload(properties)
    importlib.reload(uv_sets)
    importlib.reload(texel)
    importlib.reload(heatmap)
    importlib.reload(debug)
    importlib.reload(checker)
    importlib.reload(trims)
    importlib.reload(prefs)
    importlib.reload(ui)
else:
    from . import common, properties, uv_sets, texel, heatmap, debug, checker, trims, prefs, ui

import bpy  # noqa: E402

_modules = (properties, uv_sets, texel, heatmap, debug, checker, trims, prefs, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()

