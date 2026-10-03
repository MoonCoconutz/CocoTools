"""Shared helpers: which meshes a command acts on, UV islands, and the texel
density maths. No Blender classes are registered here."""

import math

import bmesh
import bpy
import gpu
import numpy as np

# Display unit -> how many of that unit make one metre.
UNIT_FACTORS = {'PX_M': 1.0, 'PX_CM': 100.0, 'PX_MM': 1000.0}
UNIT_LABELS = {'PX_M': "px/m", 'PX_CM': "px/cm", 'PX_MM': "px/mm"}

# Two corners are on the same island when their UVs are this close - the same
# tolerance Blender's own island tools use (STD_UV_CONNECT_LIMIT).
UV_CONNECT_LIMIT = 0.0001
# The numpy island finder quantises UVs to this grid instead.
UV_KEY_SCALE = 1e5

# "Done" marks: a hidden boolean face attribute per UV map, saved in the .blend.
DONE_PREFIX = ".cocouvs_done."
# Seams Update: a hidden boolean edge attribute per UV map, holding the island
# borders the seams were last set from. It lives in the mesh so that it comes
# back with Ctrl+Z, like the seams and the UVs it is compared with.
SEAM_SYNC_PREFIX = ".cocouvs_seams."


def done_layer_name(uv_name):
    return DONE_PREFIX + uv_name


def seam_sync_name(uv_name):
    return SEAM_SYNC_PREFIX + uv_name


def _per_map_names(uv_name):
    return (done_layer_name(uv_name), seam_sync_name(uv_name))


def rename_uv_map(me, old, new):
    """Rename a UV map and the hidden attributes that belong to it."""
    layer = me.uv_layers.get(old)
    if layer is None:
        return
    layer.name = new
    for before, after in zip(_per_map_names(old), _per_map_names(layer.name)):
        attribute = me.attributes.get(before)
        if attribute is not None:
            attribute.name = after


def _uv_borders(bm, uv):
    """Per edge, in bm.edges order: is it an island border of `uv`? An edge is
    one where the faces on either side do not share UVs at both ends. Mesh
    boundary edges are not, as in Blender's Seams from Islands."""
    limit = UV_CONNECT_LIMIT

    def same(a, b):
        return abs(a.x - b.x) < limit and abs(a.y - b.y) < limit

    borders = []
    for edge in bm.edges:
        loops = list(edge.link_loops)
        split = False
        for other in loops[1:]:
            first = loops[0]
            # Corner UVs of the same two vertices, from each side.
            a0, a1 = first[uv].uv, first.link_loop_next[uv].uv
            if other.vert == first.vert:
                b0, b1 = other[uv].uv, other.link_loop_next[uv].uv
            else:
                b0, b1 = other.link_loop_next[uv].uv, other[uv].uv
            if not (same(a0, b0) and same(a1, b1)):
                split = True
                break
        borders.append(split)
    return borders


def _set_seams(bm, uv_name, borders, seams=True):
    """Record `borders` as the ones the seams follow, and make them the seams."""
    name = seam_sync_name(uv_name)
    layer = bm.edges.layers.bool.get(name)
    if layer is None:
        layer = bm.edges.layers.bool.new(name)
    for edge, border in zip(bm.edges, borders):
        edge[layer] = border
        if seams:
            edge.seam = border


def seams_from_uv_map(obj, uv_name):
    """Replace the mesh's seams with the island borders of `uv_name`."""
    me = obj.data
    in_edit = obj.mode == 'EDIT'
    bm = bmesh.from_edit_mesh(me) if in_edit else bmesh.new()
    if not in_edit:
        bm.from_mesh(me)
    uv = bm.loops.layers.uv.get(uv_name)
    if uv is None:
        if not in_edit:
            bm.free()
        return
    _set_seams(bm, uv_name, _uv_borders(bm, uv))
    if in_edit:
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    else:
        bm.to_mesh(me)
        bm.free()


def follow_uv_islands(obj, uv_name):
    """Seams Update in Edit Mode: replace the seams with the island borders of
    `uv_name` if those borders changed since the seams were last set from
    them. Returns whether it did.

    Borders that did not change leave the seams alone, so a seam marked by
    hand stays until the islands change (it is there to be unwrapped). A map
    seen for the first time on a mesh that has seams only has its borders
    recorded: they may be hand-made ones waiting for an unwrap. A mesh with
    no seam at all has nothing to lose and gets them straight away - the
    default cube's cross is cut along edges that were never marked."""
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    uv = bm.loops.layers.uv.get(uv_name)
    if uv is None:
        return False
    borders = _uv_borders(bm, uv)
    layer = bm.edges.layers.bool.get(seam_sync_name(uv_name))
    if layer is None:
        unmarked = not any(edge.seam for edge in bm.edges)
        _set_seams(bm, uv_name, borders, seams=unmarked)
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        return unmarked and any(borders)
    if all(edge[layer] == border for edge, border in zip(bm.edges, borders)):
        return False
    _set_seams(bm, uv_name, borders)
    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return True


def remove_done_marks(me, uv_name):
    """Remove the hidden attributes that belong to a UV map."""
    for name in _per_map_names(uv_name):
        attribute = me.attributes.get(name)
        if attribute is not None:
            me.attributes.remove(attribute)


def _editing(view_layer):
    """Mesh objects in Edit Mode. Blender keeps objects in Edit Mode only
    alongside an active one that is, so outside Edit Mode this costs nothing;
    the scan of the whole view layer runs only while editing."""
    active = view_layer.objects.active
    if active is None or active.mode != 'EDIT':
        return []
    return [o for o in view_layer.objects if o.type == 'MESH' and o.mode == 'EDIT']


def unique_meshes(objects):
    """One object per mesh data block, order kept."""
    result = []
    seen = set()
    for obj in objects:
        if obj.data not in seen:
            seen.add(obj.data)
            result.append(obj)
    return result


def target_objects(context=None):
    """Every mesh object the UV map commands act on: the active object plus
    every selected one, and anything in Edit Mode, each once, active first."""
    view_layer = (context or bpy.context).view_layer
    candidates = []
    active = view_layer.objects.active
    if active is not None:
        candidates.append(active)
    candidates.extend(view_layer.objects.selected)
    candidates.extend(_editing(view_layer))
    return list(dict.fromkeys(o for o in candidates
                              if o is not None and o.type == 'MESH' and o.data is not None))


def has_targets(context):
    """Whether target_objects() would find anything, without collecting them."""
    view_layer = context.view_layer
    active = view_layer.objects.active
    if active is not None and active.type == 'MESH':
        return True
    return any(o is not None and o.type == 'MESH' for o in view_layer.objects.selected)


def target_meshes(context=None):
    """The meshes of target_objects(). Instances sharing one mesh count once.
    The active object's mesh comes first."""
    return [obj.data for obj in unique_meshes(target_objects(context))]


def edit_objects(context=None):
    """Mesh objects in Edit Mode, one per mesh data block."""
    return unique_meshes(_editing((context or bpy.context).view_layer))


def source_objects(view_layer):
    """What the overlays show: the objects in Edit Mode if there are any,
    otherwise the visible selected meshes. One per mesh. Returns
    (objects, editing)."""
    editing = _editing(view_layer)
    objects = editing or [o for o in view_layer.objects.selected
                          if o is not None and o.type == 'MESH' and o.visible_get(view_layer=view_layer)]
    return unique_meshes(objects), bool(editing)


def ppm_to_unit(ppm, unit):
    return ppm / UNIT_FACTORS[unit]


def format_density(ppm, unit):
    value = ppm_to_unit(ppm, unit)
    return f"{value:.3f} {UNIT_LABELS[unit]}" if value < 100 else f"{value:.1f} {UNIT_LABELS[unit]}"


def uv_face_visible(face, sync):
    """Whether the UV Editor draws this face. Without sync selection it only
    shows the faces selected in the mesh."""
    return not face.hide and (sync or face.select)


def uv_face_selected(face, sync, bm):
    """Whether this face counts as selected in the UV Editor."""
    if face.hide:
        return False
    if sync:
        # Since 5.0 sync selection can hold a UV-level selection of its own;
        # it is only meaningful while the BMesh says it is valid.
        return face.uv_select if bm.uv_select_sync_valid else face.select
    return face.select and face.uv_select


def islands(faces, allowed, uv_layer):
    """Group faces into UV islands. `faces` are the seeds, `allowed` the set of
    faces an island may grow through. Faces are connected when they share a
    vertex whose UV matches on both sides - Blender's own definition."""
    used = set()
    result = []
    limit = UV_CONNECT_LIMIT
    for seed in faces:
        if seed in used:
            continue
        used.add(seed)
        island = [seed]
        stack = [seed]
        while stack:
            face = stack.pop()
            for loop in face.loops:
                uv = loop[uv_layer].uv
                for other in loop.vert.link_loops:
                    other_face = other.face
                    if other_face in used or other_face not in allowed:
                        continue
                    ouv = other[uv_layer].uv
                    if abs(ouv.x - uv.x) < limit and abs(ouv.y - uv.y) < limit:
                        used.add(other_face)
                        island.append(other_face)
                        stack.append(other_face)
        result.append(island)
    return result


def _components(counts, starts, keys, n_keys):
    """Island label per face: faces sharing a corner key (same vertex, same
    UV) end up with the same label. Min-label propagation with pointer
    jumping, all in numpy."""
    n_faces = len(counts)
    loop_face = np.repeat(np.arange(n_faces), counts)
    labels = np.arange(n_faces)
    while True:
        key_min = np.full(n_keys, n_faces, dtype=np.int64)
        np.minimum.at(key_min, keys, labels[loop_face])
        new = np.minimum(np.minimum.reduceat(key_min[keys], starts), labels)
        while True:
            jumped = new[new]
            if np.array_equal(jumped, new):
                break
            new = jumped
        if np.array_equal(new, labels):
            return labels
        labels = new


def face_islands(counts, starts, loop_vi, uv):
    """numpy island finder: island index (0..n-1) per face, from each
    corner's vertex index and UV. Corners join when they share a vertex and
    (nearly) the same UV - the key is packed into one int64 (21 bits each for
    the quantised u and v) so np.unique stays 1-D and fast. Two corners of one
    vertex only collide if their UVs differ by an exact multiple of ~21 units."""
    q = np.floor(uv * UV_KEY_SCALE).astype(np.int64) & 0x1FFFFF
    _, keys = np.unique((loop_vi.astype(np.int64) << 42) | (q[:, 0] << 21) | q[:, 1], return_inverse=True)
    keys = keys.ravel()
    _, island = np.unique(_components(counts, starts, keys, int(keys.max()) + 1), return_inverse=True)
    return island.ravel()


def apply_face_selection(bm, visible, matched_faces, sync, extend):
    """Select exactly `matched_faces` in the UV Editor (replacing the selection
    of `visible` faces unless `extend`).

    No vertex flush: in vertex select mode a flush also selects faces of
    *other* islands whose corners all sit on the seam. uv_select_set()
    flushes down to the face's own UV corners only, and UV corners are never
    shared between faces. (bm.uv_select_foreach_set() refuses to run unless
    uv_select_sync_valid is already true.)"""
    if sync:
        was_valid = bm.uv_select_sync_valid
        if not extend:
            for f in visible:
                f.select_set(False)
                f.uv_select_set(False)
        elif not was_valid:
            # Adding to a mesh-only selection: carry it over to UVs.
            for f in visible:
                f.uv_select_set(f.select)
        for f in matched_faces:
            f.select_set(True)
            f.uv_select_set(True)
        # The UV-level selection now matches the mesh one face for face.
        bm.uv_select_sync_valid = True
    else:
        if not extend:
            for f in visible:
                f.uv_select_set(False)
        for f in matched_faces:
            f.uv_select_set(True)
        bm.uv_select_flush_mode()


def world_coords(bm, matrix):
    """World-space position of every vertex, keyed by the BMVert itself, not
    by BMVert.index: setting indices (index_update) writes to the edit mesh."""
    return {v: matrix @ v.co for v in bm.verts}


def face_world_area(face, coords):
    """Area of a face in world units, from its vector area. Exact for planar
    faces, and what Blender reports for non-planar ones is no better."""
    pts = [coords[v] for v in face.verts]
    n = len(pts)
    x = y = z = 0.0
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        x += a.y * b.z - a.z * b.y
        y += a.z * b.x - a.x * b.z
        z += a.x * b.y - a.y * b.x
    return 0.5 * math.sqrt(x * x + y * y + z * z)


def face_uv_area(face, uv_layer):
    """Area of a face in UV space (the 0-1 square has area 1)."""
    uvs = [loop[uv_layer].uv for loop in face.loops]
    n = len(uvs)
    s = 0.0
    for i in range(n):
        a = uvs[i]
        b = uvs[(i + 1) % n]
        s += a.x * b.y - b.x * a.y
    return abs(s) * 0.5


def island_areas(island, uv_layer, coords):
    """(uv_area, world_area) summed over an island."""
    uv_area = 0.0
    world_area = 0.0
    for face in island:
        uv_area += face_uv_area(face, uv_layer)
        world_area += face_world_area(face, coords)
    return uv_area, world_area


def density_ppm(uv_area, world_area, texture_size, scale_length):
    """Texel density in pixels per metre. `world_area` is in Blender units
    squared; `scale_length` is the scene's metres per Blender unit."""
    world_m2 = world_area * scale_length * scale_length
    if world_m2 <= 0.0:
        return None
    return texture_size * math.sqrt(max(uv_area, 0.0) / world_m2)


def scale_island(island, uv_layer, factor):
    """Scale an island's UVs about the centre of its UV bounding box."""
    loops = [loop for face in island for loop in face.loops]
    us = [loop[uv_layer].uv.x for loop in loops]
    vs = [loop[uv_layer].uv.y for loop in loops]
    cu = (min(us) + max(us)) * 0.5
    cv = (min(vs) + max(vs)) * 0.5
    for loop in loops:
        luv = loop[uv_layer]
        uv = luv.uv
        luv.uv = (cu + (uv.x - cu) * factor, cv + (uv.y - cv) * factor)


def scale_islands_together(islands_with_layers, factor):
    """Scale several islands as one block about the centre of their combined
    UV bounding box. `islands_with_layers` is [(faces, uv_layer)], so islands
    from several objects in Edit Mode share one pivot, as they do on screen."""
    loops = [(loop, uv_layer) for island, uv_layer in islands_with_layers
             for face in island for loop in face.loops]
    if not loops:
        return
    us = [loop[uv_layer].uv.x for loop, uv_layer in loops]
    vs = [loop[uv_layer].uv.y for loop, uv_layer in loops]
    cu = (min(us) + max(us)) * 0.5
    cv = (min(vs) + max(vs)) * 0.5
    for loop, uv_layer in loops:
        luv = loop[uv_layer]
        uv = luv.uv
        luv.uv = (cu + (uv.x - cu) * factor, cv + (uv.y - cv) * factor)


# --- Reading a mesh for the overlays (read-only) ------------------------------
# The heatmap and the Debug overlays both need every visible face's corners,
# UVs, islands and world positions. Their timers fire together after an edit,
# so one read is cached until the next depsgraph update (forget_reads()).

EDGE_TYPES = ('BEVEL', 'CREASE', 'SHARP', 'SEAM')

_reads = {}


def forget_reads():
    _reads.clear()


def read_mesh(obj, editing, sync, want_edges=False, keep_faces=False):
    """One object's visible faces as numpy arrays, or None. Only reads the
    mesh: in Edit Mode this may run mid-transform, so vertices and edges are
    identified by hash() (their address), never by .index. With keep_faces
    (Edit Mode only, never cached) the BMFaces and the BMesh are kept too,
    for selecting."""
    if keep_faces:
        return _read_mesh(obj, editing, sync, want_edges, True)
    key = (obj.as_pointer(), editing, sync)
    cached = _reads.get(key, False)
    if cached is False or (want_edges and cached is not None and "loop_marks" not in cached):
        cached = _reads[key] = _read_mesh(obj, editing, sync, want_edges, False)
    return cached


def _read_mesh(obj, editing, sync, want_edges, keep_faces):
    me = obj.data
    bm = bmesh.from_edit_mesh(me) if editing else bmesh.new()
    if not editing:
        bm.from_mesh(me)
    try:
        uv_layer = bm.loops.layers.uv.active
        active = me.uv_layers.active
        if uv_layer is None or active is None:
            return None
        faces = [f for f in bm.faces if not f.hide]
        if not faces:
            return None
        done_layer = bm.faces.layers.bool.get(done_layer_name(active.name))
        part = {
            "obj": obj,
            "counts": np.array([len(f.loops) for f in faces], dtype=np.int64),
            "shown": np.array([sync or f.select for f in faces], dtype=bool) if editing
            else np.zeros(len(faces), dtype=bool),
            "done": np.array([f[done_layer] for f in faces], dtype=bool) if done_layer is not None
            else np.zeros(len(faces), dtype=bool),
            "uv": np.array([loop[uv_layer].uv[:] for f in faces for loop in f.loops], dtype=np.float64),
        }
        loop_vert = np.array([hash(loop.vert) for f in faces for loop in f.loops], dtype=np.int64)
        verts = bm.verts
        vert_hash = np.array([hash(v) for v in verts], dtype=np.int64)
        vert_co = np.array([v.co[:] for v in verts], dtype=np.float64)
        if want_edges:
            loop_edge = np.array([hash(loop.edge) for f in faces for loop in f.loops], dtype=np.int64)
            edges = bm.edges
            edge_hash = np.array([hash(e) for e in edges], dtype=np.int64)
            crease = bm.edges.layers.float.get("crease_edge")
            bevel = bm.edges.layers.float.get("bevel_weight_edge")
            none = np.zeros(len(edges), dtype=bool)
            flags = {
                'SEAM': np.array([e.seam for e in edges], dtype=bool),
                'SHARP': np.array([not e.smooth for e in edges], dtype=bool),
                'CREASE': np.array([e[crease] > 0.0 for e in edges], dtype=bool) if crease is not None else none,
                'BEVEL': np.array([e[bevel] > 0.0 for e in edges], dtype=bool) if bevel is not None else none,
            }
        if keep_faces:
            part["faces"] = faces
            part["bm"] = bm
    finally:
        if not editing:
            bm.free()

    order = np.argsort(vert_hash)
    loop_vi = order[np.searchsorted(vert_hash[order], loop_vert)]
    counts = part["counts"]
    starts = np.zeros(len(counts), dtype=np.int64)
    starts[1:] = np.cumsum(counts)[:-1]
    part["starts"] = starts
    part["island"] = face_islands(counts, starts, loop_vi, part["uv"])
    mw = np.array(obj.matrix_world, dtype=np.float64)
    part["world"] = (vert_co @ mw[:3, :3].T + mw[:3, 3])[loop_vi]

    # Fan triangles (first corner, k, k+1), per face - read-only, unlike
    # calc_loop_triangles().
    n_tris = counts - 2
    tri_face = np.repeat(np.arange(len(counts)), n_tris)
    k = np.arange(len(tri_face)) - np.repeat(np.cumsum(n_tris) - n_tris, n_tris) + 1
    a = starts[tri_face]
    part["tri_face"] = tri_face
    part["corners"] = np.stack([a, a + k, a + k + 1], axis=1)

    if want_edges:
        order = np.argsort(edge_hash)
        loop_ei = order[np.searchsorted(edge_hash[order], loop_edge)]
        part["loop_marks"] = {kind: flags[kind][loop_ei] for kind in EDGE_TYPES}
    return part


def draw_on_surface(batches, shader):
    """Draw 3D Viewport overlay batches over the surface, pulled a hair
    towards the camera so they do not z-fight with it (what Blender's own
    overlays do)."""
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    with gpu.matrix.push_pop_projection():
        proj = gpu.matrix.get_projection_matrix().copy()
        if proj[3][3] == 0.0:           # perspective
            proj[2][3] *= 1.0 + 1e-4
        else:                            # orthographic
            proj[2][3] -= 1e-5
        gpu.matrix.load_projection_matrix(proj)
        for batch in batches:
            batch.draw(shader)
    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def uv_square(region):
    """(x, y, width, height): where the UV 0-1 square lands in the region."""
    x0, y0 = region.view2d.view_to_region(0.0, 0.0, clip=False)
    x1, y1 = region.view2d.view_to_region(1.0, 1.0, clip=False)
    return x0, y0, x1 - x0, y1 - y0


def redraw_all(context=None):
    context = context or bpy.context
    wm = context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()
