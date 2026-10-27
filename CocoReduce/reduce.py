"""The reduction itself, on meshes only (no operators, no UI).

Every vertex of a LOD is a vertex of the original: the reduction only ever
merges a vertex into one of its neighbours (a half-edge collapse), never
moves one. That keeps UVs, colours and normals exact at every vertex left.

1. Feature lines are found: UV seams (an edge whose two sides have
   different UVs in any UV map), edges marked sharp, open borders, material
   borders and, in Hard Surface mode, edges bent past the Sharp Angle.
2. Each corner gets two normals that ride along with merges: the shading
   normal (NORMAL, the original's own) and the shape normal (SHAPE, the mean
   face normal on its side of the creases).
3. Merges are taken in order of how far they move the surface, in metres:
   the farthest the target lies from the merged vertex's face planes, its
   error quadric (Garland & Heckbert) and its line in UV. A vertex on a
   feature line may only merge along its line; where lines meet, or a line
   turns a corner, it never merges. In quads a whole edge ring merges at
   once. Whole small loose parts wait in the same queue, at how far
   deleting them would move the surface.
4. A merge that would break something is refused, never merely made dear:
   a round line or surface losing more than half its points (more at sizes
   below 50%), shading that drifts from the original's, a part moving by
   more than PART_DEVIATION of its size, a UV island lost, a face folded in
   3D or UV, two faces closing onto each other.
5. Each round welds many merges at once (an operator call costs as much as
   the whole mesh): the cheapest ones whose face rings do not touch.
6. Triangles join back into quads where nearly flat, and in Hard Surface
   mode evenly shaded flat areas become n-gons.

If nothing more may go, the LOD stays above the Size: on a game asset full
of seams, hard edges and round parts that can be far above it.

Blender's Collapse is not used: protecting the lines with a vertex group
wrecked its order on a real asset where most vertices sit on a line (a
locomotive, 2026-10-10), and it moves vertices, which made copied normals
guess.
"""

import math

import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils.geometry import (barycentric_transform, closest_point_on_tri,
                                intersect_point_line, normal, tessellate_polygon)

FEATURE = "_coco_reduce_feature"
ORIG = "_coco_reduce_orig"
NORMAL = "_coco_reduce_normal"
SHAPE = "_coco_reduce_shape"
REGION = "_coco_reduce_region"

# Feature kinds, as bits of FEATURE. A UV split has one bit per UV map,
# UV_SPLIT << map index, so a line only continues within the same maps.
BORDER = 1
SHARP = 2
ANGLE = 4
MATERIAL = 8
UV_SPLIT = 16

# How hard a feature line resists bending, against the surface around it.
LINE_WEIGHT = 100.0

# Round things lose sides in step with the Size, by a scale of 1 / ratio but
# never less than 2. Where a line bends, each vertex left may stand for at
# most that many vertices of the original: down to 50% a circle keeps half
# its sides. Where the original's shape normals were some angle apart in a
# face, a merge may leave at most that angle times the scale. Never past
# ROUND_ANGLE (a circle keeps 8 sides or more); a line that stays within
# ROUND_FREE of straight is not round. A line turning more than ROUND_ANGLE
# at a vertex is a corner and never merges.
ROUND_ANGLE = math.radians(45.0)
ROUND_FREE = math.radians(5.0)
_COS_FREE = math.cos(ROUND_FREE)
_COS_ROUND = math.cos(ROUND_ANGLE)
# A round part loses every other side only if it bends at most this much at
# each (a 16-sided tube's 22.5 degrees), so that halved it stays within
# ROUND_ANGLE; a little more for sides not quite even.
_COS_HALF = math.cos(ROUND_ANGLE / 2 + math.radians(1.0))
# The fewest sides a round part keeps, by default (ROUND_ANGLE). Asked for
# fewer, the round limits widen to match (_Run.round_angle); corners stay
# where they were (a line turning past ROUND_ANGLE in the original).
MIN_SIDES = 8
# So the limits on round lines and faces allow that much more: a 16-sided
# pipe whose sides bend 22 to 23 degrees, halved, bends up to 46 (a
# pipeline, 2026-10-15).
ROUND_SLACK = math.radians(2.0)
_COS_ROUND_SLACK = math.cos(ROUND_ANGLE + ROUND_SLACK)

# The faces a merge leaves must shade as the original did, within this angle:
# where the merged vertex was, and in the middle of each of their triangles
# (against the original's normals there). Merging a support loop into the
# flat face beside it, or a bevel's corner across a large face, smears
# shading over the whole face.
SHADING_ANGLE = math.radians(10.0)
_COS_SHADING = math.cos(SHADING_ANGLE)

# Deleting a whole loose part counts as moving the surface by PART_SHARE of
# its size (about its radius, which is what meshoptimizer's prune compares
# with the error), so smaller parts always go first. Only parts up to
# part_size of the whole mesh's size (PART_SIZE unless asked otherwise) ever
# go. Ordered by how far each stood off the rest instead, which parts went
# looked random (2026-10-15).
PART_SHARE = 0.5
PART_SIZE = 0.02

# Copies of a part (same triangles, area and size within this share) go
# together or not at all.
KIND_TOLERANCE = 0.02

# No merge may move a loose part's surface by more than this share of the
# part's own size: a part keeps its shape or keeps its triangles (and, if
# small, may go whole). Measured as the farthest the target lies from the
# planes of the merged vertex's faces, and from its quadric.
PART_DEVIATION = 0.05

# A round part losing every other side keeps its shape and only bends more
# between its sides, so its halving counts as this share of how far it moves
# the surface, as a part's removal counts half its size. Counted in full, a
# pipe's 16 sides (2.6 cm) waited behind its bolts (1.8 cm) and the bolts
# went instead (a pipeline, 2026-10-15); my hand-made LODs halve the pipe
# and keep the bolts.
HALVE_SHARE = 0.5

# No merge may move the surface by more than this share of how far behind
# it the next surface facing it is: a cab roof is a plate 5 mm thick, and
# its curved edge flattened by 1 cm let the underside show through in dark
# streaks (a locomotive, 2026-10-26).
THIN_SHARE = 0.5

# An open border within this of another part's open border meets it, and
# moves at most THIN_SHARE of it (a part merely standing on another, like a
# stack on a hood, opens no crack): a cab roof's flat top and curved front strip
# are two parts edge to edge, and flattening the strip's edge opened a dark
# crack between them (a locomotive, 2026-10-26).
JOIN_GAP = 0.002

# Triangles left by the merges join back into quads only when they lie
# within this angle of each other.
JOIN_ANGLE = math.radians(10.0)

_UV_EPS = 1e-5


def tri_count(mesh_or_bm):
    if isinstance(mesh_or_bm, bmesh.types.BMesh):
        return sum(len(f.verts) - 2 for f in mesh_or_bm.faces)
    return sum(p.loop_total - 2 for p in mesh_or_bm.polygons)


def _loop_at(face, vert):
    for loop in face.loops:
        if loop.vert is vert:
            return loop
    return None


def _uv_splits(edge, uv_layers):
    """The UV_SPLIT bits of the maps whose UVs differ across edge."""
    l1, l2 = edge.link_loops
    if l2.vert is l1.vert:
        pairs = ((l1, l2), (l1.link_loop_next, l2.link_loop_next))
    else:
        pairs = ((l1, l2.link_loop_next), (l1.link_loop_next, l2))
    bits = 0
    for i, uv in enumerate(uv_layers):
        for a, b in pairs:
            if (a[uv].uv - b[uv].uv).length_squared > _UV_EPS * _UV_EPS:
                bits |= UV_SPLIT << i
                break
    return bits


def mark_features(bm, sharp_angle):
    """Store each edge's feature kinds in the FEATURE layer; return the layer."""
    layer = bm.edges.layers.int.get(FEATURE) or bm.edges.layers.int.new(FEATURE)
    uv_layers = bm.loops.layers.uv.values()
    for e in bm.edges:
        faces = e.link_faces
        kind = 0
        if len(faces) != 2:
            kind |= BORDER
        else:
            if faces[0].material_index != faces[1].material_index:
                kind |= MATERIAL
            kind |= _uv_splits(e, uv_layers)
            if sharp_angle is not None and e.calc_face_angle(0.0) > sharp_angle:
                kind |= ANGLE
        if not e.smooth:
            kind |= SHARP
        e[layer] = kind
    return layer


def _same_line(k1, k2):
    """Two feature edges continue the same line: same kinds, sharp and angle as one."""
    def fold(k):
        return (k & ~ANGLE) | (SHARP if k & (SHARP | ANGLE) else 0)
    return fold(k1) == fold(k2)


def _seg_dist(p, a, b):
    if (b - a).length_squared < 1e-30:
        return (p - a).length
    q, t = intersect_point_line(p, a, b)
    t = min(max(t, 0.0), 1.0)
    return (p - a.lerp(b, t)).length


def _uv_area(uvs):
    s = 0.0
    for i, a in enumerate(uvs):
        b = uvs[(i + 1) % len(uvs)]
        s += a.x * b.y - b.x * a.y
    return s * 0.5


def _cos_turn(p, q, r):
    """Cosine of how far a line p -> q -> r turns at q (1 = straight on)."""
    u, w = q - p, r - q
    lu, lw = u.length, w.length
    if lu < 1e-12 or lw < 1e-12:
        return 1.0
    return u.dot(w) / (lu * lw)


def _triangles(cos):
    """A face's corners as triangles (index triples). A fan from the first
    corner folds over itself on a face that is not convex: a pipe's end cap
    made as one n-gon round a smaller pipe gave triangles facing backwards,
    and every merge on its rim looked like a 180 degree change in shading (a
    pipe rack, 2026-10-26)."""
    if len(cos) == 3:
        return ((0, 1, 2),)
    if len(cos) == 4:
        return ((0, 1, 2), (0, 2, 3)) if (cos[0] - cos[2]).length_squared <= (cos[1] - cos[3]).length_squared             else ((0, 1, 3), (1, 2, 3))
    return tessellate_polygon([cos])


def _blended(p, faces):
    """The normal faces give at the point nearest to p: faces are
    (corner positions, corner normals), each split as a fan of triangles."""
    best = None
    for cos, nrms in faces:
        for i, j, k in _triangles(cos):
            tri = (cos[i], cos[j], cos[k])
            q = closest_point_on_tri(p, *tri)
            d = (q - p).length_squared
            if best is None or d < best[0]:
                best = (d, q, tri, (nrms[i], nrms[j], nrms[k]))
    if best is None:
        return None
    _, q, tri, ns = best
    if normal(tri).length_squared < 1e-20:
        return None
    n = barycentric_transform(q, *tri, *ns)
    return n.normalized() if n.length_squared > 1e-12 else None


def _shades_alike(p, n_p, faces):
    """The faces left shade p within SHADING_ANGLE of n_p."""
    n = _blended(p, faces)
    return n is None or n.dot(n_p) >= _COS_SHADING


def _shades_like_original(run, pid, faces, why=None):
    """faces (corner positions, corner normals) shade the middle of each of
    their triangles within SHADING_ANGLE of how part pid of the original did
    there. Checked only where the merged vertex was, small changes added up:
    a fuel tank's end lost its inner points one by one until one corner's
    normal, bent 46 degrees to round the edge beside it, shaded the whole
    0.9 m2 end (a locomotive, 2026-10-10)."""
    for cos, nrms in faces:
        facing = normal(cos)  # the whole face's, whichever way a triangle turns
        for i, j, k in _triangles(cos):
            a, b, c = cos[i], cos[j], cos[k]
            fn = facing if facing.length_squared > 1e-20 else normal((a, b, c))
            if fn.length_squared < 1e-20:
                continue
            n_new = nrms[i] + nrms[j] + nrms[k]
            if n_new.length_squared < 1e-12:
                continue
            n_old = run.original_normal(pid, (a + b + c) / 3, fn)
            if n_old is not None and n_new.normalized().dot(n_old) < _COS_SHADING:
                if why is not None:
                    why.append(("off by", round(math.degrees(n_new.angle(n_old)), 1),
                                "at", tuple(round(x, 3) for x in (a + b + c) / 3), "corners", len(cos),
                                "n_old", tuple(round(x, 2) for x in n_old), "fn", tuple(round(x, 2) for x in fn),
                                "nrms", [tuple(round(x, 2) for x in n) for n in nrms]))
                return False
    return True


def _min_dot(normals):
    """The cosine of the widest angle between two of normals."""
    worst = 1.0
    for i, a in enumerate(normals):
        for b in normals[i + 1:]:
            worst = min(worst, a.dot(b))
    return worst


# --- Error quadrics ----------------------------------------------------------


def _plane(n, p, w):
    """The quadric of the plane through p with unit normal n, weighted by w,
    as the 10 entries of a symmetric 4x4 matrix, then the weight itself (so
    a summed quadric knows how many planes it holds)."""
    a, b, c = n
    d = -(a * p[0] + b * p[1] + c * p[2])
    return [w * a * a, w * a * b, w * a * c, w * a * d, w * b * b,
            w * b * c, w * b * d, w * c * c, w * c * d, w * d * d, w]


def _add(q, r):
    for i in range(11):
        q[i] += r[i]


def _error(q, r, p):
    """(q + r) evaluated at p: the summed squared distances to their planes."""
    x, y, z = p
    s = [q[i] + r[i] for i in range(10)]
    return (s[0] * x * x + 2 * s[1] * x * y + 2 * s[2] * x * z + 2 * s[3] * x
            + s[4] * y * y + 2 * s[5] * y * z + 2 * s[6] * y
            + s[7] * z * z + 2 * s[8] * z + s[9])


def quadrics(bm, layer, orig):
    """Each vertex's quadric, keyed by its ORIG id: the planes of its faces,
    and along each feature line the planes through the line square to its
    faces (times LINE_WEIGHT), which keep the line from bending. Not weighted
    by size: a centimetre is a centimetre on a bolt or on a panel. Weighted
    by area, small parts went first and lost their shape (a locomotive's
    strips and plates, up to 67 cm off, 2026-10-10)."""
    bm.normal_update()
    q = {v[orig]: [0.0] * 11 for v in bm.verts}
    for f in bm.faces:
        if f.normal.length_squared < 0.5:
            continue
        p = _plane(f.normal, f.verts[0].co, 1.0)
        for v in f.verts:
            _add(q[v[orig]], p)
    for e in bm.edges:
        if not e[layer]:
            continue
        a, b = e.verts
        d = b.co - a.co
        w = LINE_WEIGHT
        for f in e.link_faces:
            n = d.cross(f.normal)
            if n.length_squared < 1e-20:
                continue
            n.normalize()
            p = _plane(n, a.co, w)
            _add(q[a[orig]], p)
            _add(q[b[orig]], p)
    return q


# --- Merging one vertex into a neighbour ---------------------------------------


def _walk(vert, edge, face, stop):
    """Faces around vert from face (next to edge) to the face next to stop."""
    fan = [face]
    for _ in range(len(vert.link_faces) + 1):
        loop = _loop_at(face, vert)
        edge = loop.link_loop_prev.edge if loop.edge is edge else loop.edge
        if edge is stop:
            return fan
        others = [f for f in edge.link_faces if f is not face]
        if len(others) != 1:
            return None
        face = others[0]
        fan.append(face)
    return None


def _sides(vert, ea, eb):
    """The fans of faces around vert between line edges ea and eb, one per
    side, each running from the face on ea to the face on eb. None unless
    vert is a plain fan cut in two (or one, on a border) by the line."""
    sides = []
    for face in ea.link_faces:
        fan = _walk(vert, ea, face, eb)
        if fan is None:
            return None
        sides.append(fan)
    if sum(len(s) for s in sides) != len(vert.link_faces):
        return None
    return sides


def _line(vert, layer):
    return [e for e in vert.link_edges if e[layer]]


def _options(vert, layer):
    """The edges vert may be merged along: any edge for a vertex off the
    lines (a plain closed fan), its two line edges for a vertex in the middle
    of a line, none where lines meet or end."""
    line = _line(vert, layer)
    if not line:
        if not vert.link_faces or len(vert.link_faces) != len(vert.link_edges):
            return ()
        return tuple(vert.link_edges)
    if (len(line) == 2 and _same_line(line[0][layer], line[1][layer])
            and line[0].other_vert(vert) is not line[1].other_vert(vert)):
        return tuple(line)
    return ()


def _line_next(vert, edge, layer):
    """The vertex after vert along edge's line, away from edge; None where
    the line ends or meets another."""
    others = [e for e in vert.link_edges if e is not edge and e[layer]]
    if len(others) != 1 or not _same_line(others[0][layer], edge[layer]):
        return None
    return others[0].other_vert(vert)


def _corner(vert, fans, layer, uv_layers):
    """vert's line turns past ROUND_ANGLE there, in 3D or in a UV map on
    either side: a corner, which keeps the shape of what the line outlines (a
    lone quad lost a corner and became a triangle, a locomotive, 2026-10-10)."""
    ea, eb = _line(vert, layer)
    a, b = ea.other_vert(vert), eb.other_vert(vert)
    if _cos_turn(a.co, vert.co, b.co) < _COS_ROUND:
        return True
    for fan in fans:
        la, lv, lb = _loop_at(fan[0], a), _loop_at(fan[0], vert), _loop_at(fan[-1], b)
        if la is None or lb is None:
            continue
        for uv in uv_layers:
            if _cos_turn(la[uv].uv.to_3d(), lv[uv].uv.to_3d(), lb[uv].uv.to_3d()) < _COS_ROUND:
                return True
    return False


class _Run:
    """What one reduction carries from merge to merge: the layers, how round
    the original was around each vertex, and how many vertices of its line
    each vertex stands for (by ORIG id)."""

    def __init__(self, bm, layer, ratio, part, custom=True, min_sides=MIN_SIDES):
        self.layer = layer
        # how far a round line may turn at a vertex, and every other side
        # of a round part before it is halved: 45 and 23.5 degrees for 8
        self.round_angle = 2 * math.pi / max(3, min_sides)
        self.cos_round_slack = math.cos(self.round_angle + ROUND_SLACK)
        self.cos_half = math.cos(self.round_angle / 2 + math.radians(1.0))
        # A circle at min_sides strays from the true one by (1 - cos(pi / n))
        # of its radius: 3.8% of its size at 8 sides, within PART_DEVIATION;
        # 6.7% at 6, so a 12-sided ring could not be halved (2026-10-26).
        self.deviation = max(PART_DEVIATION, 1.1 * (1 - math.cos(math.pi / max(3, min_sides))) / 2)
        self.uv_layers = bm.loops.layers.uv.values()
        # Roundness is read from the shape (SHAPE), shading from the normals
        # the LOD will have: the original's own if it had custom normals,
        # else the shape's (Blender works them out again from the faces).
        self.shape = bm.loops.layers.float_vector.get(SHAPE)
        self.nrm = bm.loops.layers.float_vector.get(NORMAL if custom else SHAPE) or self.shape
        self.orig = bm.verts.layers.int.get(ORIG)
        # At 1 / ratio a curve could not lose a single point at 80% (each
        # left would stand for 1.25): halving is always allowed, and the
        # Size stops it where it is not needed.
        self.scale = max(2.0, 1.0 / max(ratio, 1e-3))
        # Vertices of the original line each vertex stands for, and the
        # widest angle between its shape normal and another corner's in one
        # of its faces in the original. Taking the steepest bend of what a
        # vertex absorbed instead let the limit grow merge after merge: an
        # arc of 24 went down to 4 (a locomotive's axle box yoke, 2026-10-10).
        self.weight = {}
        self.curve = {}
        for v in bm.verts:
            o = v[self.orig]
            self.weight[o] = 1
            worst = 1.0
            if self.shape is not None:
                for f in v.link_faces:
                    n_v = _loop_at(f, v)[self.shape]
                    for l in f.loops:
                        worst = min(worst, n_v.dot(l[self.shape]))
            self.curve[o] = math.acos(max(-1.0, min(1.0, worst)))
        # The original's triangles with their shading normals, by part, to
        # check the LOD's shading against (see original_normal).
        self.part_of = {v[self.orig]: part[v] for v in bm.verts}
        # How far behind each vertex the next surface of its own part facing
        # it is: the underside of a plate, the far wall of a box (see
        # THIN_SHARE). Another part's surface does not count: a pipe resting
        # on a support 1 cm inside its wall kept every side there, and,
        # halved everywhere else, filled with triangles (a pipe rack,
        # 2026-10-27).
        bm.normal_update()
        bm.faces.ensure_lookup_table()
        tree = BVHTree.FromBMesh(bm)
        self.room = {}
        for v in bm.verts:
            n = v.normal
            if n.length_squared < 0.5:
                continue
            start, d = v.co - n * 1e-6, 0.0
            for _ in range(16):
                hit = tree.ray_cast(start, -n)
                if hit[0] is None:
                    break
                d += hit[3]
                if part[bm.faces[hit[2]].verts[0]] == part[v]:
                    if hit[1].dot(n) < -0.3:
                        self.room[v[self.orig]] = d
                    break
                start = hit[0] - n * 1e-6
        # Open borders that meet another part's open border (see JOIN_GAP)
        # may barely move.
        for v in bm.verts:
            if not v.is_boundary:
                continue
            for _, _, i, d in tree.find_nearest_range(v.co, JOIN_GAP):
                f = bm.faces[i]
                if part[f.verts[0]] != part[v] and any(
                        e.is_boundary and _seg_dist(v.co, e.verts[0].co, e.verts[1].co) <= JOIN_GAP
                        for e in f.edges):
                    self.room[v[self.orig]] = min(self.room.get(v[self.orig], math.inf), JOIN_GAP)
                    break
        self._tris = {}
        self._trees = {}
        if self.nrm is not None:
            for tri in bm.calc_loop_triangles():
                self._tris.setdefault(part[tri[0].vert], []).append(
                    tuple(l.vert.co.copy() for l in tri) + tuple(Vector(l[self.nrm]) for l in tri))

    def original_normal(self, pid, p, facing):
        """The original's shading normal at the point of part pid nearest p,
        on a face turned the same way as facing (not the back of a plate);
        None if there is none."""
        tris = self._tris.get(pid)
        if not tris:
            return None
        tree = self._trees.get(pid)
        if tree is None:
            tree = BVHTree.FromPolygons([c for t in tris for c in t[:3]],
                                        [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))])
            self._trees[pid] = tree
        loc, nor, idx, d = tree.find_nearest(p)
        if loc is None:
            return None
        # Of the original faces about as near as the nearest, the nearest
        # turned like this face (within about 30 degrees), else the nearest
        # turned its way at all (not the back of a plate). A halved pipe's
        # new face lies inside the old surface, and on a coupling's 1.4 cm
        # bevel the nearest original face was the pipe beside it, turned
        # 43 degrees (a pipe rack, 2026-10-26).
        f = facing.normalized()
        hits = list(tree.find_nearest_range(p, 3 * d + 1e-6))
        for direction in (f, -f):
            hit = tree.ray_cast(p, direction, 3 * d + 1e-6)
            if hit[0] is not None:
                hits.append(hit)
        best = None
        for need in (0.85, 0.3):
            for hit in hits:
                if hit[1].dot(f) >= need and (best is None or hit[3] < best[3]):
                    best = hit
            if best is not None:
                break
        if best is None:
            return None
        loc, nor, idx, d = best
        a, b, c, na, nb, nc = tris[idx]
        if normal((a, b, c)).length_squared < 1e-20:
            return None
        n = barycentric_transform(loc, a, b, c, na, nb, nc)
        return n.normalized() if n.length_squared > 1e-12 else None

    def limit(self, angle):
        """The cosine of the widest angle a merge may leave where the original
        had `angle`."""
        return math.cos(min(self.round_angle + ROUND_SLACK, max(ROUND_FREE, angle * self.scale + ROUND_SLACK)))

    def absorb(self, v, t, along_line):
        """ORIG id v merged into t; along its line, t now stands for v too."""
        if along_line:
            self.weight[t] += self.weight[v]


def _keeps_round(run, vert, target, edge):
    """Merging vert (in the middle of a line) into target keeps the line as
    round as the Size allows: where it bends at the new corners (the vertex
    before vert, and target), target may stand for at most run.scale of the
    original's vertices, and no bend may pass ROUND_ANGLE unless it already
    did."""
    layer, o = run.layer, run.orig
    other = next(e for e in _line(vert, layer) if e is not edge)
    a = other.other_vert(vert)
    bends = []
    c = _line_next(target, edge, layer)
    if c is not None:
        bends.append((_cos_turn(vert.co, target.co, c.co), _cos_turn(a.co, target.co, c.co)))
    p = _line_next(a, other, layer)
    if p is not None:
        bends.append((_cos_turn(p.co, a.co, vert.co), _cos_turn(p.co, a.co, target.co)))
    if all(new >= _COS_FREE for _, new in bends):
        return True
    if any(new < min(old, run.cos_round_slack) - 1e-9 for old, new in bends):
        return False
    return run.weight[vert[o]] + run.weight[target[o]] <= run.scale + 1e-9


def _plan(vert, edge, layer):
    """[(faces, ref face)] per side of vert: the faces whose corner at vert
    take target's values from ref face's corner. None if vert is not a plain
    fan."""
    line = _line(vert, layer)
    if not line:
        return [(list(vert.link_faces), edge.link_faces[0])]
    ea, eb = line
    fans = _sides(vert, ea, eb)
    if fans is None:
        return None
    return [(fan, fan[0] if edge is ea else fan[-1]) for fan in fans]


def _line_uv_move(vert, plan, layer, uv_layers):
    """How far a line moves in UV when vert leaves it, scaled to metres along
    the line."""
    ea, eb = _line(vert, layer)
    a, b = ea.other_vert(vert), eb.other_vert(vert)
    length = (a.co - vert.co).length + (vert.co - b.co).length
    worst = 0.0
    for fan, _ in plan:
        for uv in uv_layers:
            uv_v = _loop_at(fan[0], vert)[uv].uv
            uv_a = _loop_at(fan[0], a)[uv].uv
            uv_b = _loop_at(fan[-1], b)[uv].uv
            uv_len = (uv_a - uv_v).length + (uv_v - uv_b).length
            if uv_len < 1e-12:
                continue
            dev = _seg_dist(uv_v.to_3d(), uv_a.to_3d(), uv_b.to_3d()) * length / uv_len
            worst = max(worst, dev)
    return worst


def _round_ok(run, old, new, verts):
    """A face whose corners had normals `old` and gets `new`, made of or
    absorbing `verts`, stays as round as the original allows there (see
    _Run.limit), or no less round than it was. Two corners of a 24-sided
    tube's face differ by 15 degrees: at 50% they may differ by 30."""
    lim = run.limit(max(run.curve[v[run.orig]] for v in verts))
    return _min_dot(new) >= min(_min_dot(old), lim) - 1e-9


def _refuse(why, reason):
    """False, noting the reason in why (a list) when given: for tests."""
    if why is not None:
        why.append(reason)
    return False


def _can_merge(run, vert, target, edge, plan, why=None, faces=True):
    """Merging vert into target along edge keeps the mesh sound and its shape
    and shading. With faces False, the faces it leaves are not checked (fold,
    roundness, shading): in a group of merges (a ring, a halving) each face
    is checked once every merge is made (_group_ok). Checked one merge at a
    time, a pipe's every other side could not go: with only one of a face's
    corners moved, the face twisted and shaded 20 degrees off, though once
    both had moved it was right (a pipe rack, 2026-10-26)."""
    layer, uv_layers, nrm = run.layer, run.uv_layers, run.nrm
    # Link condition: a common neighbour must close a triangle on the edge,
    # or the merge would fold the surface.
    near_v = {e.other_vert(vert) for e in vert.link_edges}
    near_t = {e.other_vert(target) for e in target.link_edges}
    allowed = {v for f in edge.link_faces if len(f.verts) == 3 for v in f.verts}
    if (near_v & near_t) - allowed:
        return _refuse(why, "link")
    if edge[layer] and not _keeps_round(run, vert, target, edge):
        return _refuse(why, "round line")
    # No face may end up with the same corners as another: a thin plate or a
    # short tube would close up into two faces back to back.
    existing = {frozenset(f.verts) for f in target.link_faces if vert not in f.verts}
    for fan, _ in plan:
        for f in fan:
            if target in f.verts and len(f.verts) == 3:
                continue
            key = frozenset(target if w is vert else w for w in f.verts)
            if key in existing:
                return _refuse(why, "same corners")
            existing.add(key)
    # The far corner of a triangle on the edge loses an edge; left with two
    # (one on a border) its faces fold onto each other, and later merges turn
    # that into an edge shared by three faces.
    for f in edge.link_faces:
        if len(f.verts) == 3:
            far = next(w for w in f.verts if w is not vert and w is not target)
            if len(far.link_edges) <= (2 if far.is_boundary else 3):
                return _refuse(why, "valence")
    # A side that is one triangle closed by a line on its third edge is a
    # whole UV island (or sharp sliver) on its own: the merge would delete it.
    for fan, _ in plan:
        if len(fan) == 1 and len(fan[0].verts) == 3:
            far = next(e for e in fan[0].edges if vert not in e.verts)
            if far[layer]:
                return _refuse(why, "one-triangle side")
    if not _keeps_islands({f for f in edge.link_faces if len(f.verts) == 3}, layer, len(uv_layers)):
        return _refuse(why, "island")
    if not faces:
        return True
    # No face may fold over, in 3D or in any UV map. A face holding both
    # loses vert's corner instead (a triangle that does simply goes).
    for fan, ref_face in plan:
        ref = _loop_at(ref_face, target)
        left = []
        for f in fan:
            shared = target in f.verts
            if shared and len(f.verts) == 3:
                continue
            if shared:
                loops = [l for l in f.loops if l.vert is not vert]
                cos = [l.vert.co for l in loops]
            else:
                loops = list(f.loops)
                cos = [target.co if l.vert is vert else l.vert.co for l in loops]
            n = normal(cos)
            if n.length_squared < 1e-20 or n.dot(f.normal) < 0.5:
                return _refuse(why, "fold 3d")
            shape = run.shape
            if shape is not None and not _round_ok(
                    run, [l[shape] for l in f.loops],
                    [ref[shape] if l.vert is vert else l[shape] for l in loops], list(f.verts) + [target]):
                return _refuse(why, "round face")
            if nrm is not None:
                left.append((cos, [ref[nrm] if l.vert is vert else l[nrm] for l in loops]))
            for uv in uv_layers:
                before = _uv_area([l[uv].uv for l in f.loops])
                after = _uv_area([ref[uv].uv if l.vert is vert else l[uv].uv for l in loops])
                if abs(before) < 1e-14:
                    continue
                if after / before < 0.05:
                    return _refuse(why, "fold uv")
        if left and not _shades_alike(vert.co, _loop_at(fan[0], vert)[nrm], left):
            return _refuse(why, "shading")
        if left and not _shades_like_original(run, run.part_of[vert[run.orig]], left):
            return _refuse(why, "shading")
    return True


def _prepare(bm, vert, target, edge, plan, layer):
    """Ready vert to be welded into target. Return the edges that must keep
    their flags afterwards: (target, other end, kind, seam, smooth)."""
    fixes = []
    # The line edge carrying on past vert becomes target's.
    for e in _line(vert, layer):
        if e is not edge:
            fixes.append((target, e.other_vert(vert), e[layer], e.seam, e.smooth))
    # A triangle on the edge goes; its two other edges become one.
    for f in edge.link_faces:
        if len(f.verts) == 3:
            far = next(w for w in f.verts if w is not vert and w is not target)
            ev, et = bm.edges.get((vert, far)), bm.edges.get((target, far))
            if ev is not None and et is not None:
                fixes.append((target, far, ev[layer] | et[layer], ev.seam or et.seam,
                              ev.smooth and et.smooth))
    # Each corner moving onto target takes target's UVs (and every other
    # corner value) from its own side of the line. A face holding both keeps
    # one of the two corners, so both must carry target's values.
    for fan, ref_face in plan:
        ref = _loop_at(ref_face, target)
        for f in fan:
            own = _loop_at(f, target)
            _loop_at(f, vert).copy_from(own if own is not None else ref)
    return fixes


# --- Edge rings ------------------------------------------------------------


def _ring_step(p, q, face):
    """Across quad face from its edge (p, q): the opposite edge, with the
    corners next to p and q. None if face is not a quad."""
    if len(face.verts) != 4:
        return None
    lp = _loop_at(face, p)
    if lp.link_loop_next.vert is q:
        p2, q2 = lp.link_loop_prev.vert, lp.link_loop_next.link_loop_next.vert
    else:
        p2, q2 = lp.link_loop_next.vert, lp.link_loop_prev.link_loop_prev.vert
    for e in face.edges:
        if p2 in e.verts and q2 in e.verts:
            return e, p2, q2
    return None


def ring_of(edge):
    """The edge ring through quads containing edge: [(edge, p, q)] in order,
    every p on one side and every q on the other. On a cylinder the ring of
    an edge around it runs along its length, so merging every p into its q
    takes out one whole side."""
    p, q = edge.verts
    halves = []
    for face in edge.link_faces[:2]:
        half = []
        seen = set()
        e, a, b, f = edge, p, q, face
        while True:
            step = _ring_step(a, b, f)
            if step is None:
                break
            e, a, b = step
            if e is edge:
                return [(edge, p, q)] + half  # a closed ring
            if e in seen:
                break
            seen.add(e)
            half.append((e, a, b))
            others = [g for g in e.link_faces if g is not f]
            if len(others) != 1:
                break
            f = others[0]
        halves.append(half)
    back = halves[1] if len(halves) > 1 else []
    return list(reversed(back)) + [(edge, p, q)] + (halves[0] if halves else [])


def _ring_closed(ring):
    """ring (from ring_of) goes all the way round: its first and last edges
    share a quad."""
    if len(ring) < 3:
        return False
    first = set(ring[0][0].link_faces)
    return any(f in first and len(f.verts) == 4 for f in ring[-1][0].link_faces)


def _round_spans(ring, closed, layer, cos_half=_COS_HALF):
    """The stretches of ring that go round and may lose every other side:
    [[i, ...]], ring positions in order, the first and last a line kept as
    it is (where the curve starts or ends, or a feature line), every other
    one bent within (ROUND_FREE, ROUND_ANGLE / 2] on both sides of the ring
    (halved, at most ROUND_ANGLE), all the same way round. A closed
    ring that is round all the way round and crosses no feature line gives
    its positions once, with no kept ends."""
    n = len(ring)
    sides = ([p.co for _, p, _ in ring], [q.co for _, _, q in ring])

    def axis(i):
        a, b = (i - 1) % n, (i + 1) % n
        for pts in sides:
            c = _cos_turn(pts[a], pts[i], pts[b])
            if c >= _COS_FREE or c < cos_half:
                return None
        ax = (sides[0][i] - sides[0][a]).cross(sides[0][b] - sides[0][i])
        return ax.normalized() if ax.length_squared > 1e-24 else None

    inner = range(n) if closed else range(1, n - 1)
    axes = {i: axis(i) for i in inner}
    free = {i for i in inner if axes[i] is not None and not ring[i][0][layer]}
    if closed and len(free) == n:
        if all(axes[i].dot(axes[(i + 1) % n]) > 0.5 for i in range(n)):
            return [list(range(n))]
        return []
    if closed:
        start = next(i for i in range(n) if i not in free)
        order = [(start + k) % n for k in range(n)] + [start]
    else:
        order = list(range(n))
    spans = []
    first = None
    for k, i in enumerate(order):
        ok = 0 < k < len(order) - 1 and i in free
        if ok and first is not None and axes[order[k - 1]].dot(axes[i]) <= 0.5:
            ok = False
        if ok:
            if first is None:
                first = k
        elif first is not None:
            spans.append(order[first - 1:k + 1])
            first = None
    return spans


class _Halving:
    """Every other side of a round part, to merge at once: chains of merges
    [(vert, edge)], each taking one whole side (an edge ring along the
    part) into the side before it."""

    def __init__(self):
        self.chains = []
        self.keys = []

    def trim(self, cost):
        """The stretches of each chain that may go (cost(vert, edge) not
        None), each its own run of merges: a side ring often meets a vertex
        that may not move (a corner of a wheel's rim in UV), and the rest of
        the side still goes. None if no stretch is left anywhere."""
        chains = []
        for chain in self.chains:
            stretch = []
            for m in chain + [None]:
                if m is not None and cost(*m) is not None:
                    stretch.append(m)
                elif stretch:
                    chains.append(stretch)
                    stretch = []
        return chains or None


def _halvings(rings, layer, orig, failed, known, released=(), notes=None, cos_half=_COS_HALF):
    """The round parts of the mesh and how to halve their sides, as artists
    do for a LOD: a tube of 32 sides keeps every other one, never two
    neighbours, so it stays round and even. Merged one side at a time by
    cost instead, a locomotive's 33-sided wheel rim kept 28 sides, the ones
    left unevenly spaced (2026-10-15).

    A round part is a ring of quads going round (`_round_spans`); its sides
    are the edge rings across it, as far as they run over round parts.
    Return (the halvings, the edges between two sides of a round part):
    those are only ever merged as part of a halving. Side rings whose key
    is in failed (refused before) are left, and edges in released are not
    reserved: a round part whose halving was refused may still lose sides
    one by one, within the round limits. Reserved for good, a pipe rack's
    long pipes kept all 16 sides (2026-10-26). known keeps each ring's round
    stretches from call to call, by its vertices: vertices never move, so
    the same ones give the same answer."""
    at = {}
    for ri, ring in enumerate(rings):
        for k, (x, a, b) in enumerate(ring):
            at[x] = (ri, k)
    reserved = set()
    spans = []
    for ring in rings:
        if len(ring) < 3:
            continue
        key = tuple(p[orig] for _, p, _ in ring) + tuple(q[orig] for _, _, q in ring)
        got = known.get(key)
        if got is None:
            closed = _ring_closed(ring)
            got = known[key] = (closed, _round_spans(ring, closed, layer, cos_half))
        closed, round_spans = got
        for span in round_spans:
            wrap = len(span) == len(ring) and closed and span[0] != span[-1]
            spans.append((wrap, ring, span))
    # Parts with a seam or hard line across them first: that line stays,
    # which fixes which sides go; a ring with none follows the others.
    spans.sort(key=lambda s: s[0])

    def side_of(ring, h, i):
        p, prev = ring[i][1], ring[h][1]
        side = next((x for x in p.link_edges if x.other_vert(p) is prev), None)
        return side if side is not None and side in at else None

    chains = {}  # (side ring, flip, first, end) -> (key, chain)

    def plan_of(ring, span, removed):
        plan = []
        for k in removed:
            side = side_of(ring, span[k - 1], span[k])
            if side is None:
                return None
            ri, anchor = at[side]
            side_ring = rings[ri]
            _, a, b = side_ring[anchor]
            flip = b is ring[span[k]][1]
            # only where the side runs over round parts: past them it may
            # cross a wheel's face to its far side
            lo, hi = anchor, anchor + 1
            while lo > 0 and side_ring[lo - 1][0] in reserved:
                lo -= 1
            while hi < len(side_ring) and side_ring[hi][0] in reserved:
                hi += 1
            got = chains.get((ri, flip, lo, hi))
            if got is None:
                chain = [((b if flip else a), x) for x, a, b in side_ring[lo:hi]]
                got = chains[(ri, flip, lo, hi)] = (frozenset(v[orig] for v, _ in chain), chain)
            plan.append((got[0], got[1], anchor - lo))
        return plan

    for wrap, ring, span in spans:
        pairs = list(zip(span, span[1:])) + ([(span[-1], span[0])] if wrap else [])
        for h, i in pairs:
            for c in (1, 2):
                p, prev = ring[i][c], ring[h][c]
                side = next((x for x in p.link_edges if x.other_vert(p) is prev), None)
                if side is not None:
                    reserved.add(side)

    role = {}  # vert -> True if merged away, False if kept as a target
    found = {}  # key of a side ring -> its _Halving
    covered = set()  # the edges of the side rings planned
    halvings = []
    for wrap, ring, span in spans:
        n = len(span)
        # every other side, either way round; never two neighbours
        if wrap:
            choices = (range(1, n - n % 2, 2), range(0, n - 1, 2))
        else:
            choices = (range(1, n - 1, 2), range(2, n - 1, 2))
        sides = [side_of(ring, span[k - 1], span[k]) for k in range(1 if not wrap else 0, n)]
        if not wrap:
            sides.insert(0, None)
        # another ring of the same part already planned it all
        if any(all(sides[k] in covered for k in removed) for removed in choices):
            continue
        best = None
        why = []
        for removed in choices:
            plan = plan_of(ring, span, removed)
            if not plan or any(key in failed for key, _, _ in plan):
                why.append("no plan" if not plan else "failed")
                continue
            # Each side from where it crosses this part outwards, up to the
            # first vertex another side already takes or keeps: where a part
            # changes its count of sides (a wheel's 32 on the tread, 33 on
            # its face), a side ring that was every other one is no longer.
            roles = {}
            new = []

            def free(v, t):
                return (v not in role and v not in roles
                        and role.get(t) is not True and roles.get(t) is not True)

            # first where each side crosses this part, then outwards
            for key, chain, k in plan:
                v, x = chain[k]
                if key not in found:
                    if not free(v, x.other_vert(v)):
                        new = None
                        break
                    roles[v] = True
                    roles.setdefault(x.other_vert(v), False)
            for key, chain, k in plan if new is not None else ():
                if key in found:
                    continue
                lo, hi = k, k + 1
                while lo > 0 and free(chain[lo - 1][0], chain[lo - 1][1].other_vert(chain[lo - 1][0])):
                    lo -= 1
                while hi < len(chain) and free(chain[hi][0], chain[hi][1].other_vert(chain[hi][0])):
                    hi += 1
                # claimed as it goes, so the next side stops short of it
                for v, x in chain[lo:hi]:
                    roles[v] = True
                    roles.setdefault(x.other_vert(v), False)
                new.append((key, chain[lo:hi], k - lo))
            if new is None:
                why.append("clash")
                continue
            agree = len(plan) - len(new)
            if best is None or agree > best[0]:
                best = (agree, plan, new, roles)
        if notes is not None:
            notes.append((_centre([(ring[i][1], None) for i in span]), len(ring), n, wrap,
                          why if best is None else ("ok", len(best[2]), len(best[1]))))
        if best is None or not best[2]:
            continue
        _, plan, new, roles = best
        owner = next((found[key] for key, _, _ in plan if key in found), None)
        if owner is None:
            owner = _Halving()
            halvings.append(owner)
        for key, chain, k in new:
            covered.update(x for _, x in chain)
            owner.chains.append(chain)
            owner.keys.append(key)
            found[key] = owner
        role.update(roles)
    return halvings, reserved.difference(released)


def _centre(members):
    """Where merges [(vert, edge)] are, on average: for test traces."""
    c = Vector()
    for v, _ in members:
        c += v.co
    return tuple(round(x, 3) for x in c / max(len(members), 1))


def _keeps_islands(deleted, layer, maps):
    """The faces a merge deletes do not make up a whole UV island in any map:
    each group of them joined across unsplit edges still reaches a face that
    stays. A ring closing up a one-quad-wide island lost it whole (a
    locomotive lost 113 islands in each map, 2026-10-10)."""
    if not deleted:
        return True
    for i in range(maps):
        bit = UV_SPLIT << i
        seen = set()
        for f in deleted:
            if f in seen:
                continue
            stack = [f]
            seen.add(f)
            reaches = False
            while stack:
                g = stack.pop()
                for e in g.edges:
                    if e[layer] & (bit | BORDER):
                        continue
                    for h in e.link_faces:
                        if h is g:
                            continue
                        if h not in deleted:
                            reaches = True
                        elif h not in seen:
                            seen.add(h)
                            stack.append(h)
            if not reaches:
                return False
    return True


def _group_ok(run, members, why=None):
    """With why (a list), a refusal notes the vertices where it is, when it
    is in one place, then the reason.
    Merging every (vert, target, edge, plan) of members at once keeps the
    surface manifold, unfolded in 3D and in every UV map, round where it was
    (see _round_ok), shaded as the original was (see _shades_like_original)
    and every UV island; no two faces end up with the same corners."""
    layer, uv_layers, nrm = run.layer, run.uv_layers, run.nrm
    merge = {}
    for v, t, e, plan in members:
        if v in merge:
            return _refuse(why, "dup source")
        merge[v] = t
    if any(t in merge for t in merge.values()):
        return _refuse(why, "target merged")
    ref_of = {}
    for v, t, e, plan in members:
        for fan, ref_face in plan:
            ref = _loop_at(ref_face, t)
            for f in fan:
                own = _loop_at(f, t)
                ref_of[(f, v)] = own if own is not None else ref
    touched = {f for v in merge for f in v.link_faces}
    use = {}
    deleted = set()
    new_face = {}
    keys = {frozenset(f.verts) for t in merge.values() for f in t.link_faces if f not in touched}
    for f in touched:
        loops = []
        for l in f.loops:
            w = merge.get(l.vert, l.vert)
            if loops and loops[-1][0] is w:
                continue
            loops.append((w, ref_of.get((f, l.vert), l)))
        if len(loops) > 1 and loops[0][0] is loops[-1][0]:
            loops.pop()
        verts = [w for w, _ in loops]
        if len(set(verts)) != len(verts):
            return _refuse(why, set(f.verts)) or _refuse(why, "dup corner")
        if len(verts) < 3:
            fv = list(f.verts)
            if not any(merge.get(a) is b or merge.get(b) is a
                       for a, b in zip(fv, fv[1:] + fv[:1])):
                return _refuse(why, set(f.verts)) or _refuse(why, "degenerate")
            deleted.add(f)
            continue
        n = normal([w.co for w in verts])
        if n.length_squared < 1e-20 or n.dot(f.normal) < 0.5:
            return _refuse(why, set(f.verts)) or _refuse(why, "fold 3d")
        key = frozenset(verts)
        if key in keys:
            return _refuse(why, set(f.verts)) or _refuse(why, "same corners")
        keys.add(key)
        if run.shape is not None and not _round_ok(run, [l[run.shape] for l in f.loops],
                                                   [l[run.shape] for _, l in loops], verts + list(f.verts)):
            if why is not None:
                why.append((tuple(round(c, 3) for c in f.calc_center_median()), len(f.verts), len(verts),
                            round(math.degrees(math.acos(max(-1, min(1, _min_dot([l[run.shape] for _, l in loops]))))), 1),
                            round(math.degrees(math.acos(max(-1, min(1, _min_dot([l[run.shape] for l in f.loops]))))), 1),
                            round(math.degrees(max(run.curve[w[run.orig]] for w in verts + list(f.verts))), 1)))
            return _refuse(why, set(f.verts)) or _refuse(why, "round face")
        if nrm is not None:
            new_face[f] = ([w.co for w in verts], [l[nrm] for _, l in loops])
        for uv in uv_layers:
            before = _uv_area([l[uv].uv for l in f.loops])
            after = _uv_area([l[uv].uv for _, l in loops])
            if abs(before) > 1e-14 and after / before < 0.05:
                return _refuse(why, set(f.verts)) or _refuse(why, "fold uv")
        for a, b in zip(verts, verts[1:] + verts[:1]):
            key = frozenset((a, b))
            use[key] = use.get(key, 0) + 1
    for key, n in use.items():
        a, b = tuple(key)
        e = next((x for x in a.link_edges if x.other_vert(a) is b), None)
        if e is not None:
            n += sum(1 for f in e.link_faces if f not in touched)
        if n > 2:
            return _refuse(why, {a, b}) or _refuse(why, "edge 3 faces")
    if nrm is not None:
        for v in merge:
            # each side of v: the faces whose corner at v has the same normal
            sides = {}
            for f in v.link_faces:
                n_v = _loop_at(f, v)[nrm]
                key = (round(n_v.x, 3), round(n_v.y, 3), round(n_v.z, 3))
                sides.setdefault(key, (n_v, []))[1].append(f)
            for n_v, faces in sides.values():
                left = [new_face[f] for f in faces if f in new_face]
                if left and not _shades_alike(v.co, n_v, left):
                    return _refuse(why, {v}) or _refuse(why, "shading here")
        pid = run.part_of[next(iter(merge))[run.orig]]
        for f, face in new_face.items():
            if not _shades_like_original(run, pid, [face]):
                if why is not None:
                    _shades_like_original(run, pid, [face], why)
                return _refuse(why, set(f.verts)) or _refuse(why, "shading original")
    return _keeps_islands(deleted, layer, len(uv_layers)) or _refuse(why, "island")


def _local_move(vert, target, edge, layer):
    """How far merging vert into target moves the surface where vert was:
    the most of how far vert is from the faces left (the true change at the
    point that goes), how far the middle of each face that moves gets from
    the face's old plane, and, along a line, how far vert is from the new
    line. Averaged into a quadric, one face moved 2 m across a fuel tank
    showed as 23 cm (a locomotive, 2026-10-10). Measured as how far target
    lay from vert's old face planes, a point on a circle counted twice what
    it moves the circle, and a pipe rack's 16-sided flanges could not lose
    a side (2026-10-26)."""
    p = vert.co
    d = target.co - p
    near = None
    middle = 0.0
    for f in vert.link_faces:
        if target in f.verts:
            if len(f.verts) == 3:
                continue
            cos = [l.vert.co for l in f.loops if l.vert is not vert]
        else:
            cos = [target.co if l.vert is vert else l.vert.co for l in f.loops]
            # the face's middle moves by a share of how far its corner does
            middle = max(middle, abs(f.normal.dot(d)) / len(cos))
        for i, j, k in _triangles(cos):
            q = closest_point_on_tri(p, cos[i], cos[j], cos[k])
            dist = (q - p).length_squared
            if near is None or dist < near:
                near = dist
    worst = max(math.sqrt(near) if near is not None else 0.0, middle)
    if edge[layer]:
        other = next((e for e in _line(vert, layer) if e is not edge), None)
        if other is not None:
            worst = max(worst, _seg_dist(p, other.other_vert(vert).co, target.co))
    return worst


def _parts(bm):
    """Each vertex's loose part (vertices joined by edges) as {vert: id}, and
    each part's size: twice the farthest its vertices are from their mean,
    the same however the part is turned. Measured by its box, the bolts
    round a flange, turned each its own way, came out different sizes, so
    half of them went (a pipeline, 2026-10-15)."""
    part = {}
    sizes = []
    for v0 in bm.verts:
        if v0 in part:
            continue
        pid = len(sizes)
        part[v0] = pid
        stack = [v0]
        verts = []
        while stack:
            v = stack.pop()
            verts.append(v)
            for e in v.link_edges:
                w = e.other_vert(v)
                if w not in part:
                    part[w] = pid
                    stack.append(w)
        mid = sum((v.co for v in verts), Vector()) / len(verts)
        sizes.append(2 * max((v.co - mid).length for v in verts))
    return part, sizes


def _kinds(bm, part, sizes):
    """The loose parts grouped into kinds, copies of one another: the same
    triangles, and area and size within KIND_TOLERANCE. [[part id, ...]]."""
    tris = [0] * len(sizes)
    area = [0.0] * len(sizes)
    for f in bm.faces:
        pid = part[f.verts[0]]
        tris[pid] += len(f.verts) - 2
        area[pid] += f.calc_area()
    order = sorted(range(len(sizes)), key=lambda p: (tris[p], area[p], sizes[p]))
    kinds = []
    for p in order:
        if kinds:
            q = kinds[-1][0]
            if (tris[p] == tris[q] and area[p] <= area[q] * (1 + KIND_TOLERANCE) + 1e-12
                    and abs(sizes[p] - sizes[q]) <= sizes[q] * KIND_TOLERANCE + 1e-9):
                kinds[-1].append(p)
                continue
        kinds.append([p])
    return kinds


def _plugs(bm, part, sizes, wanted):
    """The parts in wanted that fill an opening in another part: most of
    their corners sit on another part's open border. Deleted, a window pane
    or a door leaves a hole into the cab (a locomotive, 2026-10-10)."""
    points = []
    for e in bm.edges:
        if len(e.link_faces) < 2:
            a, b = e.verts
            points += [(a.co, part[a]), (b.co, part[b]), ((a.co + b.co) / 2, part[a])]
    if not points:
        return set()
    tree = KDTree(len(points))
    for i, (co, _) in enumerate(points):
        tree.insert(co, i)
    tree.balance()
    verts_of = {}
    for v, pid in part.items():
        if pid in wanted:
            verts_of.setdefault(pid, []).append(v)
    plugs = set()
    for pid, verts in verts_of.items():
        reach = max(0.002, 0.03 * sizes[pid])
        near = sum(1 for v in verts
                   if any(points[i][1] != pid for _, i, _ in tree.find_range(v.co, reach)))
        if near >= 0.3 * len(verts):
            plugs.add(pid)
    return plugs


def decimate(bm, layer, target, progress=None, trace=None, custom=True, part_size=PART_SIZE,
             info=None, halve=True, fixed=frozenset(), min_sides=MIN_SIDES, slack=None,
             tris=tri_count):
    """Merge vertices until bm has about `target` triangles or nothing more
    may go, taking first what moves the surface least. bm needs the ORIG
    vertex layer and the NORMAL and SHAPE loop layers. Return how many loose
    parts were deleted and how far the surface moved at most (metres).

    In quads a merge is a whole run of an edge ring at once (each vertex on
    one side into its partner on the other): a tube loses one whole side and
    stays straight. Merged one end at a time, a locomotive's 12-sided tubes
    twisted (2026-10-10). Edges in no ring of quads merge alone.

    Small loose parts (up to part_size of the whole mesh) may go whole
    instead of breaking, in the same queue, by kind (copies of one another,
    `_kinds`), smallest first: deleting one counts as moving the surface by
    half its size (about its radius). At 80% a locomotive kept its parts; deleting every part below
    the farthest merge so far took 327 of them.

    With halve, round parts lose every other side at once (see _halvings)
    and never one side alone; info, if a dict, gets "halved", how many
    halvings went.

    Vertices whose ORIG id is in fixed never go and take no merge, and parts
    with one never go (Edit Mode: the vertices not selected). Round parts
    keep min_sides at least. Triangles are counted with tris(bm) (the
    selection's only, in Edit Mode), and it stops within slack of target (1%
    of it by default)."""
    now = start = tris(bm)
    part, sizes = _parts(bm)
    run = _Run(bm, layer, target / max(start, 1), part, custom, min_sides)
    uv_layers, orig = run.uv_layers, run.orig
    q = quadrics(bm, layer, orig)
    # Small parts go by kind, smallest first, every copy of a kind at once or
    # none: a kind with one copy over the limit or filling an opening stays.
    part_limit = part_size * _diagonal(bm)
    kinds = [ps for ps in _kinds(bm, part, sizes) if max(sizes[p] for p in ps) <= part_limit]
    if fixed:
        held = {part[v] for v in bm.verts if v[orig] in fixed}
        kinds = [k for k in ([p for p in ps if p not in held] for ps in kinds) if k]
    plugs = _plugs(bm, part, sizes, {p for ps in kinds for p in ps})
    kinds = [ps for ps in kinds if plugs.isdisjoint(ps)]
    small = {p for ps in kinds for p in ps}
    verts_of = {}
    for v, pid in part.items():
        if pid in small:
            verts_of.setdefault(pid, []).append(v)
    # how far deleting a kind moves the surface: half its size
    doomable = {tuple(ps): PART_SHARE * max(sizes[p] for p in ps) for ps in kinds}
    level = 0.0
    gone = 0
    halved = 0
    failed = set()  # keys of side rings whose halving was refused
    released = set()  # their edges, free to merge one by one
    known = {}  # round stretches of rings, see _halvings
    if slack is None:
        slack = max(2, target // 100)
    costs = {}  # vert -> {edge: how far merging along edge moves the surface}
    dirty = set(bm.verts)
    while now > target + slack:
        bm.normal_update()
        # Only vertices whose faces changed last round are worked out again:
        # a vertex none of whose faces changed has the same neighbours, and
        # none of them took a merge (that would have changed a shared face).
        for v in dirty:
            if not v.is_valid:
                continue
            costs.pop(v, None)
            if v[orig] in fixed:
                continue
            opts = _options(v, layer)
            if not opts:
                continue
            uv_move = 0.0
            if opts[0][layer]:
                ea, eb = opts
                fans = _sides(v, ea, eb)
                if fans is None or _corner(v, fans, layer, uv_layers):
                    continue
                uv_move = _line_uv_move(v, [(fan, fan[0]) for fan in fans], layer, uv_layers)
            qv = q[v[orig]]
            limit = run.deviation * sizes[part[v]]
            by_edge = {}
            for e in opts:
                t = e.other_vert(v)
                if t[orig] in fixed:
                    continue
                qt = q[t[orig]]
                err = _error(qv, qt, t.co)
                # how far it moves the surface: the most of its own faces'
                # planes, of everything merged into either vertex so far
                # (mean over the quadric's planes), and of the line in UV
                dist = max(_local_move(v, t, e, layer),
                           math.sqrt(max(err, 0.0) / max(qv[10] + qt[10], 1e-12)), uv_move)
                if dist <= limit:
                    by_edge[e] = dist
            if by_edge:
                costs[v] = by_edge

        def cost(v, e):
            """How far merging v along e moves the surface; None if it may not
            go, or would move it through the surface behind (THIN_SHARE),
            halvings too: halved, a cab roof's curve went through its
            underside as well."""
            c = costs.get(v, {}).get(e)
            if c is not None and c > THIN_SHARE * run.room.get(v[orig], math.inf):
                return None
            return c

        # (how far it moves the surface, triangles it removes, what): a run
        # of merges [(vert, edge)], or a group of parts (a tuple of ids).
        found = []
        in_ring = set()
        rings = []
        for e in bm.edges:
            if e in in_ring or not any(len(f.verts) == 4 for f in e.link_faces):
                continue
            ring = ring_of(e)
            in_ring.update(x for x, _, _ in ring)
            if len(ring) >= 2:
                rings.append(ring)
        halvings, reserved = (_halvings(rings, layer, orig, failed, known, released, cos_half=run.cos_half)
                              if halve else ([], set()))
        for halving in halvings:
            chains = halving.trim(cost)
            if chains is None:
                if trace is not None:
                    trace.append(("halve-cost", _centre([m for c in halving.chains for m in c])))
                continue
            halving.chains = chains
            members = [m for chain in chains for m in chain]
            found.append((HALVE_SHARE * max(cost(v, x) for v, x in members), 2 * len(members), halving))
            if trace is not None:
                worst = max(members, key=lambda m: cost(*m))
                trace.append(("halve-offer", _centre(members), round(found[-1][0], 4), found[-1][1],
                              round(_local_move(worst[0], worst[1].other_vert(worst[0]), worst[1], layer), 4)))
        for ring in rings:
            for flip in (False, True):
                stretch = []
                for x, a, b in ring + [(None, None, None)]:
                    v = b if flip else a
                    c = cost(v, x) if x is not None and x not in reserved else None
                    if c is None:
                        if stretch:
                            found.append((max(r[0] for r in stretch), 2 * len(stretch),
                                          [(r[1], r[2]) for r in stretch]))
                        stretch = []
                        continue
                    stretch.append((c, v, x))
        for v, by_edge in costs.items():
            for e in by_edge:
                c = cost(v, e)
                if c is not None and e not in in_ring:
                    found.append((c, 2, [(v, e)]))
        if doomable:
            tris_now = {}
            for f in bm.faces:
                pid = part[f.verts[0]]
                if pid in small:
                    tris_now[pid] = tris_now.get(pid, 0) + len(f.verts) - 2
            for ps, err in doomable.items():
                gain = sum(tris_now.get(p, 0) for p in ps)
                if gain:
                    found.append((err, gain, ps))
        if not found:
            break
        # Ties (copies of a part reduce alike) go by the original vertex
        # numbers, so the same mesh always gives the same LOD.
        def tie(what):
            if isinstance(what, list):
                return what[0][0][orig]
            if isinstance(what, _Halving):
                return what.chains[0][0][0][orig]
            return -1 - what[0]

        found.sort(key=lambda c: (c[0], tie(c[2])))
        # Take about what is left, but none dearer than the cheapest that
        # many: a merge blocked by a neighbour this round waits for the next
        # one rather than letting a dear one in (a roof strip's corner merged
        # across its end, round 1).
        budget = max(1, now - target)
        count = 0
        cutoff = found[-1][0]
        for c, gain, _ in found:
            count += gain
            if count >= budget:
                cutoff = c
                break

        locked = set()
        targetmap = {}
        merges = []
        fixes = []
        doomed = []
        refused = []
        waiting = []  # a cheaper merge waits for the next round

        def take(members, chains=None):
            """Merge members as one group if safe; a ring that is not is tried
            again in halves, down to single merges (a head's long loops never
            passed whole, and Suzanne stopped at 28% when asked for 10%). A
            single merge refused is not tried again until its faces change.
            A halving (chains given) goes as one, less what is refused
            (take_halving). Return "wait", "no" or "ok"."""
            zone = set()
            for v, e in members:
                t = e.other_vert(v)
                zone.update(w for f in v.link_faces for w in f.verts)
                zone.update(w for f in t.link_faces for w in f.verts)
            if not zone.isdisjoint(locked):
                waiting.append(True)
                return "wait"
            if chains is not None:
                return take_halving(chains, zone)
            group = []
            for v, e in members:
                plan = _plan(v, e, layer)
                if plan is None:
                    break
                group.append((v, e.other_vert(v), e, plan))
            ok = (len(group) == len(members)
                  and all(_can_merge(run, v, t, e, plan, faces=len(group) == 1) for v, t, e, plan in group)
                  and (len(group) == 1 or _group_ok(run, group)))
            if not ok:
                if len(members) > 1:
                    half = len(members) // 2
                    take(members[:half])
                    take(members[half:])
                else:
                    v, e = members[0]
                    if costs.get(v, {}).pop(e, None) is not None:
                        refused.append(v)
                return "no"
            return commit(members, group, zone, [members])

        def take_halving(chains, zone):
            """Merge chains as one group; where that is refused, leave out
            the chains merging the vertices where it is and try again. A
            wheel whose rim has 32 sides and face 33 cannot lose every other
            one where the two meet, and it still loses them everywhere else."""
            chains = list(chains)
            for _ in range(len(chains) + 1):
                why = []
                group = []
                at = set()
                for chain in chains:
                    for v, e in chain:
                        t = e.other_vert(v)
                        plan = _plan(v, e, layer)
                        if plan is None:
                            at = {v}
                            why.append("plan")
                            break
                        if not _can_merge(run, v, t, e, plan, why, faces=False):
                            at = {v, t}
                            break
                        group.append((v, t, e, plan))
                    if at:
                        break
                if not at:
                    if _group_ok(run, group, why):
                        members = [m for chain in chains for m in chain]
                        return commit(members, group, zone, chains)
                    at = next((w for w in why if isinstance(w, set)), set())
                if trace is not None:
                    trace.append(("halve-no", _centre([m for c in chains for m in c]),
                                  [w for w in why if not isinstance(w, set)]))
                left = [c for c in chains
                        if not any(v in at or e.other_vert(v) in at for v, e in c)]
                released.update(x for c in chains if c not in left for _, x in c)
                if not left or len(left) == len(chains):
                    return "no"
                chains = left
            return "no"

        def commit(members, group, zone, chains):
            # In a ring, the edges either side of each closed-up quad become one.
            for chain in chains:
                after = chain[1:] + (chain[:1] if len(chain) > 2 else [])
                for (v1, e1), (v2, e2) in zip(chain, after):
                    t1, t2 = e1.other_vert(v1), e2.other_vert(v2)
                    if v1 is v2 or t1 is t2:
                        continue
                    ev, et = bm.edges.get((v1, v2)), bm.edges.get((t1, t2))
                    if ev is not None and et is not None:
                        fixes.append((t1, t2, ev[layer] | et[layer], ev.seam or et.seam,
                                      ev.smooth and et.smooth))
            for v, t, e, plan in group:
                fixes.extend(_prepare(bm, v, t, e, plan, layer))
                targetmap[v] = t
                merges.append((v[orig], t[orig], bool(e[layer])))
                if trace is not None:
                    trace.append(("merge", v[orig], t[orig], len(group), bool(e[layer])))
            locked.update(zone)
            return "ok"

        removed = 0

        def overshoots(gain):
            """A halving or a kind of parts goes whole: it would leave the LOD
            farther below the Size than it is above now. All 16 bolts of a
            pipe at once took it from 73% to 22% when asked for 50%."""
            left = budget - removed
            return gain - left > max(left, slack)

        for c, gain, what in found:
            if removed >= budget or c > cutoff:
                break
            if isinstance(what, tuple):
                verts = [v for p in what for v in verts_of[p] if v.is_valid]
                # Parts go only after every cheaper merge: one that is
                # always free to go would otherwise take the place of merges
                # that only had to wait a round.
                if waiting or not locked.isdisjoint(verts) or overshoots(gain):
                    continue
                locked.update(verts)
                doomed.extend(verts)
                del doomable[what]
                removed += gain
                gone += len(what)
                level = max(level, c)
                if trace is not None:
                    trace.append(("part", round(c, 4), len(what), gain, round(sizes[what[0]], 3)))
                continue
            before = len(targetmap)
            if isinstance(what, _Halving):
                if overshoots(gain):
                    continue
                done = take([m for chain in what.chains for m in chain], what.chains)
                if done == "no":
                    failed.update(what.keys)
                    released.update(x for chain in what.chains for _, x in chain)
                    refused.append(what)
                elif done == "ok":
                    removed += 2 * (len(targetmap) - before)
                    level = max(level, c)
                    halved += 1
                    if trace is not None:
                        trace.append(("halved", _centre([c[0] for c in what.chains]), round(c, 4), len(what.chains), gain))
                continue
            take(what)
            if len(targetmap) > before:
                removed += 2 * (len(targetmap) - before)
                level = max(level, c)
                if trace is not None:
                    trace.append(("taken", c, [(v[orig], e.other_vert(v)[orig]) for v, e in what]))
        if trace is not None:
            trace.append(("round", now, len(targetmap), round(level, 4), len(doomed)))
        if not targetmap and not doomed:
            if refused:
                # Everything cheap enough this round was refused: the next
                # round looks further up.
                dirty = set()
                continue
            break
        for v in targetmap:
            costs.pop(v, None)
        dirty = {w for w in locked if w not in targetmap}
        if targetmap:
            bmesh.ops.weld_verts(bm, targetmap=targetmap)
        for ov, ot, along_line in merges:
            _add(q[ot], q[ov])
            run.absorb(ov, ot, along_line)
        for t, other, kind, seam, smooth in fixes:
            if t.is_valid and other.is_valid:
                merged = bm.edges.get((t, other))
                if merged is not None:
                    merged[layer] = kind
                    merged.seam = seam
                    merged.smooth = smooth
        if doomed:
            for v in doomed:
                costs.pop(v, None)
            bmesh.ops.delete(bm, geom=doomed, context='VERTS')
            dirty = {w for w in dirty if w.is_valid}
        now = tris(bm)
        if progress is not None and start > target:
            progress(min(1.0, (start - now) / (start - target)))
    if info is not None:
        info["halved"] = halved
    return gone, level


# --- Flat areas to n-gons ------------------------------------------------


_SAME_NORMAL = math.cos(math.radians(1.0))


def _even(face, nrm):
    """Every corner of face has the same normal: its shading is flat."""
    first = face.loops[0][nrm]
    return all(l[nrm].dot(first) >= _SAME_NORMAL for l in face.loops)


def _straight(vert, uv_layers, nrm, tol):
    """vert sits on a straight run of two edges, in 3D and in every UV map,
    with the same normal as both ends."""
    a, b = (e.other_vert(vert) for e in vert.link_edges)
    if _seg_dist(vert.co, a.co, b.co) > tol:
        return False
    length = (a.co - vert.co).length + (vert.co - b.co).length
    for f in vert.link_faces:
        la, lv, lb = _loop_at(f, a), _loop_at(f, vert), _loop_at(f, b)
        if la is None or lb is None:
            return False
        if nrm is not None and (lv[nrm].dot(la[nrm]) < _SAME_NORMAL
                                or lv[nrm].dot(lb[nrm]) < _SAME_NORMAL):
            return False
        for uv in uv_layers:
            uv_len = (la[uv].uv - lv[uv].uv).length + (lv[uv].uv - lb[uv].uv).length
            if uv_len < 1e-12:
                continue
            dev = _seg_dist(lv[uv].uv.to_3d(), la[uv].uv.to_3d(), lb[uv].uv.to_3d())
            if dev * length / uv_len > tol:
                return False
    return True


def merge_flat(bm, layer, angle, tol, inside=lambda f: True):
    """Join each fairly flat area (every face within `angle` of where the area
    started, no feature line crossed) into one n-gon.

    Only faces shaded flat with the same normal join: a strip whose corners
    blend into a rounded edge is flat in shape, and joined to the face beside
    it spread the rounding over all of it (a locomotive's walkway beam,
    2026-10-10). Only faces for which inside(f) holds are joined, and only
    vertices all of whose faces are.

    An edge between two quads is never dissolved, so edge loops stay: a
    flange's flat face, halved to 12 quads, became one 14-sided n-gon each
    side of its seam (a pipe rack, 2026-10-27). Triangles and n-gons left in
    a flat area still join."""
    bm.normal_update()
    nrm = bm.loops.layers.float_vector.get(NORMAL)
    limit = math.cos(angle)
    region_of = {}
    for f in bm.faces:
        if f in region_of or not inside(f):
            continue
        seed = f.normal.copy()
        stack = [f]
        region_of[f] = f
        if nrm is not None and not _even(f, nrm):
            continue
        shade = f.loops[0][nrm] if nrm is not None else None
        while stack:
            g = stack.pop()
            for e in g.edges:
                if e[layer]:
                    continue
                for h in e.link_faces:
                    if h in region_of or not inside(h) or h.normal.dot(seed) < limit:
                        continue
                    if nrm is not None and (not _even(h, nrm)
                                            or h.loops[0][nrm].dot(shade) < _SAME_NORMAL):
                        continue
                    region_of[h] = f
                    stack.append(h)
    # One dissolve for every area at once: an operator call costs as much as
    # the whole mesh.
    inner = [e for e in bm.edges
             if not e[layer] and len(e.link_faces) == 2 and e.link_faces[0] in region_of
             and not (len(e.link_faces[0].verts) == 4 and len(e.link_faces[1].verts) == 4)
             and region_of[e.link_faces[0]] is region_of.get(e.link_faces[1])]
    if inner:
        bmesh.ops.dissolve_edges(bm, edges=inner, use_verts=False, use_face_split=False)

    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')

    uv_layers = bm.loops.layers.uv.values()
    straight = [v for v in bm.verts
                if len(v.link_edges) == 2 and v.link_faces and all(inside(f) for f in v.link_faces)
                and v.link_edges[0][layer] == v.link_edges[1][layer]
                and _straight(v, uv_layers, nrm, tol)]
    if straight:
        bmesh.ops.dissolve_verts(bm, verts=straight)


# --- Normals ------------------------------------------------------------------


def store_normals(bm, src):
    """Put each corner's normal from src into the NORMAL loop layer of bm (made
    from src). Merges carry it with every other corner value."""
    layer = bm.loops.layers.float_vector.new(NORMAL)
    normals = src.corner_normals
    bm.faces.ensure_lookup_table()
    for poly in src.polygons:
        for loop, li in zip(bm.faces[poly.index].loops, poly.loop_indices):
            loop[layer] = normals[li].vector
    return layer


def store_shape(bm, layer):
    """Put each corner's shape normal into the SHAPE loop layer: the mean of
    its vertex's face normals (by area) on its side of the creases (sharp,
    bent past the angle, open borders), whatever the shading. A flat-shaded
    sphere's corners each hold their own face's normal, so judged by those
    no merge kept it round and it was not reduced at all."""
    shape = bm.loops.layers.float_vector.new(SHAPE)
    crease = SHARP | ANGLE | BORDER
    bm.normal_update()
    for v in bm.verts:
        done = set()
        for f0 in v.link_faces:
            if f0 in done:
                continue
            fan = [f0]
            done.add(f0)
            stack = [f0]
            while stack:
                g = stack.pop()
                for e in g.edges:
                    if v not in e.verts or e[layer] & crease:
                        continue
                    for h in e.link_faces:
                        if h not in done:
                            done.add(h)
                            fan.append(h)
                            stack.append(h)
            n = Vector()
            for g in fan:
                n += g.normal * g.calc_area()
            n = n.normalized() if n.length_squared > 1e-30 else f0.normal.copy()
            for g in fan:
                _loop_at(g, v)[shape] = n
    return shape


def apply_normals(out, custom):
    """Set out's custom normals from its NORMAL corner attribute if custom,
    then drop the attribute."""
    attr = out.attributes.get(NORMAL)
    if attr is None:
        return
    if custom:
        normals = [Vector(d.vector) for d in attr.data]
        out.normals_split_custom_set(normals)
    out.attributes.remove(out.attributes[NORMAL])


# --- The whole reduction ---------------------------------------------------


def reduce_mesh(src, ratio, hard_surface=True, sharp_angle=math.radians(30),
                flat_angle=math.radians(5), part_size=PART_SIZE, progress=None, info=None,
                selected=None, min_sides=MIN_SIDES):
    """A new mesh with about `ratio` of src's triangles; src is not changed.

    Faces follow the source: a mostly triangulated source stays triangles,
    otherwise triangles are joined into quads, and in Hard Surface mode fairly
    flat areas (within `flat_angle`) become n-gons. Loose parts up to
    `part_size` of the mesh's size may go whole (0 keeps them all). If `info`
    is a dict, it gets "parts_removed" (how many loose parts went) and
    "moved" (how far the surface moved at most, in metres).

    With selected (polygon indices), only those faces are reduced, to about
    `ratio` of their triangles (Edit Mode): only their vertices merge, and
    only into one another. Faces beside them that share a vertex follow it;
    every face with no vertex in the selection stays as it was. The rest of
    the mesh still counts for what the selection may do: shading, the
    surface behind, the part's size. The result has what is left of the
    selection selected, and nothing else. Round parts keep min_sides at
    least (8 by default).
    """
    bm = bmesh.new()
    bm.from_mesh(src)
    region = fixed = None
    if selected is not None:
        region = bm.faces.layers.int.new(REGION)
        bm.faces.ensure_lookup_table()
        for i in selected:
            bm.faces[i][region] = 1
    target = max(1, round(tri_count(bm) * ratio))
    slack = None
    count = tri_count
    if region is not None:
        # Only the selection's triangles count, and the slack is 1% of
        # them: 1% of a 7,900-triangle pipe rack was more than a
        # 24-triangle selection, which then was never touched; and the
        # faces beside it losing corners stopped it halfway (2026-10-26).
        def count(bm):
            return sum(len(f.verts) - 2 for f in bm.faces if f[region])
        target = max(1, round(count(bm) * ratio))
        slack = max(1, target // 100)
    corners = [len(f.verts) for f in bm.faces]
    polys = bool(corners) and sum(1 for c in corners if c > 3) > 0.1 * len(corners)
    tol = _diagonal(bm) * 1e-5

    orig = bm.verts.layers.int.new(ORIG)
    for i, v in enumerate(bm.verts):
        v[orig] = i
    if region is not None:
        mine = {v for f in bm.faces if f[region] for v in f.verts}
        fixed = frozenset(v[orig] for v in bm.verts if v not in mine)
    store_normals(bm, src)
    layer = mark_features(bm, sharp_angle if hard_surface else None)
    store_shape(bm, layer)
    trace = info.get("trace") if info is not None else None  # a list, for tests
    gone, moved = decimate(bm, layer, target, progress, trace, src.has_custom_normals, part_size, info,
                           halve=hard_surface, fixed=fixed or frozenset(), min_sides=min_sides, slack=slack,
                           tris=count)
    inside = (lambda f: True) if region is None else (lambda f: bool(f[region]))
    if info is not None:
        info["parts_removed"] = gone
        info["moved"] = moved

    if polys:
        tris = [f for f in bm.faces if len(f.verts) == 3 and inside(f)]
        # Only nearly flat pairs: a bent quad can be split along its other
        # diagonal later (by Blender or a game exporter), which moves the
        # surface and blends its normals the other way.
        bmesh.ops.join_triangles(
            bm, faces=tris, cmp_seam=True, cmp_sharp=True, cmp_uvs=True,
            cmp_vcols=True, cmp_materials=True,
            angle_face_threshold=min(sharp_angle, JOIN_ANGLE) if hard_surface else JOIN_ANGLE,
            angle_shape_threshold=math.radians(40))
        if hard_surface:
            merge_flat(bm, layer, flat_angle, tol, inside)
    if region is not None:
        for x in (*bm.verts, *bm.edges):
            x.select = False
        for f in bm.faces:
            f.select = False
        for f in bm.faces:
            if f[region]:
                f.select_set(True)
        bm.faces.layers.int.remove(region)
    bm.edges.layers.int.remove(layer)
    bm.loops.layers.float_vector.remove(bm.loops.layers.float_vector[SHAPE])
    out = src.copy()  # keeps the material slots
    bm.to_mesh(out)
    bm.free()
    apply_normals(out, src.has_custom_normals)
    out.attributes.remove(out.attributes[ORIG])
    return out


def _bad_edges(bm):
    return sum(1 for e in bm.edges if len(e.link_faces) > 2)


def _diagonal(bm):
    if not bm.verts:
        return 1.0
    first = next(iter(bm.verts)).co
    lo, hi = Vector(first), Vector(first)
    for v in bm.verts:
        for i in range(3):
            lo[i] = min(lo[i], v.co[i])
            hi[i] = max(hi[i], v.co[i])
    return max((hi - lo).length, 1e-6)
