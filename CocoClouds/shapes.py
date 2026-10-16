"""The rough shape a new cloud starts from: spheres, as a mesh.

The generator. A heaped cloud is built the way Cloud Creator's generator is
described by its author: primary spheres spread over the cloud's footprint,
the footprint broken up by a noise on the ground plane (Distortion), then a
few rounds of secondary spheres (Lumps), each round a ring of smaller ones
on the surface of the last, pushed mostly upwards or, with Spread, every
way. Random Size makes the spheres of a round unequal. A layer cloud is a
sheet of flattened spheres. A cirrus is not spheres but strokes, in a curve
object (fill_curve), which the user can draw more of. A heap
or a sheet is always one piece: _joined pulls any part that came out apart
back onto the rest.

The result is an ordinary mesh the user can go on editing. The Cloud
modifier then fills it with balls (nodes.py); the spheres here only give
the outline.

Every builder takes a random.Random and the generator's settings and
returns blobs, each (centre, radii), in a space about one unit long.
fill_mesh() stretches them to the length, width and height asked for and
rests them on Z = 0. Another seed is another cloud.
"""

import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Vector

# The generator's settings, with what each starts at when a genus does not
# say otherwise: (name, default, min, max, description).
SETTINGS = (
    ("lumps", 2, 0, 4, "Rounds of smaller spheres grown on the larger ones"),
    ("spread", 0.3, 0.0, 1.0, "Which way the lumps grow: upwards at 0, every way at 1"),
    ("random_size", 0.5, 0.0, 1.0, "How unequal the spheres are"),
    ("distortion", 0.3, 0.0, 1.0, "How far the noise on the ground plane breaks up the footprint"),
    ("distortion_scale", 2.0, 0.1, 20.0, "How many bends of that noise across the cloud"),
)


def _ball(x, y, z, r, flat=1.0, wide=1.0):
    """A blob at a place: radius `r` along X, `wide` of it along Y, `flat`
    of it along Z."""
    return (Vector((x, y, z)), (r, r * wide, r * flat))


class _Wobble:
    """A smooth noise on the ground plane, a few sines of random phases:
    the Distortion of the footprint."""

    def __init__(self, rng, scale):
        self.waves = [(rng.uniform(0.6, 1.4) * scale * math.tau, rng.uniform(0.0, math.tau),
                       rng.uniform(0.0, math.tau)) for _ in range(3)]

    def __call__(self, x, y):
        dx = sum(math.sin(f * y + a) for f, a, _b in self.waves) / 3.0
        dy = sum(math.sin(f * x + b) for f, _a, b in self.waves) / 3.0
        return dx, dy


def _distorted(rng, p, blobs, reach=0.25):
    """Move the blobs on the ground plane by the Distortion noise."""
    if p["distortion"] <= 0.0:
        return blobs
    wobble = _Wobble(rng, p["distortion_scale"])
    moved = []
    for c, r in blobs:
        dx, dy = wobble(c.x, c.y)
        moved.append((Vector((c.x + dx * reach * p["distortion"], c.y + dy * reach * p["distortion"], c.z)), r))
    return moved


def _unequal(rng, p, r, by=0.6):
    """A radius made unequal by Random Size."""
    return r * (1.0 + p["random_size"] * rng.uniform(-by, by))


# Two blobs are joined when the line between their centres runs inside one
# or the other shrunk to JOIN of its radii: a thinner neck does not survive
# the cloud's fill, and the heap would come out as two clouds.
JOIN = 0.75


def _inside(q, blob, shrink):
    c, r = blob
    return sum(((q[i] - c[i]) / (r[i] * shrink)) ** 2 for i in range(3)) <= 1.0


def _touch(a, b, shrink=JOIN):
    if (a[0] - b[0]).length > (max(a[1]) + max(b[1])) * shrink:
        return False
    for k in range(1, 12):
        q = a[0].lerp(b[0], k / 12.0)
        if not (_inside(q, a, shrink) or _inside(q, b, shrink)):
            return False
    return True


def _joined(blobs):
    """Pull pieces of a heap that do not touch the rest onto it, each piece
    whole, along the ground, until it is joined to the nearest blob of the
    largest piece."""
    blobs = list(blobs)
    while True:
        # The pieces, as lists of indices, largest (by volume) first.
        left, pieces = set(range(len(blobs))), []
        while left:
            piece, todo = [], [left.pop()]
            while todo:
                i = todo.pop()
                piece.append(i)
                near = [j for j in left if _touch(blobs[i], blobs[j])]
                left.difference_update(near)
                todo += near
            pieces.append(piece)
        if len(pieces) == 1:
            return blobs
        pieces.sort(key=lambda piece: -sum(blobs[i][1][0] * blobs[i][1][1] * blobs[i][1][2] for i in piece))
        main, stray = pieces[0], pieces[1]
        i, j = min(((i, j) for i in stray for j in main),
                   key=lambda ij: (blobs[ij[0]][0] - blobs[ij[1]][0]).length)
        way = blobs[j][0] - blobs[i][0]
        way.z = 0.0
        if way.length < 1e-6:
            way = blobs[j][0] - blobs[i][0]
        step = way * 0.05
        for _ in range(20):
            for k in stray:
                blobs[k] = (blobs[k][0] + step, blobs[k][1])
            if _touch(blobs[i], blobs[j]):
                break
        else:
            # Over it and still apart in height: the rest of the way up or down.
            rest = blobs[j][0] - blobs[i][0]
            for k in stray:
                blobs[k] = (blobs[k][0] + rest, blobs[k][1])


def _scatter(rng, count, half_width, half_depth):
    """Places in an ellipse on the ground, spread evenly: each is the one of
    a dozen tries farthest from those before it."""
    places = []
    for _ in range(count):
        best = None
        for _ in range(12):
            angle, away = rng.uniform(0.0, math.tau), math.sqrt(rng.random())
            q = Vector((away * half_width * math.cos(angle), away * half_depth * math.sin(angle), 0.0))
            near = min(((q - o).length for o in places), default=1.0)
            if best is None or near > best[0]:
                best = (near, q)
        places.append(best[1])
    return places


def _lumps(rng, p, parents, rounds=None, per=(2, 4), shrink=(0.55, 0.8), up=1.0, flat=1.0, lowest=-0.25,
           reach=(0.8, 1.05)):
    """Rounds of smaller spheres on the surface of the larger ones. Each
    round grows on the one before: a direction mostly up (`up` -1 turns it
    down) bent towards a random one by Spread, the centre a little under the
    parent's surface. Returns every round's spheres together."""
    rounds = p["lumps"] if rounds is None else rounds
    made, last = [], parents
    for _ in range(rounds):
        grown = []
        for centre, radii in last:
            for _ in range(rng.randint(*per)):
                while True:
                    d = Vector((rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)))
                    if d.length > 1e-6:
                        break
                d.normalize()
                lean = Vector((rng.gauss(0.0, 0.35), rng.gauss(0.0, 0.35), up))
                way = lean.normalized().lerp(d, p["spread"])
                if way.length < 1e-6:
                    continue
                way.normalize()
                if way.z * up < lowest:
                    way.z = lowest * up
                    way.normalize()
                r = _unequal(rng, p, radii[0] * rng.uniform(*shrink), 0.35)
                out = Vector((way.x * radii[0], way.y * radii[1], way.z * radii[2])) * rng.uniform(*reach)
                grown.append((centre + out, (r, r, r * flat)))
        made += grown
        last = grown
    return made


# ---------------------------------------------------------------- the genera

def _aspect(p):
    """The cloud's width and height as parts of its length: a genus is built
    in those proportions, so the stretch to the size asked for keeps its
    spheres round."""
    return p.get("aspect", (1.0, 0.75, 0.6))


def _turret(rng, p, place, top, r):
    """A rising tower of a heap: spheres stacked from the ground up to `top`,
    narrowing a little upwards and wandering sideways, ending in a dome."""
    made, centre, z = [], Vector((place.x, place.y, 0.0)), r * 0.4
    for _ in range(40):
        rr = _unequal(rng, p, r * (1.0 - 0.3 * min(z / max(top, 1e-6), 1.0)), 0.25)
        if z + rr >= top:
            made.append(_ball(centre.x, centre.y, max(top - rr, 0.4 * rr), rr))
            break
        made.append(_ball(centre.x, centre.y, z, rr))
        centre += Vector((rng.gauss(0.0, 0.12), rng.gauss(0.0, 0.12), 0.0)) * rr
        z += rr * rng.uniform(0.5, 0.7)
    return made


def _cumulus(rng, p):
    """Cumulus: a dome of a few wide rising towers on one flat base, the
    tallest near the middle, the others shouldering it, their upper parts
    bulging like a cauliflower."""
    _l, w, h = _aspect(p)
    a, b = 0.5, 0.5 * w
    side = min(a, b)
    body = []
    places = sorted(_scatter(rng, rng.randint(3, 5), a * 0.45, b * 0.45), key=lambda q: (q.x / a) ** 2 + (q.y / b) ** 2)
    for i, q in enumerate(places):
        off = min(1.0, (q.x / a) ** 2 + (q.y / b) ** 2)
        top = h * (1.0 - 0.6 * off) * (1.0 if i == 0 else rng.uniform(0.6, 0.85))
        r = _unequal(rng, p, side * rng.uniform(0.55, 0.7), 0.25)
        body += _turret(rng, p, q, max(top, 1.2 * r), r)
    body = _joined(_distorted(rng, p, body))
    # The cauliflower: lumps on the upper parts only, half sunk in them; the
    # base stays smooth.
    upper = [blob for blob in body if blob[0].z > 0.2 * h]
    return body + _lumps(rng, p, upper, per=(2, 3), shrink=(0.5, 0.65), reach=(0.85, 1.0), lowest=-0.3)


def _cell(rng, p, x, y, r, top, wide=1.0):
    """A rounded mass of a layer: one flattened sphere as high as `top`, with
    one or two smaller ones on its crown."""
    made = [_ball(x, y, top * 0.3, r, min(1.0, top * 0.75 / r), wide)]
    for _ in range(rng.randint(1, 2)):
        rr = r * rng.uniform(0.45, 0.65)
        made.append(_ball(x + rng.uniform(-0.35, 0.35) * r, y + rng.uniform(-0.35, 0.35) * r * wide,
                          max(top - rr * 0.8, rr * 0.5), rr, 0.85))
    return made


def _edge(rng, x, y, a, b, ragged=0.3):
    """Whether a place is inside an ellipse whose edge is broken by up to
    `ragged`."""
    return (x / a) ** 2 + (y / b) ** 2 <= 1.0 - rng.uniform(0.0, ragged)


def _stratocumulus(rng, p):
    """Stratocumulus: a layer of large rounded masses packed in rolls across
    it, merged in most places, with a few gaps, flat underneath."""
    _l, w, h = _aspect(p)
    a, b = 0.5, 0.5 * w
    cell = rng.uniform(0.1, 0.13)
    rows = max(2, round(2.0 * b / (cell * 1.05)))
    gap = 2.0 * b / rows
    body = []
    for j in range(rows):
        y0 = -b + (j + 0.5) * gap
        phase, bend = rng.uniform(0.0, math.tau), rng.uniform(0.15, 0.35) * gap
        x = -a + rng.uniform(0.0, 0.5) * cell
        while x < a:
            y = y0 + bend * math.sin(x * math.tau * 1.5 + phase)
            if _edge(rng, x, y, a, b) and rng.random() > 0.1:
                r = _unequal(rng, p, cell * rng.uniform(0.55, 0.7), 0.3)
                body += _cell(rng, p, x, y, r, h * rng.uniform(0.55, 1.0), gap / cell * rng.uniform(0.9, 1.1))
            x += cell * rng.uniform(0.85, 1.05)
    body = _joined(_distorted(rng, p, body or [_ball(0.0, 0.0, 0.0, 0.1, 0.5)]))
    return body + _lumps(rng, p, [blob for blob in body if blob[0].z > 0.4 * h], rounds=min(p["lumps"], 1),
                         per=(1, 2), shrink=(0.4, 0.55), flat=0.8, lowest=0.0)


def _altocumulus(rng, p):
    """Altocumulus: a layer of separate rounded cloudlets in loose wavy
    rows, each a small cluster, of unequal sizes."""
    _l, w, h = _aspect(p)
    a, b = 0.5, 0.5 * w
    step = rng.uniform(0.11, 0.14)
    rows = max(2, round(2.0 * b / step))
    lets = []
    for j in range(rows):
        y0 = -b + (j + 0.5) * 2.0 * b / rows
        phase = rng.uniform(0.0, math.tau)
        x = -a + rng.uniform(0.0, 0.6) * step
        while x < a:
            y = y0 + 0.25 * step * math.sin(x * math.tau * 2.0 + phase) + rng.uniform(-0.15, 0.15) * step
            if _edge(rng, x, y, a, b, 0.35) and rng.random() > 0.12:
                r = _unequal(rng, p, step * rng.uniform(0.28, 0.38), 0.4)
                top = min(h, r * 0.8)
                lets.append(_ball(x, y, top * 0.3, r, 0.45, rng.uniform(0.85, 1.15)))
                for _ in range(rng.randint(2, 4)):
                    angle = rng.uniform(0.0, math.tau)
                    rr = r * rng.uniform(0.5, 0.75)
                    lets.append(_ball(x + math.cos(angle) * r * 0.6, y + math.sin(angle) * r * 0.6,
                                      top * rng.uniform(0.3, 0.55), rr, 0.6))
            x += step * rng.uniform(0.85, 1.15)
    lets = _distorted(rng, p, lets or [_ball(0.0, 0.0, 0.0, 0.1, 0.6)])
    return lets + _lumps(rng, p, lets[::3], rounds=min(p["lumps"], 1), per=(1, 2), shrink=(0.4, 0.55), flat=0.8,
                         lowest=0.0)


def _patches(rng, scale):
    """A smooth noise on the ground plane, about -1 to 1: where a thin
    layer is, and where it has holes."""
    waves = [(rng.uniform(0.6, 1.4) * scale * math.tau, rng.uniform(0.6, 1.4) * scale * math.tau,
              rng.uniform(0.0, math.tau)) for _ in range(4)]
    return lambda x, y: sum(math.sin(fx * x + 0.7 * fy * y + c) * math.cos(fy * y - 0.5 * fx * x + c)
                            for fx, fy, c in waves) / 2.0


def _cirrocumulus(rng, p):
    """Cirrocumulus: a thin high sheet rippled like sand: crests across the
    wind, each a line of tiny grains drawn out along it, merged in places
    and apart in others, the sheet broken into patches."""
    _l, w, _h = _aspect(p)
    a, b = 0.5, 0.5 * w
    wave = rng.uniform(0.035, 0.05)
    patch = _patches(rng, 2.2)
    bend, swing = rng.uniform(0.6, 1.2), rng.uniform(1.0, 2.5) * wave
    grains = []
    x0 = -a
    while x0 < a:
        phase = rng.uniform(-0.3, 0.3)
        y = -b
        while y < b:
            x = x0 + swing * math.sin(y * math.tau * bend + phase) + rng.uniform(-0.08, 0.08) * wave
            size = 0.5 + 0.5 * patch(x, y)
            if _edge(rng, x, y, a, b, 0.4) and size > rng.uniform(0.15, 0.35):
                r = _unequal(rng, p, wave * rng.uniform(0.25, 0.35) * (0.7 + 0.5 * size), 0.4)
                grains.append(_ball(x, y, rng.uniform(-0.2, 0.2) * r, r, 0.5, rng.uniform(1.2, 1.7)))
            y += wave * rng.uniform(0.35, 0.55)
        x0 += wave * rng.uniform(0.85, 1.15)
    return _distorted(rng, p, grains or [_ball(0.0, 0.0, 0.0, 0.03)])


def _sheet(rng, p, count, flat, lumps_up):
    """A layer: flattened spheres spread evenly over the footprint, run
    together, with lumps on top (`lumps_up` 1) or hanging under (-1)."""
    step = math.sqrt(0.6 / count)
    body = []
    for q in _scatter(rng, count, 0.5, 0.5 * _aspect(p)[1]):
        r = _unequal(rng, p, step * rng.uniform(0.85, 1.2), 0.4)
        body.append(_ball(q.x, q.y, rng.uniform(-0.01, 0.01), r, flat, rng.uniform(0.8, 1.1)))
    body = _joined(_distorted(rng, p, body))
    return body + _lumps(rng, p, body, rounds=min(p["lumps"], 2), per=(1, 2), shrink=(0.4, 0.6),
                         up=lumps_up, flat=0.6, lowest=-0.1)


def _stratus(rng, p):
    """Stratus: a flat, featureless grey layer. Altostratus and Nimbostratus
    are the same layer higher up, or thicker and darker: the Height and the
    material make them (0.22.0)."""
    return _sheet(rng, p, rng.randint(14, 20), 0.18, 1.0)


def _cirrus(rng, p):
    """Cirrus: a few strokes along the wind, each a dense head and a long
    tail that bends and falls away, hooked at its end. Not blobs but strokes,
    (place, radius) along each: a cirrus is a curve object, whose strokes
    the Cloud modifier makes fibres of (nodes.py), and more can be drawn on
    it with the Draw tool."""
    _l, w, h = _aspect(p)
    strokes = []
    for _ in range(rng.randint(3, 6)):
        start = Vector((rng.uniform(-0.5, -0.05), rng.uniform(-0.45, 0.45) * w, rng.uniform(0.0, 0.3) * h))
        heading = rng.uniform(-0.25, 0.25)
        length = rng.uniform(0.45, 0.95)
        hook = rng.uniform(0.2, 0.6) * rng.choice((-1.0, 1.0))
        fall = rng.uniform(0.3, 0.8) * h
        steps = max(6, int(32 * length))
        stroke = []
        for k in range(steps):
            t = k / (steps - 1)
            angle = heading + hook * t ** 2
            q = start + Vector((math.cos(angle), math.sin(angle), 0.0)) * (length * t)
            q.z -= fall * t * t
            # Thick at the head, thinning along the tail.
            stroke.append((q, 1.0 - 0.4 * t + 0.1 * rng.uniform(-1.0, 1.0)))
        strokes.append(stroke)
    return strokes


# (identifier, label, description, builder). The genera in CURVES are
# drawn as strokes into a curve, the others as spheres into a mesh.
GENERA = (
    ('CUMULUS', "Cumulus", "Cumulus: a heaped fair-weather cloud with a flat base", _cumulus),
    ('STRATOCUMULUS', "Stratocumulus", "Stratocumulus: a low layer of large rounded masses in loose rolls",
     _stratocumulus),
    ('ALTOCUMULUS', "Altocumulus", "Altocumulus: a mid-level layer of small rounded cloudlets", _altocumulus),
    ('CIRROCUMULUS', "Cirrocumulus", "Cirrocumulus: a thin high sheet of tiny grains in ripples", _cirrocumulus),
    ('STRATUS', "Stratus", "Stratus: a flat, featureless grey layer, also as Altostratus or Nimbostratus",
     _stratus),
    ('CIRRUS', "Cirrus", "Cirrus: thin high strokes and hooks of ice", _cirrus),
)
BUILDERS = {g[0]: g[3] for g in GENERA}
CURVES = {'CIRRUS'}


def defaults():
    return {name: default for name, default, *_ in SETTINGS}


def blobs(genus, seed, settings=None, dimensions=None):
    p = defaults()
    p.update(settings or {})
    if dimensions is not None:
        length = max(dimensions[0], 1e-6)
        p["aspect"] = (1.0, dimensions[1] / length, dimensions[2] / length)
    return BUILDERS[genus](random.Random(seed), p)


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


# Height ±: the tops rise and sink over the footprint by a smooth noise of
# VARY_BENDS bends across it; never by more than VARY_MOST of the height:
# past half, a place stretched that far up reads as a flame (0.21.0).
VARY_BENDS = 1.2
VARY_MOST = 0.5


def _varied(seed, xyz, dimensions, vary):
    """Heights made unequal, in place: each place's height over the base
    scaled so the tops lie from about Height less `vary` to Height plus it.
    `xyz` is an (n, 3) array in metres, its base on Z = 0."""
    if vary <= 0.0 or len(xyz) == 0:
        return
    wobble = _Wobble(random.Random(seed * 7919 + 17), VARY_BENDS)
    x = xyz[:, 0] / max(dimensions[0], 1e-6)
    y = xyz[:, 1] / max(dimensions[1], 1e-6)
    w = sum(np.sin(f * y + a) + np.sin(f * x + b) for f, a, b in wobble.waves)
    w = w / max(float(np.abs(w).max()), 1e-6)
    xyz[:, 2] *= 1.0 + min(vary, VARY_MOST * dimensions[2]) / max(dimensions[2], 1e-6) * w


def fill_mesh(mesh, genus, seed, dimensions, settings=None, vary=0.0):
    """Write a genus's rough shape into a mesh, in place of whatever it
    holds: `dimensions` (length, width, height) along X, Y and Z, its base
    on Z = 0 and its middle on the Z axis; with `vary`, Height ± in metres,
    its tops from place to place higher or lower than the height. Each seed
    gives another one.

    The spheres are copies of two icospheres put together as arrays: one
    bmesh operator call for each took 60 to 170 ms for a heap, too long for
    a slider that calls this at every step; this takes a few."""
    heap = blobs(genus, seed, settings, dimensions)
    largest = max(r[0] for _c, r in heap)
    verts, faces, count = [], [], 0
    for centre, radii in heap:
        # The large ones show their facets, the small ones only add vertices.
        v, f = _icosphere(3 if radii[0] > 0.5 * largest else (2 if len(heap) < 400 else 1))
        verts.append(v * np.array(radii, dtype=np.float32) + np.array(centre, dtype=np.float32))
        faces.append(f + count)
        count += len(v)
    verts, faces = np.concatenate(verts), np.concatenate(faces)
    # Stretched to the size asked for, measured on the vertices themselves:
    # an icosphere does not reach its radius along every axis.
    low, high = verts.min(axis=0), verts.max(axis=0)
    span = np.maximum(high - low, 1e-6)
    verts = (verts - low) / span * np.array(dimensions, dtype=np.float32)
    verts[:, 0] -= dimensions[0] / 2.0
    verts[:, 1] -= dimensions[1] / 2.0
    _varied(seed, verts, dimensions, vary)
    mesh.clear_geometry()
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set("vertex_index", faces.ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(0, faces.size, 3, dtype=np.int32))
    mesh.update(calc_edges=True)


def fill_curve(curve, genus, seed, dimensions, settings=None, vary=0.0):
    """Write a genus's strokes into a curve, in place of the ones it has:
    poly splines stretched to `dimensions` as fill_mesh stretches a heap,
    each point's radius the stroke's thickness there."""
    strokes = blobs(genus, seed, settings, dimensions)
    places = [q for stroke in strokes for q, _r in stroke]
    low = Vector(tuple(min(q[i] for q in places) for i in range(3)))
    high = Vector(tuple(max(q[i] for q in places) for i in range(3)))
    at = np.array([[(q[i] - low[i]) / max(high[i] - low[i], 1e-6) * dimensions[i] for i in range(3)]
                   for q in places], dtype=np.float64)
    at[:, 0] -= dimensions[0] / 2.0
    at[:, 1] -= dimensions[1] / 2.0
    _varied(seed, at, dimensions, vary)
    curve.splines.clear()
    curve.dimensions = '3D'
    k = 0
    for stroke in strokes:
        spline = curve.splines.new('POLY')
        spline.points.add(len(stroke) - 1)
        for point, (_q, r) in zip(spline.points, stroke):
            point.co = (*at[k], 1.0)
            point.radius = r
            k += 1


def blockout_mesh(genus, seed, dimensions, settings=None, name="Cloud"):
    mesh = bpy.data.meshes.new(name)
    fill_mesh(mesh, genus, seed, dimensions, settings)
    return mesh
