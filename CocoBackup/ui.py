"""The coconut button in the 3D Viewport header, and the panel it opens."""

import os

import bpy
import bpy.utils.previews
from bpy.app.handlers import persistent
from bpy.types import Panel


_previews = None


def coconut_icon():
    if _previews is None:
        return 0
    return _previews["coconut"].icon_id


def file_state():
    """"unsaved": never written to disk (no path). "saved": on disk and nothing
    changed since. "modified": on disk, with changes not saved yet."""
    if not bpy.data.filepath:
        return "unsaved"
    return "modified" if bpy.data.is_dirty else "saved"


_STATE_ICONS = {"unsaved": "coconut_unsaved", "saved": "coconut_saved", "modified": "coconut"}


def status_icon():
    """The header button: red coconut for a file that exists nowhere on disk,
    green for a saved one, plain for a saved file with unsaved changes."""
    if _previews is None:
        return 0
    return _previews[_STATE_ICONS[file_state()]].icon_id


# The colour follows bpy.data.is_dirty, which Blender sets after an operator's
# undo push -- i.e. after depsgraph_update_post has already run. So each event
# schedules one check a moment later instead, which redraws the 3D Viewport
# headers only if the state actually changed. Nothing polls.

_last_state = None


def _check_status():
    global _last_state
    state = file_state()
    if state != _last_state:
        _last_state = state
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'HEADER':
                            region.tag_redraw()
    return None


@persistent
def _on_event(*_args):
    if not bpy.app.timers.is_registered(_check_status):
        bpy.app.timers.register(_check_status, first_interval=0.1)


_HANDLERS = ("depsgraph_update_post", "save_post", "load_post", "undo_post", "redo_post")


class COCOBACKUP_PT_menu(Panel):
    bl_idname = "COCOBACKUP_PT_menu"
    bl_label = "CocoBackup"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    def draw(self, context):
        layout = self.layout
        layout.label(text="CocoBackup", icon_value=coconut_icon())

        col = layout.column(align=True)
        col.scale_y = 1.3
        # Buttons in a panel opened by wm.call_panel run with EXEC by default:
        # the operator would skip the file browser and get no path at all.
        col.operator_context = 'INVOKE_DEFAULT'
        col.operator("cocobackup.export_backup", text="Export Backup…", icon='EXPORT')
        col.operator("cocobackup.import_backup", text="Import Backup…", icon='IMPORT')

        addon = context.preferences.addons.get(__package__)
        if addon is None:
            return
        prefs = addon.preferences
        box = layout.box()
        box.prop(prefs, "use_autosave", text="Autosave to a Backup folder")
        sub = box.column()
        sub.active = prefs.use_autosave
        sub.prop(prefs, "autosave_interval", text="Every (minutes)")
        sub.prop(prefs, "autosave_versions", text="Versions to keep")
        if prefs.use_autosave and not bpy.data.filepath:
            sub.label(text="Save the file once to start", icon='INFO')


# The button sits right after the header's menus (View, Select, Add, Object)
# and whatever other add-ons append there -- where the user asked for it.
# VIEW3D_MT_editor_menus is the row those menus are drawn from, and appending
# to it is the ordinary, supported way to add to that row.

def draw_header_button(self, _context):
    # A popover opens anchored under its button, like View / Select, and draws
    # a dropdown arrow beside the icon, which the user asked for. (wm.call_panel
    # opened the panel wherever the mouse was.)
    self.layout.popover(COCOBACKUP_PT_menu.bl_idname, text="", icon_value=status_icon())


def _scrub(menu):
    """Remove earlier copies of the button by name, so a reload never doubles it."""
    draw_funcs = menu._dyn_ui_initialize()
    draw_funcs[:] = [fn for fn in draw_funcs
                     if not (getattr(fn, "__name__", "") == "draw_header_button"
                             and getattr(fn, "__module__", "") == __name__)]


def _unwrap_old_tool_header():
    """1.0.0 wrapped the tool header's draw_tool_settings; put it back."""
    header = bpy.types.VIEW3D_HT_tool_header
    original = getattr(header.draw_tool_settings, "_cocobackup_original", None)
    if original is not None:
        header.draw_tool_settings = original


def register():
    global _previews
    _previews = bpy.utils.previews.new()
    _previews.load("coconut", os.path.join(os.path.dirname(__file__), "icons", "coconut.png"), 'IMAGE')
    for name in ("coconut_saved", "coconut_unsaved"):
        _previews.load(name, os.path.join(os.path.dirname(__file__), "icons", name + ".png"), 'IMAGE')
    bpy.utils.register_class(COCOBACKUP_PT_menu)
    _unwrap_old_tool_header()
    _scrub(bpy.types.VIEW3D_MT_editor_menus)
    bpy.types.VIEW3D_MT_editor_menus.append(draw_header_button)
    for name in _HANDLERS:
        getattr(bpy.app.handlers, name).append(_on_event)


def unregister():
    global _previews
    for name in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if _on_event in handlers:
            handlers.remove(_on_event)
    if bpy.app.timers.is_registered(_check_status):
        bpy.app.timers.unregister(_check_status)
    _scrub(bpy.types.VIEW3D_MT_editor_menus)
    bpy.utils.unregister_class(COCOBACKUP_PT_menu)
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
