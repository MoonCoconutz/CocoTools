"""The rough shape a new cloud starts from: spheres, as a mesh.

The generator. A heaped cloud is built the way Cloud Creator's generator is
described by its author: primary spheres spread over the cloud's footprint,
the footprint broken up by a noise on the ground plane (Distortion), then a
few rounds of secondary spheres (Lumps), each round a ring of smaller ones
on the surface of the last, pushed mostly upwards or, with Spread, every
way. Random Size makes the spheres of a round unequal. A layer cloud is a
sheet of flattened spheres; a cirrus a few strokes of small ones.

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

def _cumulus(rng, p):
    """Cumulus: a few large primary spheres along the length, lumps heaped
    on them."""
    count = rng.randint(4, 7)
    step = 0.8 / count
    body = []
    for i in range(count):
        r = _unequal(rng, p, step * rng.uniform(0.75, 0.95), 0.4)
        x = -0.4 + (i + 0.5 + rng.uniform(-0.2, 0.2)) * step
        body.append(_ball(x, rng.uniform(-0.1, 0.1), r * 0.6, r))
    body = _distorted(rng, p, body)
    return body + _lumps(rng, p, body)


def _cumulonimbus(rng, p):
    """Cumulonimbus: a broad tower, floors of a few spheres round its axis,
    flaring at its top into the anvil, a thick sheet flat on top that
    reaches farther downwind."""
    r = 0.2
    body = []
    place = Vector((0.0, 0.0, r * 0.7))
    lean = Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.08, 0.08), 0.0))
    floors = rng.randint(4, 6)
    for f in range(floors):
        # Each floor a sphere on the axis and a ring round it, narrower higher up.
        ring = rng.randint(3, 5)
        wide = r * (1.0 - 0.25 * f / floors)
        body.append((place.copy(), (wide,) * 3))
        turn = rng.uniform(0.0, math.tau)
        for k in range(ring):
            a = turn + k * math.tau / ring + rng.uniform(-0.3, 0.3)
            rr = _unequal(rng, p, wide * rng.uniform(0.7, 0.9), 0.3)
            body.append((place + Vector((math.cos(a), math.sin(a), rng.uniform(-0.3, 0.3))) * wide * 0.8, (rr,) * 3))
        place = place + (lean + Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), 1.0))) * wide * 0.95
    # The anvil's underside goes into the top floor, or it floats over the tower.
    top = max(body, key=lambda blob: blob[0].z)[0]
    wind = rng.uniform(0.0, math.tau)
    downwind = Vector((math.cos(wind), 0.6 * math.sin(wind), 0.0))
    span, thick = r * 2.3, r * 0.7
    ceiling = top.z + r * 0.85
    centre = Vector((top.x, top.y, 0.0)) + downwind * 0.4 * span
    anvil = [(Vector((centre.x, centre.y, ceiling - thick)), (span, span * 0.85, thick))]
    count = rng.randint(7, 10)
    for i in range(count):
        angle = (i + rng.uniform(-0.3, 0.3)) * math.tau / count
        away = rng.uniform(0.45, 1.0)
        out = Vector((math.cos(angle), 0.8 * math.sin(angle), 0.0)) * away * span
        out *= 1.0 + 0.6 * max(0.0, out.normalized().dot(downwind.normalized()))
        a = _unequal(rng, p, span * rng.uniform(0.4, 0.6), 0.3)
        deep = thick * rng.uniform(0.5, 0.9) * (1.0 - 0.5 * away)
        anvil.append((Vector((centre.x + out.x, centre.y + out.y, ceiling - deep)), (a, a * rng.uniform(0.8, 1.0), deep)))
    body = _distorted(rng, p, body, 0.1)
    return body + anvil + _lumps(rng, p, body, rounds=min(p["lumps"], 2), per=(1, 2), up=0.3)


def _altocumulus(rng, p):
    """Altocumulus: a layer of separate cloudlets in loose rows, each a
    small heap."""
    across, deep = rng.randint(6, 8), rng.randint(5, 7)
    step = 1.0 / across
    lets = []
    for j in range(deep):
        for i in range(across):
            x = (i + 0.5 * (j % 2) + rng.uniform(-0.25, 0.25)) * step - 0.5
            y = (j + rng.uniform(-0.25, 0.25) - 0.5 * (deep - 1)) * step * 0.9
            if (x / 0.5) ** 2 + (y / (0.45 * deep * step)) ** 2 > 1.0 - rng.uniform(0.0, 0.3) or rng.random() < 0.1:
                continue
            r = _unequal(rng, p, step * rng.uniform(0.25, 0.4), 0.4)
            lets.append(_ball(x, y, 0.0, r, 0.6, rng.uniform(0.8, 1.2)))
    lets = _distorted(rng, p, lets or [_ball(0.0, 0.0, 0.0, 0.1, 0.6)])
    return lets + _lumps(rng, p, lets, rounds=min(p["lumps"], 1), per=(1, 3), flat=0.8)


def _cirrocumulus(rng, p):
    """Cirrocumulus: a thin high sheet of many tiny grains in ripples."""
    rows = rng.randint(9, 13)
    grains = []
    bend = rng.uniform(0.04, 0.1)
    for j in range(rows):
        y = (j / (rows - 1) - 0.5) * 0.8
        count = rng.randint(14, 20)
        for i in range(count):
            x = (i + rng.uniform(-0.3, 0.3)) / count - 0.5
            yy = y + bend * math.sin(x * math.tau * 1.3 + j) + rng.uniform(-0.01, 0.01)
            if (x / 0.5) ** 2 + (yy / 0.42) ** 2 > 1.0 - rng.uniform(0.0, 0.25) or rng.random() < 0.15:
                continue
            r = _unequal(rng, p, 0.022, 0.5)
            grains.append(_ball(x, yy, 0.0, r, 0.55, rng.uniform(1.0, 1.8)))
    return _distorted(rng, p, grains or [_ball(0.0, 0.0, 0.0, 0.03)])


def _sheet(rng, p, count, flat, lumps_up):
    """A layer: flattened spheres spread evenly over the footprint, run
    together, with lumps on top (`lumps_up` 1) or hanging under (-1)."""
    step = math.sqrt(0.6 / count)
    body = []
    for q in _scatter(rng, count, 0.5, 0.36):
        r = _unequal(rng, p, step * rng.uniform(0.85, 1.2), 0.4)
        body.append(_ball(q.x, q.y, rng.uniform(-0.01, 0.01), r, flat, rng.uniform(0.8, 1.1)))
    body = _distorted(rng, p, body)
    return body + _lumps(rng, p, body, rounds=min(p["lumps"], 2), per=(1, 2), shrink=(0.4, 0.6),
                         up=lumps_up, flat=0.6, lowest=-0.1)


def _stratus(rng, p):
    """Stratus: a low, flat, featureless grey sheet."""
    return _sheet(rng, p, rng.randint(14, 20), 0.18, 1.0)


def _altostratus(rng, p):
    """Altostratus: a thinner, smoother sheet higher up."""
    return _sheet(rng, p, rng.randint(18, 26), 0.1, 1.0)


def _nimbostratus(rng, p):
    """Nimbostratus: a thick dark layer, ragged underneath."""
    return _sheet(rng, p, rng.randint(14, 20), 0.35, -1.0)


def _cirrus(rng, p):
    """Cirrus: a few thin strokes, each a chain of small spheres along a
    bent path, thickest at its head and trailing off, often hooked."""
    strokes = []
    for _ in range(rng.randint(3, 6)):
        start = Vector((rng.uniform(-0.45, -0.1), rng.uniform(-0.3, 0.3), rng.uniform(-0.05, 0.05)))
        heading = rng.uniform(-0.35, 0.35)
        length = rng.uniform(0.4, 0.9)
        hook = rng.uniform(0.15, 0.5) * rng.choice((-1.0, 1.0))
        steps = int(60 * length)
        for k in range(steps):
            t = k / max(steps - 1, 1)
            angle = heading + hook * t * t
            q = start + Vector((math.cos(angle), math.sin(angle), 0.15 * t * t)) * (length * t)
            r = _unequal(rng, p, 0.018 * (1.0 - 0.75 * t) + 0.004, 0.3)
            strokes.append(_ball(q.x, q.y, q.z, r, 0.7, 1.0))
    return _distorted(rng, p, strokes, 0.1)


# (identifier, label, description, builder)
GENERA = (
    ('CUMULUS', "Cumulus", "Cumulus: a heaped fair-weather cloud with a flat base", _cumulus),
    ('CUMULONIMBUS', "Cumulonimbus", "Cumulonimbus: a thunderstorm tower spreading into a flat anvil", _cumulonimbus),
    ('ALTOCUMULUS', "Altocumulus", "Altocumulus: a mid-level layer of small rounded cloudlets", _altocumulus),
    ('CIRROCUMULUS', "Cirrocumulus", "Cirrocumulus: a thin high sheet of tiny grains in ripples", _cirrocumulus),
    ('STRATUS', "Stratus", "Stratus: a low, flat, featureless grey sheet", _stratus),
    ('ALTOSTRATUS', "Altostratus", "Altostratus: a thin, even mid-level sheet", _altostratus),
    ('NIMBOSTRATUS', "Nimbostratus", "Nimbostratus: a thick dark rain layer, ragged underneath", _nimbostratus),
    ('CIRRUS', "Cirrus", "Cirrus: thin high strokes and hooks of ice", _cirrus),
)
BUILDERS = {g[0]: g[3] for g in GENERA}


def defaults():
    return {name: default for name, default, *_ in SETTINGS}


def blobs(genus, seed, settings=None):
    p = defaults()
    p.update(settings or {})
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


def fill_mesh(mesh, genus, seed, dimensions, settings=None):
    """Write a genus's rough shape into a mesh, in place of whatever it
    holds: `dimensions` (length, width, height) along X, Y and Z, its base
    on Z = 0 and its middle on the Z axis. Each seed gives another one.

    The spheres are copies of two icospheres put together as arrays: one
    bmesh operator call for each took 60 to 170 ms for a heap, too long for
    a slider that calls this at every step; this takes a few."""
    heap = blobs(genus, seed, settings)
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
    mesh.clear_geometry()
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set("vertex_index", faces.ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(0, faces.size, 3, dtype=np.int32))
    mesh.update(calc_edges=True)


def blockout_mesh(genus, seed, dimensions, settings=None, name="Cloud"):
    mesh = bpy.data.meshes.new(name)
    fill_mesh(mesh, genus, seed, dimensions, settings)
    return mesh
