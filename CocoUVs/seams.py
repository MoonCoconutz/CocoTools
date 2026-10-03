"""Seams Update in Edit Mode: the seams follow the active UV map's islands.

Any command can change the islands - Rip, Unwrap, Stitch, another add-on's -
so nothing is hooked to a list of operators. A depsgraph update only starts a
short timer, as the overlays do, and the timer compares the island borders
with the ones the seams were last set from (common.follow_uv_islands).
"""

import bpy

from . import common

DEBOUNCE = 0.25


def _modal_running():
    """A transform or another modal is holding the mesh: do not touch it now."""
    return any(len(window.modal_operators) for window in bpy.context.window_manager.windows)


def _follow_timer():
    try:
        if _modal_running():
            return DEBOUNCE
        window = bpy.context.window or next(iter(bpy.context.window_manager.windows), None)
        if window is None or not window.scene.cocouvs.update_seams:
            return None
        for obj in common.unique_meshes(common._editing(window.view_layer)):
            active = obj.data.uv_layers.active
            if active is not None:
                common.follow_uv_islands(obj, active.name)
    except Exception as error:
        # A timer that raises is dropped without a word
        print(f"CocoUVs: Seams Update failed: {error!r}")
    return None


def request_follow():
    if bpy.app.timers.is_registered(_follow_timer):
        bpy.app.timers.unregister(_follow_timer)
    bpy.app.timers.register(_follow_timer, first_interval=DEBOUNCE)


@bpy.app.handlers.persistent
def _depsgraph_update(scene, depsgraph):
    if not scene.cocouvs.update_seams or not depsgraph.id_type_updated('MESH'):
        return
    active = bpy.context.view_layer.objects.active
    if active is not None and active.mode == 'EDIT':
        request_follow()


@bpy.app.handlers.persistent
def _load_post(*_args):
    request_follow()


def register():
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)
    bpy.app.handlers.load_post.append(_load_post)
    request_follow()


def unregister():
    for handlers, handler in ((bpy.app.handlers.depsgraph_update_post, _depsgraph_update),
                              (bpy.app.handlers.load_post, _load_post)):
        if handler in handlers:
            handlers.remove(handler)
    if bpy.app.timers.is_registered(_follow_timer):
        bpy.app.timers.unregister(_follow_timer)
