"""Shared helpers: which meshes a command acts on, UV islands, and the texel
density maths. No Blender classes are registered here."""

import math

import bpy
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


def done_layer_name(uv_name):
    return DONE_PREFIX + uv_name


def rename_uv_map(me, old, new):
    """Rename a UV map and the Done marks that belong to it."""
    layer = me.uv_layers.get(old)
    if layer is None:
        return
    layer.name = new
    done = me.attributes.get(done_layer_name(old))
    if done is not None:
        done.name = done_layer_name(layer.name)


def seams_from_uv_map(obj, uv_name):
    """Replace the mesh's seams with the island borders of `uv_name`: an edge
    is a seam where the faces on either side do not share UVs at both ends.
    Mesh boundary edges are left unmarked, as Blender's Seams from Islands."""
    import bmesh

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
    limit = UV_CONNECT_LIMIT

    def same(a, b):
        return abs(a.x - b.x) < limit and abs(a.y - b.y) < limit

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
        edge.seam = split
    if in_edit:
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    else:
        bm.to_mesh(me)
        bm.free()


def remove_done_marks(me, uv_name):
    done = me.attributes.get(done_layer_name(uv_name))
    if done is not None:
        me.attributes.remove(done)


def target_objects(context=None):
    """Every mesh object the UV map commands act on: the active object plus
    every selected one, and anything in Edit Mode, each once, active first."""
    context = context or bpy.context
    view_layer = context.view_layer
    candidates = []
    active = view_layer.objects.active
    if active is not None:
        candidates.append(active)
    candidates.extend(view_layer.objects.selected)
    candidates.extend(o for o in view_layer.objects if o.mode == 'EDIT')

    objects = []
    seen = set()
    for obj in candidates:
        if obj.type != 'MESH' or obj.data is None or obj.as_pointer() in seen:
            continue
        seen.add(obj.as_pointer())
        objects.append(obj)
    return objects


def target_meshes(context=None):
    """The meshes of target_objects(). Instances sharing one mesh count once.
    The active object's mesh comes first."""
    meshes = []
    seen = set()
    for obj in target_objects(context):
        key = obj.data.as_pointer()
        if key not in seen:
            seen.add(key)
            meshes.append(obj.data)
    return meshes


def edit_objects(context=None):
    """Mesh objects in Edit Mode, one per mesh data block."""
    context = context or bpy.context
    result = []
    seen = set()
    for obj in context.view_layer.objects:
        if obj.type != 'MESH' or obj.mode != 'EDIT':
            continue
        key = obj.data.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        result.append(obj)
    return result


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
    """World-space position of every vertex, keyed by the BMVert itself.

    Never key by BMVert.index: setting indices (index_update) writes to the
    edit mesh, and the heatmap runs this from a draw callback while a
    transform is in progress - the transform relies on those indices, and
    renumbering them mid-drag scrambled the UVs and crashed Blender."""
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


def redraw_all(context=None):
    context = context or bpy.context
    wm = context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()
