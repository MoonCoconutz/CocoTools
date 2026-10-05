"""Unfold Along U / V: Maya's UV Toolkit buttons of the same name.

Maya runs its Unfold with one direction locked (`unfold -oa`): every UV keeps
its V (or U) and only the other coordinate moves, to make the faces as
undistorted as they can be with that one locked. Unselected UVs of an island
stay pinned, so only the selection moves; Blender's own UV pins count too.

The solve is As-Rigid-As-Possible with the locked coordinate fixed: each
triangle wants its UV shape to be its world-space shape, turned and scaled.
The scale is solved per island along with the free coordinate, so it comes
out matching the scale the locked one already has (square texels)."""

import bmesh
import bpy
import numpy as np
from bpy.props import IntProperty
from bpy.types import Operator

from . import common

MIN_AREA = 1e-12     # world-space triangles smaller than this are skipped
CG_STEPS = 300       # cap on conjugate-gradient steps per iteration
CG_TOLERANCE = 1e-8  # relative to the largest right-hand side entry


def _read(obj, sync, axis):
    """What the solver needs from one mesh in Edit Mode, or None when none of
    its UVs are selected. `axis` 0 frees U, 1 frees V."""
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        return None
    faces = [f for f in bm.faces if common.uv_face_visible(f, sync)]
    if not faces:
        return None
    bm.verts.index_update()
    loops = [loop for f in faces for loop in f.loops]
    counts = np.array([len(f.loops) for f in faces])
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    uv = np.array([loop[uv_layer].uv[:] for loop in loops])
    vi = np.array([loop.vert.index for loop in loops], dtype=np.int64)
    # With sync selection the UV-level flags only count while valid.
    if not sync or bm.uv_select_sync_valid:
        sel = np.array([loop.uv_select_vert for loop in loops])
    else:
        sel = np.array([loop.vert.select for loop in loops])
    pin = np.array([loop[uv_layer].pin_uv for loop in loops])

    # A UV vertex is one mesh vertex at one UV position.
    q = np.floor(uv * common.UV_KEY_SCALE).astype(np.int64) & 0x1FFFFF
    _, key = np.unique((vi << 42) | (q[:, 0] << 21) | q[:, 1], return_inverse=True)
    key = key.ravel()
    n = int(key.max()) + 1
    face_island = common._components(counts, starts, key, n)
    island = np.empty(n, dtype=np.int64)
    island[key] = np.repeat(face_island, counts)
    _, island = np.unique(island, return_inverse=True)
    island = island.ravel()

    vsel = np.zeros(n, bool)
    np.logical_or.at(vsel, key, sel)
    vpin = np.zeros(n, bool)
    np.logical_or.at(vpin, key, pin)
    active = np.zeros(int(island.max()) + 1, bool)
    active[island[vsel]] = True
    if not active.any():
        return None

    position = {loop: i for i, loop in enumerate(loops)}
    tri, co = [], []
    mw = obj.matrix_world
    for corners in bm.calc_loop_triangles():
        idx = [position.get(loop) for loop in corners]
        if idx[0] is None or not active[island[key[idx[0]]]]:
            continue
        tri.append([key[i] for i in idx])
        co.append([(mw @ loop.vert.co)[:] for loop in corners])
    if not tri:
        return None

    free = np.zeros(n)
    fixed = np.zeros(n)
    free[key] = uv[:, axis]
    fixed[key] = uv[:, 1 - axis]
    return dict(bm=bm, uv_layer=uv_layer, loops=loops, key=key, island=island,
                movable=vsel & ~vpin, free=free, fixed=fixed,
                tri=np.array(tri), co=np.array(co, dtype=np.float64))


def _flat_triangles(co):
    """Each world-space triangle laid flat in its own plane, counter-clockwise."""
    e1 = co[:, 1] - co[:, 0]
    e2 = co[:, 2] - co[:, 0]
    normal = np.cross(e1, e2)
    l1 = np.linalg.norm(e1, axis=1)
    ln = np.linalg.norm(normal, axis=1)
    ok = (l1 > 0) & (ln > 0)
    l1[~ok] = 1
    ln[~ok] = 1
    x = e1 / l1[:, None]
    y = np.cross(normal / ln[:, None], x)
    flat = np.zeros((len(co), 3, 2))
    flat[:, 1, 0] = l1
    flat[:, 2, 0] = (e2 * x).sum(1)
    flat[:, 2, 1] = (e2 * y).sum(1)
    return flat, ok


def solve(tri, co, start, fixed, movable, vert_island, iterations):
    """The free coordinate per UV vertex, with `fixed` locked. In the maths
    below the free coordinate is called u and the locked one v."""
    n = len(start)
    flat, ok = _flat_triangles(co)
    tri_island = vert_island[tri[:, 0]]
    n_islands = int(vert_island.max()) + 1

    # An island laid out mirrored (negative UV area) is solved against
    # mirrored triangles, so the result keeps its orientation.
    du1 = start[tri[:, 1]] - start[tri[:, 0]]
    dv1 = fixed[tri[:, 1]] - fixed[tri[:, 0]]
    du2 = start[tri[:, 2]] - start[tri[:, 0]]
    dv2 = fixed[tri[:, 2]] - fixed[tri[:, 0]]
    signed = du1 * dv2 - du2 * dv1
    mirrored = np.bincount(tri_island, weights=signed, minlength=n_islands) < 0
    flat[mirrored[tri_island], :, 1] *= -1

    # Gradient operator per triangle: grad f = sum_k f_k * C[:, k].
    D = np.stack([flat[:, 1] - flat[:, 0], flat[:, 2] - flat[:, 0]], axis=2)
    det = D[:, 0, 0] * D[:, 1, 1] - D[:, 0, 1] * D[:, 1, 0]
    area = 0.5 * np.abs(det)
    ok &= area > MIN_AREA
    tri, D, det, area, tri_island = tri[ok], D[ok], det[ok], area[ok], tri_island[ok]
    if not len(tri):
        return start.copy()
    C = np.empty((len(tri), 3, 2))
    C[:, 1, 0] = D[:, 1, 1] / det           # rows of D^-1, i.e. columns of D^-T
    C[:, 1, 1] = -D[:, 0, 1] / det
    C[:, 2, 0] = -D[:, 1, 0] / det
    C[:, 2, 1] = D[:, 0, 0] / det
    C[:, 0] = -(C[:, 1] + C[:, 2])

    def grad(f):
        return np.einsum("tk,tkd->td", f[tri], C)

    def scatter(w):                         # sum_t C_t^T w_t
        return np.bincount(tri.ravel(), weights=np.einsum("tkd,td->tk", C, w).ravel(), minlength=n)

    # sum_t A_t C_t C_t^T (the cotangent Laplacian) as one coalesced sparse
    # list, so each product is a single bincount.
    K = area[:, None, None] * np.einsum("tid,tjd->tij", C, C)
    rows = np.repeat(tri, 3, axis=1).ravel()
    cols = np.tile(tri, (1, 3)).ravel()
    pairs, inverse = np.unique(rows * n + cols, return_inverse=True)
    values = np.bincount(inverse.ravel(), weights=K.ravel())
    L_rows, L_cols = pairs // n, pairs % n

    def apply_L(f):
        return np.bincount(L_rows, weights=values * f[L_cols], minlength=n)

    on_diag = L_rows == L_cols
    diag = np.bincount(L_rows[on_diag], weights=values[on_diag], minlength=n)
    solving = movable & (diag > 0)
    inv_diag = np.where(solving, 1.0 / np.where(diag > 0, diag, 1.0), 0.0)

    # An island with nothing pinned starts from u = 0: the first turn of each
    # triangle then comes from v alone, which unrolls a projection cleanly.
    pinned = np.zeros(n_islands, bool)
    np.logical_or.at(pinned, vert_island, ~movable)
    floating = ~pinned[vert_island]
    u = start.copy()
    u[floating] = 0.0

    gv = grad(fixed)
    island_area = np.bincount(tri_island, weights=area, minlength=n_islands)
    island_area[island_area == 0] = 1
    scale = np.bincount(tri_island, weights=area * np.linalg.norm(gv, axis=1),
                        minlength=n_islands) / island_area

    for step in range(iterations):
        gu = grad(u)
        a, b = gu[:, 0], gu[:, 1]
        c, d = gv[:, 0], gv[:, 1]
        theta = np.arctan2(c - b, a + d)    # the rotation closest to [gu; gv]
        cos, sin = np.cos(theta), np.sin(theta)
        if step:                            # the scale u and v agree on
            trace = a * cos - b * sin + c * sin + d * cos
            scale = np.bincount(tri_island, weights=area * trace, minlength=n_islands) / (2 * island_area)
        s = scale[tri_island]
        rhs = scatter(area[:, None] * np.stack([s * cos, -s * sin], 1))

        # Conjugate gradients over the movable UVs, from the last answer.
        r = np.where(solving, rhs - apply_L(u), 0.0)
        z = r * inv_diag
        p = z.copy()
        rz = r @ z
        tolerance = CG_TOLERANCE * max(np.abs(rhs).max(), 1e-12)
        for _ in range(CG_STEPS):
            if np.abs(r).max() < tolerance:
                break
            Ap = np.where(solving, apply_L(p), 0.0)
            alpha = rz / max(p @ Ap, 1e-300)
            u += alpha * p
            r -= alpha * Ap
            z = r * inv_diag
            rz_next = r @ z
            p = z + (rz_next / max(rz, 1e-300)) * p
            rz = rz_next

    # A floating island keeps its centre along the free axis.
    count = np.bincount(vert_island, minlength=n_islands).astype(float)
    count[count == 0] = 1
    shift = (np.bincount(vert_island, weights=start, minlength=n_islands)
             - np.bincount(vert_island, weights=u, minlength=n_islands)) / count
    u[floating] += shift[vert_island][floating]
    return u


class _UnfoldAlong:
    """Unfold Along U and V: one operator per axis (see _TrimFit)."""
    bl_options = {'REGISTER', 'UNDO'}
    axis = 0

    iterations: IntProperty(name="Iterations", default=60, min=1, max=1000,
                            description="More iterations relax long or curved islands further")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        sync = context.tool_settings.use_uv_select_sync
        done = False
        for obj in common.edit_objects(context):
            data = _read(obj, sync, self.axis)
            if data is None:
                continue
            result = solve(data["tri"], data["co"], data["free"], data["fixed"],
                           data["movable"], data["island"], self.iterations)
            uv_layer, movable, axis = data["uv_layer"], data["movable"], self.axis
            for loop, k in zip(data["loops"], data["key"]):
                if movable[k]:
                    loop[uv_layer].uv[axis] = result[k]
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            done = True
        if not done:
            self.report({'WARNING'}, "Select some UVs to unfold")
            return {'CANCELLED'}
        return {'FINISHED'}


class COCOUVS_OT_unfold_along_u(_UnfoldAlong, Operator):
    """Unfold the selected UVs sideways only: V stays, U relaxes to take out
    the stretching. Unselected and pinned UVs of an island stay put"""
    bl_idname = "cocouvs.unfold_along_u"
    bl_label = "Unfold Along U"
    axis = 0


class COCOUVS_OT_unfold_along_v(_UnfoldAlong, Operator):
    """Unfold the selected UVs up and down only: U stays, V relaxes to take
    out the stretching. Unselected and pinned UVs of an island stay put"""
    bl_idname = "cocouvs.unfold_along_v"
    bl_label = "Unfold Along V"
    axis = 1


classes = (COCOUVS_OT_unfold_along_u, COCOUVS_OT_unfold_along_v)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
