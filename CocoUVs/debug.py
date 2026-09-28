"""Debug section: Done marks, flipped / overlapping / self-intersecting UVs,
and seam / crease / sharp / bevel-weight edges.

Face kinds are drawn over the UVs in the UV Editor and over the model in the
3D Viewport; edge marks only in the UV Editor (the 3D Viewport already shows
them in Edit Mode). Each kind has a select operator.

Same rules as the heatmap: never recompute from a draw callback (an edit only
marks the overlay stale and hides it; a timer recomputes once edits stop), and
only read the mesh - it may be mid-transform. The read (common.read_mesh) is
shared with the heatmap.

Definitions:
- Flipped: an island whose total signed UV area is negative - its UVs wind
  the other way round from its faces, i.e. it is mirrored.
- Overlapping: an island with a UV triangle overlapping a triangle of a
  *different* island (any object in Edit Mode - they share UV space).
- Self-Intersecting: faces overlapping another face of the *same* island
  (folds). Triangles that merely touch along an edge or corner do not count.
- Done: faces carrying the per-UV-map Done attribute (common.done_layer_name).
"""

import traceback

import bmesh
import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader

from . import common

ALPHA = 0.45
DEBOUNCE = 0.25
OVERLAP_EPS = 1e-6     # UV units of overlap below which triangles only "touch"
SAT_CHUNK = 400_000    # triangle pairs tested per numpy batch

FACE_KINDS = ('DONE', 'FLIPPED', 'OVERLAP', 'SELF')
# kind: (label, legend icon, strip-colour slot for the overlay)
KIND_INFO = {
    'DONE': ("Done", 'STRIP_COLOR_05', 4),
    'FLIPPED': ("Flipped", 'STRIP_COLOR_07', 6),
    'OVERLAP': ("Overlapping", 'STRIP_COLOR_02', 1),
    'SELF': ("Self-Intersecting", 'STRIP_COLOR_03', 2),
}
# Edge marks, drawn bottom to top, with the 3D Viewport theme colour they use.
EDGE_TYPES = common.EDGE_TYPES
EDGE_THEME = {'BEVEL': "bevel", 'CREASE': "crease", 'SHARP': "sharp", 'SEAM': "seam"}

_handles = []
_dirty = True
_data = None      # last analysis: numpy arrays for drawing and counts
_batches = None   # GPU batches built from _data inside a draw callback


# --- Settings ----------------------------------------------------------------

def _enabled_kinds(wm):
    return {k for k in FACE_KINDS if getattr(wm, f"cocouvs_debug_{k.lower()}")}


def _any_enabled(wm):
    return bool(_enabled_kinds(wm)) or wm.cocouvs_debug_edges


def kind_color(kind):
    """The overlay colour: the theme's strip colour behind the row's legend
    icon, so the icon and the overlay always match."""
    return (*bpy.context.preferences.themes[0].strip_color[KIND_INFO[kind][2]].color, ALPHA)


def edge_color(kind):
    theme = bpy.context.preferences.themes[0].view_3d
    return (*getattr(theme, EDGE_THEME[kind])[:3], 1.0)


# --- Analysis ------------------------------------------------------------------

def _candidate_pairs(lo, hi):
    """Triangle pairs whose bounding boxes share a grid cell (each pair once)."""
    n = len(lo)
    if n < 2:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    extent = (hi - lo).max(axis=1)
    h = max(float(np.median(extent)) * 2.0, 1e-6)
    while True:
        i0 = np.floor(lo / h).astype(np.int64)
        i1 = np.floor(hi / h).astype(np.int64)
        w = i1[:, 0] - i0[:, 0] + 1
        cells = w * (i1[:, 1] - i0[:, 1] + 1)
        if cells.sum() <= 8 * n + 1_000_000:
            break
        h *= 2.0
    tri = np.repeat(np.arange(n), cells)
    k = np.arange(len(tri)) - np.repeat(np.cumsum(cells) - cells, cells)
    cx = i0[tri, 0] + k % w[tri]
    cy = i0[tri, 1] + k // w[tri]
    key = (cx - cx.min()) * (int(cy.max() - cy.min()) + 1) + (cy - cy.min())
    order = np.argsort(key, kind='stable')
    key, tri, cx, cy = key[order], tri[order], cx[order], cy[order]
    first = np.r_[True, key[1:] != key[:-1]]
    group_end = np.r_[np.flatnonzero(first)[1:], len(key)]
    end = group_end[np.cumsum(first) - 1]
    partners = end - np.arange(len(key)) - 1
    a = np.repeat(np.arange(len(key)), partners)
    b = a + 1 + (np.arange(len(a)) - np.repeat(np.cumsum(partners) - partners, partners))
    p, q = tri[a], tri[b]
    # Two triangles spanning several cells meet in each shared one. Keep the
    # pair only in the lowest shared cell, so it comes out once without an
    # np.unique over all pairs (which was half the run time).
    keep = (cx[a] == np.maximum(i0[p, 0], i0[q, 0])) & (cy[a] == np.maximum(i0[p, 1], i0[q, 1]))
    return p[keep], q[keep]


def _sat_overlap(P, Q, eps):
    """For triangle pairs (N,3,2): True where they overlap by more than eps
    (no separating axis among the six edge normals)."""
    separated = np.zeros(len(P), dtype=bool)
    for X in (P, Q):
        for e in range(3):
            d = X[:, (e + 1) % 3] - X[:, e]
            axis = np.stack([-d[:, 1], d[:, 0]], axis=1)
            axis /= np.linalg.norm(axis, axis=1)[:, None]
            pp = np.einsum('nkj,nj->nk', P, axis)
            qq = np.einsum('nkj,nj->nk', Q, axis)
            separated |= (pp.max(axis=1) <= qq.min(axis=1) + eps) | (qq.max(axis=1) <= pp.min(axis=1) + eps)
    return ~separated


def overlapping_pairs(tris, eps=OVERLAP_EPS):
    """Pairs (i, j) of UV triangles (T,3,2) that overlap."""
    d1 = tris[:, 1] - tris[:, 0]
    d2 = tris[:, 2] - tris[:, 0]
    usable = np.flatnonzero(np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) > 1e-14)
    t = tris[usable]
    lo, hi = t.min(axis=1), t.max(axis=1)
    i, j = _candidate_pairs(lo, hi)
    boxes = ((lo[i] < hi[j] - eps) & (lo[j] < hi[i] - eps)).all(axis=1)
    i, j = i[boxes], j[boxes]
    hit = np.zeros(len(i), dtype=bool)
    for s in range(0, len(i), SAT_CHUNK):
        hit[s:s + SAT_CHUNK] = _sat_overlap(t[i[s:s + SAT_CHUNK]], t[j[s:s + SAT_CHUNK]], eps)
    return usable[i[hit]], usable[j[hit]]


def analyze(parts, kinds):
    """Face mask per kind for each part (in place: part["masks"]), and how
    many islands (faces for SELF) each kind found overall."""
    counts = {}
    for part in parts:
        part["masks"] = {}
        island, tri_face, c = part["island"], part["tri_face"], part["corners"]
        n_faces, n_islands = len(part["counts"]), int(island.max()) + 1
        uv = part["uv"]
        if 'DONE' in kinds:
            part["masks"]['DONE'] = part["done"]
        if 'FLIPPED' in kinds:
            d1, d2 = uv[c[:, 1]] - uv[c[:, 0]], uv[c[:, 2]] - uv[c[:, 0]]
            signed = np.bincount(tri_face, d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0], minlength=n_faces)
            flipped = np.bincount(island, signed, minlength=n_islands) < 0.0
            part["masks"]['FLIPPED'] = flipped[island]
        part["n_islands"] = n_islands

    if {'OVERLAP', 'SELF'} & kinds:
        tris, g_island, g_face = [], [], []
        island_base = face_base = 0
        for part in parts:
            tris.append(part["uv"][part["corners"]])
            g_island.append(part["island"][part["tri_face"]] + island_base)
            g_face.append(part["tri_face"] + face_base)
            part["island_base"], part["face_base"] = island_base, face_base
            island_base += part["n_islands"]
            face_base += len(part["counts"])
        g_island, g_face = np.concatenate(g_island), np.concatenate(g_face)
        i, j = overlapping_pairs(np.concatenate(tris))
        same_island = g_island[i] == g_island[j]
        other = ~same_island
        island_hit = np.zeros(island_base, dtype=bool)
        island_hit[g_island[i[other]]] = True
        island_hit[g_island[j[other]]] = True
        folded = same_island & (g_face[i] != g_face[j])
        face_hit = np.zeros(face_base, dtype=bool)
        face_hit[g_face[i[folded]]] = True
        face_hit[g_face[j[folded]]] = True
        for part in parts:
            ib, fb, n = part["island_base"], part["face_base"], len(part["counts"])
            if 'OVERLAP' in kinds:
                part["masks"]['OVERLAP'] = island_hit[part["island"] + ib]
            if 'SELF' in kinds:
                part["masks"]['SELF'] = face_hit[fb:fb + n]

    for kind in kinds:
        total = 0
        for part in parts:
            mask = part["masks"][kind]
            total += int(mask.sum()) if kind == 'SELF' else len(np.unique(part["island"][mask]))
        counts[kind] = total
    return counts


def _loop_next(part):
    counts, starts = part["counts"], part["starts"]
    nxt = np.arange(int(counts.sum())) + 1
    nxt[starts + counts - 1] = starts
    return nxt


# --- Overlay -------------------------------------------------------------------

def _compute():
    wm = bpy.context.window_manager
    window = bpy.context.window or next(iter(wm.windows), None)
    if window is None:
        return None
    kinds = _enabled_kinds(wm)
    want_edges = wm.cocouvs_debug_edges
    sync = window.scene.tool_settings.use_uv_select_sync
    objects, editing = common.source_objects(window.view_layer)
    parts = [p for p in (common.read_mesh(o, editing, sync, want_edges and editing) for o in objects) if p]
    if not parts:
        return None
    counts = analyze(parts, kinds)

    faces = {}
    for kind in FACE_KINDS:
        if kind not in kinds:
            continue
        uv_pos, w_pos = [], []
        for part in parts:
            tri_mask = part["masks"][kind][part["tri_face"]]
            corners = part["corners"][tri_mask].ravel()
            w_pos.append(part["world"][corners])
            if editing:
                shown = part["shown"][part["tri_face"]][tri_mask]
                uv_pos.append(part["uv"][part["corners"][tri_mask][shown].ravel()])
        faces[kind] = (np.concatenate(uv_pos).astype(np.float32) if uv_pos else np.empty((0, 2), np.float32),
                       np.concatenate(w_pos).astype(np.float32))

    edges = []
    if want_edges and editing:
        for kind in EDGE_TYPES:
            seg = []
            for part in parts:
                shown = np.repeat(part["shown"], part["counts"])
                marked = np.flatnonzero(part["loop_marks"][kind] & shown)
                if len(marked):
                    nxt = _loop_next(part)
                    seg.append(np.stack([part["uv"][marked], part["uv"][nxt[marked]]], axis=1).reshape(-1, 2))
            if seg:
                edges.append((kind, np.concatenate(seg).astype(np.float32)))
    return {"faces": faces, "edges": edges, "counts": counts}


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
    global _dirty
    _dirty = True
    if not _handles:
        return
    if bpy.app.timers.is_registered(_rebuild_timer):
        bpy.app.timers.unregister(_rebuild_timer)
    bpy.app.timers.register(_rebuild_timer, first_interval=delay)


def _tile(color, n):
    return np.tile(np.array(color, dtype=np.float32), (n, 1))


def _get_batches():
    global _batches
    if _batches is None and _data is not None:
        tri_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        line_shader = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
        uv, view3d, lines = [], [], []
        for kind in FACE_KINDS:
            if kind not in _data["faces"]:
                continue
            uv_pos, w_pos = _data["faces"][kind]
            color = kind_color(kind)
            if len(uv_pos):
                uv.append(batch_for_shader(tri_shader, 'TRIS', {"pos": uv_pos, "color": _tile(color, len(uv_pos))}))
            if len(w_pos):
                view3d.append(batch_for_shader(tri_shader, 'TRIS', {"pos": w_pos, "color": _tile(color, len(w_pos))}))
        for kind, seg in _data["edges"]:
            color = edge_color(kind)
            lines.append(batch_for_shader(line_shader, 'LINES', {"pos": seg, "color": _tile(color, len(seg))}))
        _batches = (uv, view3d, lines)
    return _batches


def _draw_uv():
    if _dirty:
        return
    context = bpy.context
    space = context.space_data
    if space is None or not space.show_uvedit:
        return
    batches = _get_batches()
    if batches is None:
        return
    uv, _view3d, lines = batches
    region = context.region
    x, y, w, h = common.uv_square(region)
    gpu.state.blend_set('ALPHA')
    with gpu.matrix.push_pop():
        gpu.matrix.translate((x, y))
        gpu.matrix.scale((w, h))
        tri_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        for batch in uv:
            batch.draw(tri_shader)
        if lines:
            line_shader = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
            line_shader.uniform_float("viewportSize", (region.width, region.height))
            line_shader.uniform_float("lineWidth", 2.0 * context.preferences.system.pixel_size)
            for batch in lines:
                batch.draw(line_shader)
    gpu.state.blend_set('NONE')


def _draw_3d():
    if _dirty:
        return
    batches = _get_batches()
    if batches is None or not batches[1]:
        return
    common.draw_on_surface(batches[1], gpu.shader.from_builtin('SMOOTH_COLOR'))


@bpy.app.handlers.persistent
def _depsgraph_update(_scene, _depsgraph):
    common.forget_reads()
    mark_dirty()


@bpy.app.handlers.persistent
def _load_post(*_args):
    refresh()


def refresh(_self=None, _context=None):
    """Switch the overlay on or off to match the toggles, and recompute."""
    global _data, _batches
    _remove_handlers()
    _data = None
    _batches = None
    common.forget_reads()
    wm = bpy.context.window_manager
    if wm is not None and _any_enabled(wm):
        _handles.append((bpy.types.SpaceImageEditor, bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_uv, (), 'WINDOW', 'POST_PIXEL')))
        _handles.append((bpy.types.SpaceView3D, bpy.types.SpaceView3D.draw_handler_add(
            _draw_3d, (), 'WINDOW', 'POST_VIEW')))
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)
        mark_dirty(delay=0.0)
    try:
        common.redraw_all()
    except AttributeError:
        pass


def _remove_handlers():
    for space, handle in _handles:
        space.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
    if _depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update)
    if bpy.app.timers.is_registered(_rebuild_timer):
        bpy.app.timers.unregister(_rebuild_timer)


def found(kind):
    """How many islands (faces for SELF) the overlay currently shows, or None."""
    if _data is None or _dirty:
        return None
    return _data["counts"].get(kind)


# --- Operators -----------------------------------------------------------------

class _DebugSelect:
    """The select arrow on each Debug row. One operator per kind, never one
    operator with a kind setting: CocoPies' "Add to CocoPies" (and anything
    else that takes a button's operator) keeps only the operator's name, so
    every arrow became "select done"."""
    bl_options = {'REGISTER', 'UNDO'}
    kind = 'DONE'

    extend: BoolProperty(name="Extend", description="Add to the current selection", default=False)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        sync = context.tool_settings.use_uv_select_sync
        edges = self.kind == 'EDGES'
        parts = [p for p in (common.read_mesh(o, True, sync, edges, keep_faces=True)
                             for o in common.edit_objects(context)) if p]
        if not parts:
            self.report({'WARNING'}, "No UVs to select from")
            return {'CANCELLED'}
        total = 0
        if edges:
            _prepare_edge_select_mode(context, sync)
            for part in parts:
                marks = np.zeros(int(part["counts"].sum()), dtype=bool)
                for kind in EDGE_TYPES:
                    marks |= part["loop_marks"][kind]
                total += _select_loop_edges(part, marks, sync, self.extend)
        else:
            analyze(parts, {self.kind})
            for part in parts:
                faces, shown, mask = part["faces"], part["shown"], part["masks"][self.kind]
                visible = [f for f, s in zip(faces, shown) if s]
                matched = [f for f, s, m in zip(faces, shown, mask) if s and m]
                total += len(matched)
                common.apply_face_selection(part["bm"], visible, matched, sync, self.extend)
        for part in parts:
            bmesh.update_edit_mesh(part["obj"].data, loop_triangles=False, destructive=False)
        what = "edges" if edges else "faces"
        self.report({'INFO'}, f"Selected {total} {what}")
        return {'FINISHED'}


def _prepare_edge_select_mode(context, sync):
    """Edge selections do not show in face select mode: switch to edge mode."""
    ts = context.tool_settings
    if sync:
        if tuple(ts.mesh_select_mode) == (False, False, True):
            ts.mesh_select_mode = (False, True, False)
    elif ts.uv_select_mode == 'FACE':
        ts.uv_select_mode = 'EDGE'


def _select_loop_edges(part, marks, sync, extend):
    """Select the UV edges of the loops in `marks` (visible faces only)."""
    bm, faces, shown = part["bm"], part["faces"], part["shown"]
    visible = [f for f, s in zip(faces, shown) if s]
    if sync:
        if not extend:
            for f in visible:
                f.select_set(False)
                f.uv_select_set(False)
        elif not bm.uv_select_sync_valid:
            for f in visible:
                f.uv_select_set(f.select)
    elif not extend:
        for f in visible:
            f.uv_select_set(False)
    selected = set()
    n = 0
    for f, s in zip(faces, shown):
        for loop in f.loops:
            if marks[n] and s:
                if sync:
                    loop.edge.select_set(True)
                loop.uv_select_edge_set(True)
                loop.uv_select_vert_set(True)
                loop.link_loop_next.uv_select_vert_set(True)
                selected.add(loop.edge)
            n += 1
    if sync:
        bm.uv_select_sync_valid = True
    return len(selected)


_SHIFT = ". Shift-click to add to the current selection"


class COCOUVS_OT_select_done(_DebugSelect, Operator):
    bl_idname = "cocouvs.select_done"
    bl_label = "Select Done"
    bl_description = "Select the UV islands marked as done" + _SHIFT
    kind = 'DONE'


class COCOUVS_OT_select_flipped(_DebugSelect, Operator):
    bl_idname = "cocouvs.select_flipped"
    bl_label = "Select Flipped"
    bl_description = "Select the flipped (mirrored) UV islands" + _SHIFT
    kind = 'FLIPPED'


class COCOUVS_OT_select_overlapping(_DebugSelect, Operator):
    bl_idname = "cocouvs.select_overlapping"
    bl_label = "Select Overlapping"
    bl_description = "Select the UV islands that overlap another island" + _SHIFT
    kind = 'OVERLAP'


class COCOUVS_OT_select_self_intersecting(_DebugSelect, Operator):
    bl_idname = "cocouvs.select_self_intersecting"
    bl_label = "Select Self-Intersecting"
    bl_description = "Select the faces that overlap another face of their own island" + _SHIFT
    kind = 'SELF'


class COCOUVS_OT_select_marked_edges(_DebugSelect, Operator):
    bl_idname = "cocouvs.select_marked_edges"
    bl_label = "Select Seams / Crease / Sharp / Bevel"
    bl_description = "Select the edges with a seam, crease, sharp mark or bevel weight" + _SHIFT
    kind = 'EDGES'


SELECT_CLASSES = (COCOUVS_OT_select_done, COCOUVS_OT_select_flipped, COCOUVS_OT_select_overlapping,
                  COCOUVS_OT_select_self_intersecting, COCOUVS_OT_select_marked_edges)
# kind -> the select operator the panel draws for it
SELECT_OPERATORS = {cls.kind: cls.bl_idname for cls in SELECT_CLASSES}


class _DoneMark:
    """Add Done / Remove Done: two operators for the same reason as _DebugSelect."""
    bl_options = {'REGISTER', 'UNDO'}
    add = True

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from . import texel

        add = self.add
        # Create the attribute first: adding a layer re-allocates face data.
        for obj in common.edit_objects(context):
            active = obj.data.uv_layers.active
            if add and active is not None:
                bm = bmesh.from_edit_mesh(obj.data)
                name = common.done_layer_name(active.name)
                if bm.faces.layers.bool.get(name) is None:
                    bm.faces.layers.bool.new(name)
        changed = 0
        for obj, bm, _uv, found_islands in texel.selected_islands(context):
            layer = bm.faces.layers.bool.get(common.done_layer_name(obj.data.uv_layers.active.name))
            if layer is None:
                continue
            for island, _u, _w in found_islands:
                for f in island:
                    f[layer] = add
                changed += 1
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        if not changed:
            self.report({'WARNING'}, "Select at least one UV island")
            return {'CANCELLED'}
        islands = "island" if changed == 1 else "islands"
        self.report({'INFO'}, f"{changed} {islands} {'marked done' if add else 'removed from done'}")
        return {'FINISHED'}


class COCOUVS_OT_add_done(_DoneMark, Operator):
    bl_idname = "cocouvs.add_done"
    bl_label = "Add Done"
    bl_description = "Mark the selected UV islands as done (on the active UV map)"
    add = True


class COCOUVS_OT_remove_done(_DoneMark, Operator):
    bl_idname = "cocouvs.remove_done"
    bl_label = "Remove Done"
    bl_description = "Remove the selected UV islands from done (on the active UV map)"
    add = False


classes = (*SELECT_CLASSES, COCOUVS_OT_add_done, COCOUVS_OT_remove_done)

_TOGGLES = {
    'done': "Show UV islands marked as done",
    'flipped': "Show flipped (mirrored) UV islands",
    'overlap': "Show UV islands that overlap another island",
    'self': "Show faces that overlap another face of their own island",
    'edges': "Show seams, creases, sharp edges and bevel weights in the UV Editor, "
             "in the 3D Viewport's colours",
}


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for key, description in _TOGGLES.items():
        setattr(bpy.types.WindowManager, f"cocouvs_debug_{key}",
                BoolProperty(name=key.title(), description=description, default=False, update=refresh))
    bpy.app.handlers.load_post.append(_load_post)


def unregister():
    global _data, _batches
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    _remove_handlers()
    _data = None
    _batches = None
    for key in _TOGGLES:
        delattr(bpy.types.WindowManager, f"cocouvs_debug_{key}")
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
