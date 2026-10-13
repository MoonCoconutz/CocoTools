"""A sky of clouds for the price of a few.

A field is a mesh object, a plane to begin with, carrying the Field
modifier: points are scattered over its faces and one of a few clouds is put
on each, turned about Z and scaled. Those few are ordinary clouds, kept in a
collection of their own that neither the viewport nor a render shows. Each is
worked out once however often it is repeated: 5 clouds repeated on 151 places
took 1.1 s to work out where 302 clouds of their own took 74 s (measured on
5.2, both engines draw the copies).

A field holds every kind of cloud that comes many at a time (TYPES), a few
of each in a collection of its own inside the field's. Which kind stands
where is the modifier's doing: an amount for each, and Sorting, which keeps
each to its part of a patch.

The plane stays a mesh: scaled or reshaped in Edit Mode, the clouds follow
its faces. Not every point gets a cloud: a texture cast on the plane leaves
them in patches, as much of the sky as Coverage says, and a vertex group
painted on the plane takes them away where its weight is 0 (the group itself
is _build_field in nodes.py).

A copy's scale does not reach its cloud's Density, which is worked out for
the size the cloud itself has. So the clouds are made at their real size and
the copies scaled only a little.
"""

import math
import random

import bmesh
import bpy
from bpy.app.handlers import persistent

from . import cloud, nodes, shapes

MODIFIER_NAME = "CocoClouds Field"
# A new field's patches are this part of its plane wide.
PATCH_PART = 0.3
# The vertex group Paint Clouds makes. To be painted on, the plane needs
# vertices no farther apart than PAINT_STEP of the clouds' spacing, so a new
# field's plane is made of that many faces; a coarser mesh is cut, into at
# most PAINT_FACES faces. Cutting a mesh moves every cloud: the places are
# drawn face by face.
PAINT_GROUP = "Clouds"
PAINT_STEP = 1.0
PAINT_FACES = 40000

# The types a field is offered for: the clouds that come many at a time,
# apart from one another. Fair-weather cumulus stands in groups and rows
# (cloud streets); stratocumulus and altocumulus are fields of rounded
# masses and cloudlets; fractus is shreds scattered by the wind. Not the
# others: a cumulonimbus is one storm kilometres wide, a congestus tower
# grows alone out of smaller cumulus, a lenticular cloud stands alone over
# its mountain, and stratus is one unbroken sheet.
TYPES = ('CUMULUS', 'PUFF', 'SHEET', 'FLOCK', 'SHREDS')

# How wide a cloud of each type is made, against the Cloud Size asked for,
# which is a Cumulus's: a humilis is a small cumulus and a shred smaller
# still, a patch of stratocumulus or a flock of altocumulus many clouds wide.
SIZE = {'CUMULUS': 1.0, 'PUFF': 0.6, 'SHEET': 2.0, 'FLOCK': 2.0, 'SHREDS': 0.5}

# Voxels across each of a field's clouds, in the viewport and in a render:
# seen from far, they need fewer than a cloud added on its own. A Flock is
# many cloudlets in one cloud, each a seventh of its width, and needs more.
RESOLUTION = {'FLOCK': (96, 192)}
RESOLUTION_ELSE = (48, 128)


def field_modifier(ob):
    if ob is None or ob.type != 'MESH':
        return None
    for mod in ob.modifiers:
        if mod.type == 'NODES' and nodes.is_group(mod.node_group, nodes.FIELD_NAME):
            return mod
    return None


def is_field(ob):
    return field_modifier(ob) is not None


def kinds():
    """(identifier, label) of the kinds of cloud a field holds, as the Field
    group names their inputs."""
    return [(identifier, cloud.cloud_type(identifier)[1]) for identifier in TYPES]


def clouds_of(mod):
    """The collection that holds a field's clouds, or None: the one to show
    and hide. A field from before 0.10.0 has its clouds in it; since, a
    collection for each kind."""
    return cloud.get(mod, "Clouds")


def kind_clouds(mod, label):
    """The collection a field repeats as one kind, or None."""
    name = f"{label} Clouds"
    return cloud.get(mod, name) if cloud.has_input(mod, name) else None


def cloud_objects(mod):
    """Every cloud object a field repeats, each once."""
    found = [clouds_of(mod)] + [kind_clouds(mod, label) for _identifier, label in kinds()]
    seen = {}
    for collection in found:
        for ob in (collection.objects if collection is not None else ()):
            if cloud.is_cloud(ob):
                seen[ob.name] = ob
    return list(seen.values())


def make_field(context, area, size, spacing, count, location):
    """A field of clouds: `count` clouds of each kind in a hidden
    collection, a Cumulus `size` wide and the others by SIZE, and a plane
    `area` wide at `location` that repeats them about `spacing` apart.
    Returns the plane."""
    clouds = bpy.data.collections.new("Field Clouds")
    context.scene.collection.children.link(clouds)
    own = {}
    for row, (identifier, label) in enumerate(kinds()):
        own[label] = bpy.data.collections.new(f"Field {label}")
        clouds.children.link(own[label])
        width = size * SIZE[identifier]
        for i in range(count):
            seed = random.randint(1, cloud.SEEDS)
            name = f"Field {label}"
            ob = bpy.data.objects.new(name, shapes.blockout_mesh(identifier, seed, width, name))
            own[label].objects.link(ob)
            # In rows beside the field, a row to a kind, for when the
            # collection is shown: where they are makes no difference to the
            # copies.
            ob.location = (location[0] + (i - (count - 1) / 2) * width * 1.5,
                           location[1] - row * size * max(SIZE.values()) * 1.5, location[2])
            mod = cloud.set_type(ob, identifier, cloud.HEAP_PUFFS)
            cloud.put(mod, "Seed", seed)
            cloud.set_heap_seed(ob, seed)
            viewport, render = RESOLUTION.get(identifier, RESOLUTION_ELSE)
            cloud.put(mod, "Resolution", render)
            cloud.put(mod, "Viewport Resolution", viewport)
    clouds.hide_viewport = True
    clouds.hide_render = True

    mesh = bpy.data.meshes.new("Cloud Field")
    bm = bmesh.new()
    faces = max(1, min(math.ceil(area / (spacing * PAINT_STEP)), int(math.sqrt(PAINT_FACES))))
    bmesh.ops.create_grid(bm, x_segments=faces, y_segments=faces, size=area / 2)
    bm.to_mesh(mesh)
    bm.free()
    ob = bpy.data.objects.new("Cloud Field", mesh)
    context.collection.objects.link(ob)
    ob.location = location
    mod = ob.modifiers.new(MODIFIER_NAME, 'NODES')
    mod.node_group = nodes.get_group(nodes.FIELD_NAME)
    cloud.put(mod, "Clouds", clouds)
    for label, collection in own.items():
        cloud.put(mod, f"{label} Clouds", collection)
    cloud.put(mod, "Spacing", spacing)
    cloud.put(mod, "Patch Size", area * PATCH_PART)
    for name in ("Scatter Seed", "Patch Seed", "Mix Seed"):
        cloud.put(mod, name, random.randint(1, cloud.SEEDS))
    return ob


def _own_clouds(mod):
    """The modifiers of the clouds a field repeats."""
    return [cloud.cloud_modifier(ob) for ob in cloud_objects(mod)]


def is_current(mod):
    """False for a field on a group of an earlier version, or with a cloud
    on one: its clouds are out of sight, and are the field's to update."""
    return cloud.is_current(mod) and all(cloud.is_current(m) for m in _own_clouds(mod))


def update_field(mod):
    """Move a field to the current group, keeping the settings both have,
    and looking as it did: the one seed of the first group drew the places
    and the clouds alike, and there were clouds on every place. Its clouds
    are moved to theirs.

    A field from before 0.10.0 repeats one collection of clouds, of one
    type. That collection becomes the one of its kind, and the other kinds
    have none, so the field goes on being all of that kind."""
    if not cloud.is_current(mod):
        old = mod.node_group
        kept = {name: cloud.get(mod, name) for name, *_ in nodes.FIELD_INPUTS if nodes.socket_id(old, name)}
        seed = cloud.get(mod, "Seed") if nodes.socket_id(old, "Seed") else None
        mod.node_group = nodes.get_group(nodes.FIELD_NAME)
        for name, value in kept.items():
            cloud.put(mod, name, value)
        labels = [label for _identifier, label in kinds()]
        if not any(f"{label} Clouds" in kept for label in labels) and kept.get("Clouds") is not None:
            had = [cloud.type_of(ob) for ob in kept["Clouds"].objects if cloud.is_cloud(ob)]
            label = next((kind[1] for kind in had if kind is not None and kind[1] in labels), labels[0])
            cloud.put(mod, f"{label} Clouds", kept["Clouds"])
            cloud.put(mod, label, 1.0)
        if seed is not None:
            cloud.put(mod, "Scatter Seed", seed)
            cloud.put(mod, "Mix Seed", seed)
        if "Coverage" not in kept:
            cloud.put(mod, "Coverage", 1.0)
    for own in _own_clouds(mod):
        if not cloud.is_current(own):
            cloud.update_cloud(own)


def look_material(mod):
    """The material a field's clouds have: the first cloud's, which is all
    of theirs unless one was given another."""
    for ob in cloud_objects(mod):
        if cloud.slot_material(ob) is not None:
            return cloud.slot_material(ob)
    return None


def prepare_paint(ob):
    """Make a field's plane ready to be painted on: enough vertices, and a
    vertex group, full, that the field reads. Returns the group."""
    mod = field_modifier(ob)
    mesh = ob.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    longest = max((e.calc_length() for e in bm.edges), default=0.0)
    step = max(cloud.get(mod, "Spacing") * PAINT_STEP, 1e-6)
    # A cut edge has one more piece than cuts, a face that many squared.
    pieces = min(math.ceil(longest / step), int(math.sqrt(PAINT_FACES / max(len(bm.faces), 1))))
    if pieces > 1:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=pieces - 1, use_grid_fill=True)
        bm.to_mesh(mesh)
        mesh.update()
    bm.free()
    name = cloud.get(mod, "Paint")
    group = ob.vertex_groups.get(name) if name else None
    if group is None:
        group = ob.vertex_groups.new(name=PAINT_GROUP)
        group.add(range(len(mesh.vertices)), 1.0, 'REPLACE')
        cloud.put(mod, "Paint", group.name)
    ob.vertex_groups.active_index = group.index
    return group


@persistent
def _show_painted(scene, depsgraph):
    """A field's plane is let through its modifier while it is in Weight
    Paint, and only then (see Show Plane in nodes.py). Looked at after every
    change in the viewport's scene, for the objects that changed and the
    active one."""
    if depsgraph.mode != 'VIEWPORT':
        return
    seen = [update.id.original for update in depsgraph.updates if isinstance(update.id, bpy.types.Object)]
    active = depsgraph.view_layer.objects.active
    if active is not None:
        seen.append(active.original)
    for ob in seen:
        mod = field_modifier(ob)
        if mod is not None and cloud.has_input(mod, "Show Plane"):
            if cloud.get(mod, "Show Plane") != (ob.mode == 'WEIGHT_PAINT'):
                cloud.put(mod, "Show Plane", ob.mode == 'WEIGHT_PAINT')
                # Written from here, the input alone does not have the
                # modifier worked out again (seen without a window).
                ob.update_tag()


def register():
    bpy.app.handlers.depsgraph_update_post.append(_show_painted)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_show_painted)
