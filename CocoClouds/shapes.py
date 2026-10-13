"""The rough shape a new cloud starts from: spheres, as a mesh.

A cloud added from nothing is a heap of overlapping spheres, an ordinary mesh
the user can go on editing. What makes a heap read as a cloud is spheres of
very different sizes: a few large ones for the body, each carrying smaller
ones on its surface, and those carrying smaller ones again. Houdini's cloud
tools build a cumulus the same way (Cloud Shape Generate for the spheres,
Cloud Shape Replicate for the smaller ones around them), and so do the
metaball rigs of Blender's cloud add-ons. Spheres all of one size, which is
what CocoClouds made up to 0.3.0, give a lumpy sausage.

Every builder takes a random.Random and returns blobs, each (centre, radii),
in a space where the cloud is about one unit wide. blockout_mesh() scales the
result to the width asked for and rests it on Z = 0. Another seed is another
cloud: a builder draws how many spheres, how large and in what proportions,
not only where they go.
"""

import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Vector


def _ball(x, y, z, r, flat=1.0, wide=1.0):
    """A blob at a place: radius `r` along X, `wide` of it along Y, `flat`
    of it along Z."""
    return (Vector((x, y, z)), (r, r * wide, r * flat))


def _joined(blobs, start=1, reach=0.7):
    """Make one piece of the blobs from `start` on: each must go deep into
    one already joined, centres closer than `reach` of the two radii
    together, and is grown until it does. Merely touching is not enough, the
    erosion eats a thin neck and leaves the blob floating.

    They are taken nearest first. Taken in the order they were made, a blob
    far from the few before it was grown across the whole gap, into one huge
    lump with the others inside it."""
    done = list(blobs[:max(start, 1)])
    left = list(blobs[max(start, 1):])
    while left:
        def short(blob):
            return min((blob[0] - c).length - reach * (blob[1][0] + r[0]) for c, r in done)
        blob = min(left, key=short)
        left.remove(blob)
        gap = short(blob)
        if gap > 0.0:
            k = 1.0 + gap / (reach * blob[1][0])
            blob = (blob[0], tuple(v * k for v in blob[1]))
        done.append(blob)
    blobs[:] = done
    return blobs


def _sprout(rng, parents, count, scale, up=-0.2, reach=(0.6, 0.95), flat=1.0):
    """Smaller blobs grown out of larger ones: for each parent a number of
    them within `count`, a part of its size within `scale`, their centres
    just under its surface and no lower on it than `up` (-1 is the underside,
    1 the top). About one in seven comes out half as large again, so that a
    level is not all of one size either."""
    made = []
    for centre, radii in parents:
        for _ in range(rng.randint(*count)):
            while True:
                d = Vector((rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)))
                if d.length > 1e-6 and d.normalized().z >= up:
                    break
            d.normalize()
            r = radii[0] * rng.uniform(*scale) * (1.5 if rng.random() < 0.15 else 1.0)
            out = Vector((d.x * radii[0], d.y * radii[1], d.z * radii[2])) * rng.uniform(*reach)
            made.append((centre + out, (r, r, r * flat)))
    return made


def _row(rng, count, radius, flat=1.0, depth=0.08):
    """The body of a low cloud: blobs side by side along X over a width of
    0.7, each a part of their spacing within `radius`, resting near Z = 0."""
    step = 0.7 / count
    blobs = []
    for i in range(count):
        r = step * rng.uniform(*radius)
        x = -0.35 + (i + 0.5 + rng.uniform(-0.2, 0.2)) * step
        blobs.append(_ball(x, rng.uniform(-depth, depth), r * flat * rng.uniform(0.5, 0.8), r, flat))
    return _joined(blobs)


def _column(rng, floors, shrink, radius=(0.2, 0.26)):
    """The body of a tall cloud: three blobs round the foot, then one on top
    of the other, each a little smaller and a little off to the side."""
    r = rng.uniform(*radius)
    blobs = []
    for i in range(3):
        angle = rng.uniform(0.0, math.tau)
        foot = r * rng.uniform(0.85, 1.15)
        blobs.append(_ball(0.45 * r * math.cos(angle) * (i > 0), 0.45 * r * math.sin(angle) * (i > 0),
                           foot * rng.uniform(0.5, 0.8), foot))
    place = Vector((0.0, 0.0, r * 0.8))
    lean = Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.15, 0.15), 0.0))
    for _ in range(floors):
        r *= rng.uniform(*shrink)
        place = place + (lean + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), rng.uniform(0.75, 1.05)))) * r
        blobs.append((place.copy(), (r, r, r)))
    return _joined(blobs)


def _scatter(rng, count, half_width, half_depth):
    """Places in an ellipse on the ground, spread evenly: each is the one of
    a dozen tries farthest from those before it."""
    places = []
    for _ in range(count):
        best = None
        for _ in range(12):
            angle, away = rng.uniform(0.0, math.tau), math.sqrt(rng.random())
            p = Vector((away * half_width * math.cos(angle), away * half_depth * math.sin(angle), 0.0))
            near = min(((p - q).length for q in places), default=1.0)
            if best is None or near > best[0]:
                best = (near, p)
        places.append(best[1])
    return places


def _cumulus(rng):
    """Cumulus mediocris: a row of unequal lumps, one or two large ones
    riding on it, then two levels of smaller ones."""
    body = _row(rng, rng.randint(3, 5), (0.8, 1.6))
    crown = _sprout(rng, rng.sample(body, k=rng.randint(1, min(2, len(body)))), (1, 2), (0.7, 1.0), up=0.45)
    first = _sprout(rng, body + crown, (3, 5), (0.4, 0.65))
    second = _sprout(rng, first, (1, 2), (0.5, 0.75))
    return body + crown + first + second


def _puff(rng):
    """Cumulus humilis: wider than tall, a few flattened lumps and their
    small ones on top."""
    body = _row(rng, rng.randint(2, 4), (0.75, 1.3), flat=0.7)
    first = _sprout(rng, body, (2, 4), (0.4, 0.6), up=0.0, flat=0.8)
    second = _sprout(rng, first, (0, 2), (0.5, 0.7), up=0.0, flat=0.8)
    return body + first + second


def _tower(rng):
    """Cumulus congestus: a column taller than wide, turrets all over it."""
    body = _column(rng, rng.randint(3, 5), (0.82, 0.97))
    first = _sprout(rng, body, (3, 5), (0.4, 0.62), up=-0.3)
    second = _sprout(rng, first, (1, 2), (0.45, 0.7))
    return body + first + second


def _anvil(rng):
    """Cumulonimbus: a broad lumpy tower that flares out near its top into
    the anvil, a thick sheet twice as wide, flat on top, thinning towards
    its rim and reaching farther downwind than upwind.

    The anvil is slabs whose tops all lie on one ceiling, each thinner the
    farther it is from the tower: flat above, sloping below. The collar of
    blobs under it is what makes the tower run into the anvil instead of
    carrying it like a table."""
    body = _column(rng, rng.randint(3, 4), (0.95, 1.05), (0.3, 0.36))
    top, r = max(body, key=lambda blob: blob[0].z)
    r = r[0]
    wind = rng.uniform(0.0, math.tau)
    downwind = Vector((math.cos(wind), 0.6 * math.sin(wind), 0.0))

    collar = []
    count = rng.randint(4, 6)
    for i in range(count):
        angle = (i + rng.uniform(-0.3, 0.3)) * math.tau / count
        a = r * rng.uniform(0.6, 0.85)
        collar.append(_ball(top.x + 1.1 * r * math.cos(angle), top.y + 1.1 * r * math.sin(angle),
                            top.z + r * rng.uniform(-0.2, 0.2), a))

    span = r * rng.uniform(1.7, 2.1)
    thick = r * rng.uniform(0.7, 0.9)
    ceiling = top.z + r * 0.7 + thick
    centre = Vector((top.x, top.y, 0.0)) + downwind * 0.3 * span
    slabs = [(Vector((centre.x, centre.y, ceiling - thick)), (span, span * 0.85, thick))]
    count = rng.randint(6, 9)
    for i in range(count):
        angle = (i + rng.uniform(-0.3, 0.3)) * math.tau / count
        away = rng.uniform(0.45, 0.95)
        out = Vector((math.cos(angle), 0.8 * math.sin(angle), 0.0)) * away * span
        # Farther downwind than upwind.
        out *= 1.0 + 0.5 * max(0.0, out.normalized().dot(downwind.normalized()))
        a = span * rng.uniform(0.45, 0.65)
        deep = thick * rng.uniform(0.6, 1.0) * (1.0 - 0.55 * away)
        slabs.append((Vector((centre.x + out.x, centre.y + out.y, ceiling - deep)), (a, a * rng.uniform(0.8, 1.0), deep)))

    blobs = _joined(body + collar + slabs, start=len(body), reach=0.6)
    first = _sprout(rng, body, (3, 5), (0.4, 0.6), up=-0.3)
    second = _sprout(rng, first + collar, (1, 2), (0.45, 0.7))
    return blobs + first + second


def _sheet(rng):
    """Stratocumulus: a patch of low rounded masses grown into one another."""
    count = rng.randint(12, 20)
    step = math.sqrt(0.5 / count)
    body = []
    for p in _scatter(rng, count, 0.5, rng.uniform(0.28, 0.4)):
        r = step * rng.uniform(0.6, 1.25)
        body.append(_ball(p.x, p.y, 0.5 * r * rng.uniform(0.6, 0.9), r, 0.5))
    _joined(body)
    return body + _sprout(rng, body, (1, 3), (0.45, 0.7), up=0.2, flat=0.7)


def _flock(rng):
    """Altocumulus: a field of small separate cloudlets in loose rows."""
    across, deep = rng.randint(5, 7), rng.randint(4, 6)
    step = 1.0 / across
    blobs = []
    for j in range(deep):
        for i in range(across):
            x = (i + 0.5 * (j % 2) + rng.uniform(-0.25, 0.25)) * step - 0.5
            y = (j + rng.uniform(-0.25, 0.25) - 0.5 * (deep - 1)) * step * 0.9
            ragged = (x / 0.5) ** 2 + (y / (0.45 * deep * step)) ** 2 > 1.0 - rng.uniform(0.0, 0.3)
            if ragged or rng.random() < 0.12:
                continue
            r = step * rng.uniform(0.26, 0.5)
            blobs.append(_ball(x, y, 0.0, r, 0.55, rng.uniform(0.8, 1.2)))
    return blobs or [_ball(0.0, 0.0, 0.0, 0.2, 0.55)]


def _lens(rng):
    """Altocumulus lenticularis: one smooth lens, or a stack of two or three."""
    a, z = 0.5, 0.0
    blobs = []
    for _ in range(rng.choice((1, 2, 2, 3))):
        flat = rng.uniform(0.11, 0.16)
        z += a * flat * (1.3 if blobs else 1.0)
        blobs.append(_ball(rng.uniform(-0.08, 0.08) * bool(blobs), 0.0, z, a, flat, rng.uniform(0.6, 0.85)))
        z += a * flat * 0.9
        a *= rng.uniform(0.6, 0.85)
    return blobs


def _shreds(rng):
    """Fractus: a few small ragged pieces strung out, some apart."""
    x = -0.4
    blobs = []
    for _ in range(rng.randint(4, 7)):
        r = rng.uniform(0.08, 0.16)
        long = rng.uniform(1.1, 1.6)
        x += r * long * rng.uniform(0.5, 1.0)
        blobs.append((Vector((x, rng.uniform(-1.0, 1.0) * r, rng.uniform(-0.7, 0.7) * r)),
                      (r * long, r * rng.uniform(0.7, 1.0), r * rng.uniform(0.6, 0.9))))
        x += r * long * rng.uniform(0.5, 1.3)
    return blobs


def _layer(rng):
    """Stratus: one flat grey sheet, of a few wide slabs run together."""
    blobs = []
    for p in _scatter(rng, rng.randint(5, 8), 0.5, rng.uniform(0.25, 0.38)):
        a = rng.uniform(0.22, 0.36)
        blobs.append(_ball(p.x, p.y, rng.uniform(-0.02, 0.02), a, rng.uniform(0.1, 0.15), rng.uniform(0.7, 1.0)))
    return _joined(blobs, reach=0.6)


BUILDERS = {
    'CUMULUS': _cumulus,
    'PUFF': _puff,
    'TOWER': _tower,
    'ANVIL': _anvil,
    'SHEET': _sheet,
    'FLOCK': _flock,
    'LENS': _lens,
    'SHREDS': _shreds,
    'LAYER': _layer,
}


def blobs(identifier, seed):
    return BUILDERS[identifier](random.Random(seed))


_ICOSPHERES = {}


def _icosphere(subdivisions):
    """The vertices and the triangles of an icosphere of radius 1, made once."""
    if subdivisions not in _ICOSPHERES:
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0)
        bm.verts.index_update()
        _ICOSPHERES[subdivisions] = (
            np.array([v.co for v in bm.verts], dtype=np.float32),
            np.array([[v.index for v in f.verts] for f in bm.faces], dtype=np.int32))
        bm.free()
    return _ICOSPHERES[subdivisions]


def fill_mesh(mesh, identifier, seed, size):
    """Write the rough shape a cloud of a type starts from into a mesh,
    in place of whatever it holds: `size` wide along X, its base on Z = 0.
    Each seed gives another one.

    The spheres are copies of two icospheres put together as arrays. One
    bmesh operator call for each took 60 to 170 ms for a heap, too long for
    a slider that calls this at every step; this takes a few."""
    heap = blobs(identifier, seed)
    largest = max(r[0] for _c, r in heap)
    verts, faces, count = [], [], 0
    for centre, radii in heap:
        # The large ones show their facets, the small ones only add vertices.
        v, f = _icosphere(3 if radii[0] > 0.5 * largest else 2)
        verts.append(v * np.array(radii, dtype=np.float32) + np.array(centre, dtype=np.float32))
        faces.append(f + count)
        count += len(v)
    verts, faces = np.concatenate(verts), np.concatenate(faces)
    # Sized on the vertices themselves: an icosphere does not reach its
    # radius along every axis.
    verts[:, 2] -= verts[:, 2].min()
    verts *= size / (verts[:, 0].max() - verts[:, 0].min())
    mesh.clear_geometry()
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set("vertex_index", faces.ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(0, faces.size, 3, dtype=np.int32))
    mesh.update(calc_edges=True)


def blockout_mesh(identifier, seed, size, name="Cloud"):
    mesh = bpy.data.meshes.new(name)
    fill_mesh(mesh, identifier, seed, size)
    return mesh


def is_heap(mesh, identifier, seed):
    """True while a mesh is still the heap fill_mesh() made of a type and a
    seed, at whatever size: nothing moved, added or removed by hand."""
    if not mesh.vertices:
        return False
    size = width(mesh)
    scratch = bpy.data.meshes.new(".cococlouds heap")
    try:
        fill_mesh(scratch, identifier, seed, size)
        if len(scratch.vertices) != len(mesh.vertices):
            return False
        a = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        b = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", a)
        scratch.vertices.foreach_get("co", b)
        return float(np.abs(a - b).max()) < 1e-4 * max(size, 1e-6)
    finally:
        bpy.data.meshes.remove(scratch)


def width(mesh):
    """How wide a mesh is along X: what fill_mesh() calls its size."""
    if not mesh.vertices:
        return 0.0
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    return float(co[0::3].max() - co[0::3].min())
