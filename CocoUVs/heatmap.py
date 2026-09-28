"""Texel density heatmap: every island coloured by its density, red for the
lowest and green for the highest, drawn over the UVs in the UV Editor and over
the model in the 3D Viewport. Nothing is written into the mesh.

Two rules keep it from freezing Blender:

- It is never recomputed from a draw callback. An edit only marks it stale
  (and hides it, since it would be drawn in the wrong place); a timer
  recomputes it once the edits stop for DEBOUNCE seconds. During a drag the
  depsgraph updates on every mouse move, and recomputing each time locked
  Blender up on real meshes.
- The recompute reads each mesh once (common.read_mesh, shared with the
  Debug overlays) and does everything else (areas, colours) in numpy.
"""

import traceback

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import common

ALPHA = 0.5
DEBOUNCE = 0.25        # seconds without edits before recomputing
UNIFORM_SPREAD = 0.01  # islands within 1% of each other are shown as uniform

_handles = []
_dirty = True
_data = None       # last result of _compute(): numpy arrays and the legend
_batches = None    # GPU batches built from _data; needs a draw callback's GPU context


# --- Colours ----------------------------------------------------------------

def colors(t):
    """RGBA per value of t in 0..1: red at 0, green at 1, through orange and
    yellow. The hue is interpolated rather than RGB, so the middle is a
    bright yellow instead of a muddy olive (same as HSV with s=0.9, v=1)."""
    h = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0) * 2.0
    s = 0.9
    r = np.where(h < 1.0, 1.0, 1.0 - s * (h - 1.0))
    g = np.where(h < 1.0, 1.0 - s * (1.0 - h), 1.0)
    b = np.full_like(h, 1.0 - s)
    a = np.full_like(h, ALPHA)
    return np.stack([r, g, b, a], axis=-1).astype(np.float32)


# --- Computing --------------------------------------------------------------

def _object_triangles(obj, editing, sync, size, scale_length):
    """Fan triangles of one object's visible faces, each with its island's
    density. Only reads the mesh - in Edit Mode this may run mid-transform."""
    part = common.read_mesh(obj, editing, sync)
    if part is None:
        return None
    counts, island, tri_face = part["counts"], part["island"], part["tri_face"]
    world, uv = part["world"], part["uv"]
    a, b, c = part["corners"].T

    # Summed fan cross products give each face's vector area - exact for planar faces.
    cross = 0.5 * np.cross(world[b] - world[a], world[c] - world[a])
    face_world = np.sqrt(sum(np.bincount(tri_face, cross[:, i], minlength=len(counts)) ** 2 for i in range(3)))
    d1 = uv[b] - uv[a]
    d2 = uv[c] - uv[a]
    face_uv = np.abs(np.bincount(tri_face, 0.5 * (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]),
                                 minlength=len(counts)))

    n_islands = int(island.max()) + 1
    world_m2 = np.bincount(island, face_world, minlength=n_islands) * scale_length * scale_length
    uv_area = np.bincount(island, face_uv, minlength=n_islands)
    with np.errstate(divide='ignore', invalid='ignore'):
        ppm = np.where(world_m2 > 0.0, size * np.sqrt(uv_area / world_m2), np.nan)

    corners = part["corners"].ravel()
    return {
        "island_ppm": ppm,
        "tri_ppm": ppm[island[tri_face]],
        "world": world[corners].astype(np.float32),
        "uv": uv[corners].astype(np.float32) if editing else None,
        "uv_shown": np.repeat(part["shown"][tri_face], 3) if editing else None,
    }


def _compute():
    window = bpy.context.window or next(iter(bpy.context.window_manager.windows), None)
    if window is None:
        return None
    scene = window.scene
    size = int(scene.cocouvs.texture_size)
    scale_length = scene.unit_settings.scale_length or 1.0
    sync = scene.tool_settings.use_uv_select_sync
    objects, editing = common.source_objects(window.view_layer)

    parts = [p for p in (_object_triangles(o, editing, sync, size, scale_length) for o in objects) if p]
    island_ppm = np.concatenate([p["island_ppm"] for p in parts]) if parts else np.empty(0)
    island_ppm = island_ppm[np.isfinite(island_ppm)]
    if not len(island_ppm):
        return None
    low, high = float(island_ppm.min()), float(island_ppm.max())
    uniform = high <= 0.0 or (high - low) <= UNIFORM_SPREAD * high

    uv_pos, uv_col, w_pos, w_col = [], [], [], []
    for p in parts:
        tri_ppm = p["tri_ppm"]
        t = np.ones_like(tri_ppm) if uniform else (tri_ppm - low) / (high - low)
        vert_col = np.repeat(colors(t), 3, axis=0)
        valid = np.repeat(np.isfinite(tri_ppm), 3)
        w_pos.append(p["world"][valid])
        w_col.append(vert_col[valid])
        if p["uv"] is not None:
            keep = valid & p["uv_shown"]
            uv_pos.append(p["uv"][keep])
            uv_col.append(vert_col[keep])

    def join(chunks, width):
        return np.concatenate(chunks) if chunks else np.empty((0, width), dtype=np.float32)

    return {
        "uv_pos": join(uv_pos, 2), "uv_col": join(uv_col, 4),
        "w_pos": join(w_pos, 3), "w_col": join(w_col, 4),
        "low": low, "high": high, "uniform": uniform,
    }


def _rebuild_timer():
    global _dirty, _data, _batches
    try:
        _data = _compute()
    except Exception:
        traceback.print_exc()
        _data = None
    _batches = None
    _dirty = False
    common.redraw_all()
    return None


def mark_dirty(delay=DEBOUNCE):
    """Hide the heatmap and recompute it once edits have stopped for `delay`
    seconds. Every new edit pushes the recompute back again."""
    global _dirty
    _dirty = True
    if not _handles:
        return
    if bpy.app.timers.is_registered(_rebuild_timer):
        bpy.app.timers.unregister(_rebuild_timer)
    bpy.app.timers.register(_rebuild_timer, first_interval=delay)


# --- Drawing ----------------------------------------------------------------

def _get_batches():
    global _batches
    if _batches is None and _data is not None:
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')

        def batch(pos, col):
            return batch_for_shader(shader, 'TRIS', {"pos": pos, "color": col}) if len(pos) else None

        _batches = (batch(_data["uv_pos"], _data["uv_col"]), batch(_data["w_pos"], _data["w_col"]))
    return _batches


def _draw_uv():
    if _dirty:
        return
    context = bpy.context
    space = context.space_data
    if space is None or not space.show_uvedit:
        return
    batches = _get_batches()
    if batches is None or batches[0] is None:
        return
    x, y, w, h = common.uv_square(context.region)
    gpu.state.blend_set('ALPHA')
    with gpu.matrix.push_pop():
        gpu.matrix.translate((x, y))
        gpu.matrix.scale((w, h))
        batches[0].draw(gpu.shader.from_builtin('SMOOTH_COLOR'))
    gpu.state.blend_set('NONE')


def _draw_3d():
    if _dirty:
        return
    batches = _get_batches()
    if batches is None or batches[1] is None:
        return
    common.draw_on_surface([batches[1]], gpu.shader.from_builtin('SMOOTH_COLOR'))


# --- Switching on and off ---------------------------------------------------

@bpy.app.handlers.persistent
def _depsgraph_update(_scene, _depsgraph):
    common.forget_reads()
    mark_dirty()


@bpy.app.handlers.persistent
def _load_post(*_args):
    # The switch lives on the WindowManager: a file opened with its UI comes
    # with it off, one opened without (Load UI off) keeps this session's.
    set_enabled(bpy.context.window_manager.cocouvs_heatmap)


def set_enabled(enabled):
    global _data, _batches
    _remove_handlers()
    _data = None
    _batches = None
    common.forget_reads()
    if enabled:
        _handles.append((bpy.types.SpaceImageEditor, bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_uv, (), 'WINDOW', 'POST_PIXEL')))
        _handles.append((bpy.types.SpaceView3D, bpy.types.SpaceView3D.draw_handler_add(
            _draw_3d, (), 'WINDOW', 'POST_VIEW')))
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)
        mark_dirty(delay=0.0)
    try:
        common.redraw_all()
    except AttributeError:
        pass  # no window manager yet (headless / during load)


def _remove_handlers():
    for space, handle in _handles:
        space.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
    if _depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update)
    if bpy.app.timers.is_registered(_rebuild_timer):
        bpy.app.timers.unregister(_rebuild_timer)


def legend():
    """(lowest, highest, uniform) density in px/m of what is drawn, or None."""
    if _data is None:
        return None
    return _data["low"], _data["high"], _data["uniform"]


def register():
    bpy.app.handlers.load_post.append(_load_post)


def unregister():
    global _data, _batches
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    _remove_handlers()
    _data = None
    _batches = None
