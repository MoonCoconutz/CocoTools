"""Autosave next to the .blend, instead of Blender's temp folder.

Blender's own autosave writes `<pid>_autosave.blend` into the temp directory,
where it is easy to lose track of which file it belongs to. This one writes
`<name>_autosave_<dd-mm-YYYY_HH.MM>.blend` in a `Backup` folder next to the file, every
N minutes, and keeps only the newest M of them.

It saves a *copy* (save_as_mainfile(copy=True)): the open file keeps its own
path and its unsaved state, exactly as if nothing had happened.

Only when something changed since the last autosave or save: an idle file is
not written again and again. A file that was never saved has no folder, so it
is skipped.
"""

import glob
import os
from datetime import datetime

import bpy
from bpy.app.handlers import persistent


_changed = False


# Autosaves go in a "Backup" folder beside the .blend, created on first save,
# so they do not crowd the folder the user works in.
BACKUP_FOLDER = "Backup"


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _pattern(filepath):
    folder, name = os.path.split(filepath)
    folder = os.path.join(folder, BACKUP_FOLDER)
    stem = os.path.splitext(name)[0]
    return folder, stem, os.path.join(glob.escape(folder), glob.escape(stem) + "_autosave_*.blend")


def autosave_files(filepath):
    """Existing autosaves of `filepath`, oldest first."""
    _folder, _stem, pattern = _pattern(filepath)
    # By modification time: the day-first names do not sort by date.
    return sorted(glob.glob(pattern), key=os.path.getmtime)


def save_now():
    """Write one autosave of the open file. Returns its path, or None."""
    global _changed
    filepath = bpy.data.filepath
    if not filepath:
        return None
    folder, stem, _pattern_ = _pattern(filepath)
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, f"{stem}_autosave_{datetime.now():%d-%m-%Y_%H.%M}.blend")

    window = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
    if window is None:
        return None
    with bpy.context.temp_override(window=window):
        bpy.ops.wm.save_as_mainfile(filepath=target, copy=True, check_existing=False)
    _changed = False
    _prune(filepath)
    return target


def _prune(filepath):
    prefs = _prefs()
    keep = prefs.autosave_versions if prefs else 3
    files = autosave_files(filepath)
    for old in files[:max(0, len(files) - keep)]:
        try:
            os.remove(old)
        except OSError as e:
            print(f"CocoBackup: could not remove old autosave {old}: {e}")


def _tick():
    prefs = _prefs()
    if prefs is None:
        return 60.0
    interval = max(1, prefs.autosave_interval) * 60.0
    if not prefs.use_autosave:
        return interval
    try:
        if _changed and bpy.data.filepath and not bpy.app.is_job_running('RENDER'):
            save_now()
    except Exception as e:
        print(f"CocoBackup: autosave failed: {e}")
    return interval


@persistent
def _on_change(_scene, _depsgraph):
    global _changed
    _changed = True


@persistent
def _on_save_or_load(*_args):
    # A real save (or a freshly opened file) is a fresh start: nothing to
    # autosave until the next edit.
    global _changed
    _changed = False


def restart_timer():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    prefs = _prefs()
    minutes = prefs.autosave_interval if prefs else 5
    bpy.app.timers.register(_tick, first_interval=max(1, minutes) * 60.0, persistent=True)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_on_change)
    bpy.app.handlers.save_post.append(_on_save_or_load)
    bpy.app.handlers.load_post.append(_on_save_or_load)
    # Preferences are not reachable yet during register() at startup.
    bpy.app.timers.register(restart_timer, first_interval=1.0)


def unregister():
    if bpy.app.timers.is_registered(restart_timer):
        bpy.app.timers.unregister(restart_timer)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_change),
                         (bpy.app.handlers.save_post, _on_save_or_load),
                         (bpy.app.handlers.load_post, _on_save_or_load)):
        if fn in handlers:
            handlers.remove(fn)
