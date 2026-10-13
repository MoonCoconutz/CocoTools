"""The geometry node group CocoClouds runs on.

**Cloud** sits on a mesh object, the cloud's rough shape, and outputs a
volume in its place:

1. the mesh becomes a coarse grid, 1 inside and 0 outside, which a box blur
   turns into a ramp across the surface: 0.5 on it, corners and creases
   rounded. With Puffs low the mesh as it is takes over from that;
2. the cloud's density is that shape read at a position pushed around by a
   large noise (the billows, worked out on a coarse grid and read from it
   where the voxels are fine enough for that), as a depth in metres below
   the surface, plus
   one round lump per cell of a coarse Voronoi (the puffs), minus a fine
   cellular noise (the erosion that gives the cauliflower look);
3. that density is worked out on a sparse grid, in two passes: coarsely over
   all the room the cloud can reach, then finely only where the coarse
   pass found cloud;
4. the result is stored as the grid "density", which Principled Volume reads;
5. a second, coarse grid, "cococlouds", tells the cloud's own material what
   a shader cannot work out: how high in the cloud a place is, and how dense
   the cloud is at its densest (look.py).

Puffs is what lets the mesh be a plain box: at 0 the cloud follows the mesh,
creases and all, and the higher it goes the wider the blur and the larger
the lumps.

Every length is a part of the mesh's longest side, so a cloud looks the same
at any size, and Density is the opacity across that whole side rather than
per metre.

Two things Field to Grid does on 5.2 shape the graph. It leaves its
background value at 1.0, so everything outside the active voxels renders as
a solid box of fog: Set Grid Background puts it back to 0 and must stay right
after it. And it gives a tile of its topology one single value, so every
topology goes through Voxelize Grid first.

The group is built here, never shipped as a .blend, and carries
GROUP_VERSION. A change to the graph bumps it; older groups are left alone
for the clouds already using them (see get_group).
"""

import bpy

GROUP_VERSION = 10
CLOUD_NAME = "CocoClouds Cloud"
# The group a field of clouds runs on (field.py), versioned on its own.
FIELD_VERSION = 3
FIELD_NAME = "CocoClouds Field"
GRID = "density"
# The grid the cloud's material reads besides (see "What the material cannot
# work out" in _build_cloud), and how many coarse voxels it reaches past the
# cloud.
INFO = "cococlouds"
INFO_MARGIN = 2.0
# A third one, as coarse: at each place the way out of the cloud, a vector
# one long, for the material to light the cloud by where EEVEE cannot (the
# preview, look.py). OUT_BLUR is how many coarse voxels the shape is
# blurred over before its slope is taken, OUT_ROUND how much of the plain
# way from the cloud's middle is mixed in: deep inside the slope is nothing.
OUT = "cococlouds_out"
OUT_BLUR = 1
OUT_ROUND = 0.08

# How far the 0-1 sliders reach, as a part of the cloud's size.
BILLOW_REACH = 0.2
EROSION_REACH = 0.2
SOFT_REACH = 0.2

# Voxel sizes of the helper grids, in final voxels (see the two passes).
SHAPE_VOXELS = 2.0
COARSE_VOXELS = 4.0
# The blur that rounds the shape is this many of its own voxels wide.
BLUR_VOXELS = 4.0
# The hull of the coarse pass is grown by this part of a coarse voxel before
# the final pass. Grid to Mesh at a threshold near 0 already puts the hull
# almost a whole coarse voxel outside the last coarse voxel that holds cloud.
HULL_MARGIN = 0.5
# Layers of ever smaller hollows in the erosion. It was a slider, Detail, up
# to 0.12.0: the voxels allow two to four layers whatever it said, and a
# Cumulus at 0 and at 8 differed by 0.2 of a hundredth of a picture.
EROSION_LAYERS = 4.0
# A young cloud (Growth under 1). GROW_SPREAD: the shape is read Growth to
# this power smaller, so under 1 a young cloud is spread wider than it is
# grown. FRAY: how deep, in ramps of the shape, the shreds' noise eats at
# Growth 0, where 1 is as deep as the shape's inside goes; FRAY_POWER bends
# how soon that fades. FRAY_SCALE: shreds across the cloud. FRAY_TWIST: the
# noise's distortion, which pulls round blobs into strands. FRAY_SOFT: how
# much wider the fuzzy edge is at Growth 0, in ramps too (in fuzzy edges, a
# type with a wide one, Shreds, had no young cloud at all under Growth 0.3).
GROW_SPREAD = 0.15
FRAY = 2.8
FRAY_POWER = 1.0
FRAY_SCALE = 5.0
FRAY_TWIST = 1.5
FRAY_SOFT = 2.0
# The smallest cells of the erosion worth working out, in voxels.
CELL_VOXELS = 3.0
# The billows' push is worked out once on voxels PUSH_VOXELS times the final
# ones and read from there, as long as that leaves PUSH_CELLS of those voxels
# to each of the billows' large lumps. Otherwise it is worked out on the
# final voxels themselves (see "The push" in _build_cloud).
PUSH_VOXELS = 4.0
PUSH_CELLS = 16.0

# Puffs at 1 round the shape over this part of its thickness (see `thick`).
# The lumps move the surface by PUFF_LUMP of that, and PUFF_SWELL of it is
# added everywhere to give back the volume the rounding takes off the
# corners. SURFACE_BUDGET is how much of the thickness erosion, edge and
# puffs may use between them.
PUFF_REACH = 0.5
PUFF_LUMP = 1.0
PUFF_SWELL = 0.3
SURFACE_BUDGET = 0.6
# Below this Puffs the blurred shape gives way to the mesh as it is.
PUFF_BLEND = 0.3

# A seed moves the noise by the fraction of seed x SEED_STEP, times SEED_SPAN.
SEED_STEP = (0.7548777, 0.5698403, 0.4301597)
SEED_SPAN = 97.0

# (name, socket type, default, min, max, subtype) for the group's inputs. The
# operators and the UI address them by name.
INPUTS = (
    ("Growth", 'NodeSocketFloat', 1.0, 0.0, 1.0, 'FACTOR'),
    ("Resolution", 'NodeSocketInt', 256, 16, 1024, 'NONE'),
    ("Viewport Resolution", 'NodeSocketInt', 96, 16, 1024, 'NONE'),
    ("Puffs", 'NodeSocketFloat', 0.6, 0.0, 1.0, 'FACTOR'),
    ("Puff Scale", 'NodeSocketFloat', 3.0, 0.0, 1000.0, 'NONE'),
    ("Billows", 'NodeSocketFloat', 0.4, 0.0, 1.0, 'FACTOR'),
    ("Billow Scale", 'NodeSocketFloat', 2.0, 0.0, 1000.0, 'NONE'),
    ("Erosion", 'NodeSocketFloat', 0.4, 0.0, 1.0, 'FACTOR'),
    ("Erosion Scale", 'NodeSocketFloat', 4.0, 0.0, 1000.0, 'NONE'),
    ("Softness", 'NodeSocketFloat', 0.05, 0.0, 1.0, 'FACTOR'),
    ("Flat Base", 'NodeSocketFloat', 0.0, 0.0, 0.95, 'FACTOR'),
    ("Seed", 'NodeSocketInt', 0, -100000, 100000, 'NONE'),
    ("Density", 'NodeSocketFloat', 150.0, 0.0, 10000.0, 'NONE'),
    ("Material", 'NodeSocketMaterial', None, None, None, None),
)

DESCRIPTIONS = {
    "Growth": ("How far the cloud has grown: nothing at 0, its whole shape at 1. A young cloud is thin, "
               "frayed shreds over part of the shape, which thicken and close up into the cloud as it grows"),
    "Resolution": "Voxels along the cloud's longest side in a render",
    "Viewport Resolution": "Voxels along the cloud's longest side in the viewport",
    "Puffs": "How far the cloud leaves the mesh for round lumps of its own. 0 follows the mesh",
    "Puff Scale": "Number of round lumps across the cloud",
    "Billows": "How far the large lumps push the shape around",
    "Billow Scale": "Number of large lumps across the cloud",
    "Erosion": "How deep the small hollows eat into the surface",
    "Erosion Scale": "Number of small hollows across the cloud",
    "Softness": "Thickness of the cloud's fuzzy edge",
    "Flat Base": "Part of the cloud's height cut flat at the bottom",
    "Seed": "Another variation of the same cloud: it moves the noise, not the mesh",
    "Density": "How opaque the cloud is across its longest side, whatever its size",
    "Material": "Volume material of the cloud. CocoClouds keeps it equal to the object's first material slot",
}


# Inputs the modifier does not show: CocoClouds sets them by itself.
HIDDEN = ("Material", "Show Plane", "Clouds")


class Graph:
    """Terse node building: values in `ins` that are sockets get linked,
    anything else is written to default_value. Keys are input names, or
    indices where a node repeats a name (Math, Vector Math)."""

    def __init__(self, ng):
        self.ng = ng
        self.x = 0

    def node(self, type_, ins=None, **props):
        n = self.ng.nodes.new(type_)
        for key, value in props.items():
            setattr(n, key, value)
        n.location = (self.x, 0)
        self.x += 200
        self.link(n, ins or {})
        return n

    def link(self, n, ins):
        for key, value in ins.items():
            sock = n.inputs[key]
            if isinstance(value, bpy.types.NodeSocket):
                self.ng.links.new(value, sock)
            else:
                sock.default_value = value

    def math(self, op, a, b=None, clamp=False):
        ins = {0: a}
        if b is not None:
            ins[1] = b
        return self.node("ShaderNodeMath", ins, operation=op, use_clamp=clamp).outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        ins = {0: a}
        if b is not None:
            ins[1] = b
        if scale is not None:
            ins[3] = scale
        return self.node("ShaderNodeVectorMath", ins, operation=op).outputs[0]

    def separate(self, vector):
        return self.node("ShaderNodeSeparateXYZ", {0: vector}).outputs

    def max3(self, vector):
        v = self.separate(vector)
        return self.math('MAXIMUM', self.math('MAXIMUM', v["X"], v["Y"]), v["Z"])


def arrange(ng):
    """Lay a group's nodes out to be read: in columns from its input on the
    left to its output on the right, a node one column before the first of
    those it feeds, and in each column in the order of what they feed.
    Graph puts every node on one line."""
    feeds = {n: [] for n in ng.nodes}
    for link in ng.links:
        if link.to_node not in feeds[link.from_node]:
            feeds[link.from_node].append(link.to_node)
    column = {}

    def place(n):
        if n not in column:
            column[n] = 0                                # a loop would stop here; there are none
            column[n] = 1 + max((place(t) for t in feeds[n]), default=-1)
        return column[n]

    for n in ng.nodes:
        place(n)
    last = max(column.values(), default=0)
    for n in ng.nodes:
        if n.bl_idname == "NodeGroupInput":
            column[n] = last
    height = {}
    for n in ng.nodes:
        shown = sum(1 for s in list(n.inputs) + list(n.outputs) if s.enabled and not s.hide)
        height[n] = 60.0 + 22.0 * shown
    y = {}
    for at in range(last + 1):
        here = [n for n in ng.nodes if column[n] == at]
        # Each as high as the nodes it feeds, as far as the others leave room.
        here.sort(key=lambda n: -(sum(y[t] for t in feeds[n]) / len(feeds[n]) if feeds[n] else 0.0))
        top = sum(height[n] + 30.0 for n in here) / 2.0
        for n in here:
            y[n] = top - height[n] / 2.0
            n.location = (-at * 220.0, top)
            top -= height[n] + 30.0


def _new_group(name, inputs, descriptions):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.is_modifier = True
    ng["cococlouds_version"] = _VERSIONS[name]
    ng["cococlouds_kind"] = name
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    for name_, stype, default, lo, hi, subtype in inputs:
        s = ng.interface.new_socket(name_, in_out='INPUT', socket_type=stype,
                                    description=descriptions.get(name_, ""))
        if subtype and subtype != 'NONE':
            s.subtype = subtype
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value, s.max_value = lo, hi
        # The cloud's material is set in the object's material slot, like
        # any object's, and copied here (cloud.py): shown in the modifier
        # as well, it would be a second place to set it that does not hold.
        # A field's plane is shown while it is painted on (field.py).
        if name_ in HIDDEN:
            s.hide_in_modifier = True
    return ng


def _build_cloud():
    ng = _new_group(CLOUD_NAME, INPUTS, DESCRIPTIONS)

    g = Graph(ng)
    gi = g.node("NodeGroupInput").outputs
    go = g.node("NodeGroupOutput")
    mesh = gi["Geometry"]

    # The yardstick: the shape's longest side, in the object's own space.
    box = g.node("GeometryNodeBoundBox", {"Geometry": mesh}).outputs
    dims = g.vmath('SUBTRACT', box["Max"], box["Min"])
    middle_of_box = g.vmath('SCALE', g.vmath('ADD', box["Min"], box["Max"]), scale=0.5)
    size = g.math('MAXIMUM', g.max3(dims), 1e-4)

    viewport = g.node("GeometryNodeIsViewport").outputs[0]
    resolution = g.node("GeometryNodeSwitch", {
        "Switch": viewport, "False": gi["Resolution"], "True": gi["Viewport Resolution"],
    }, input_type='INT').outputs[0]
    voxel = g.math('DIVIDE', size, resolution)

    # The shape's thickness: three times its volume over its area. That is
    # a sphere's radius, 1.5 times a long cylinder's, and for a blockout of
    # several boxes about half the width of one of them. A mesh that is not
    # closed has no volume, hence the limits.
    def total(field):
        return g.node("GeometryNodeAttributeStatistic", {
            "Geometry": mesh, "Attribute": field}, data_type='FLOAT', domain='FACE').outputs["Sum"]

    face_area = g.node("GeometryNodeInputMeshFaceArea").outputs[0]
    outward = g.vmath('DOT_PRODUCT', g.node("GeometryNodeInputPosition").outputs[0],
                      g.node("GeometryNodeInputNormal").outputs[0]).node.outputs["Value"]
    volume3 = g.math('ABSOLUTE', total(g.math('MULTIPLY', outward, face_area)))
    thick = g.math('DIVIDE', volume3, g.math('MAXIMUM', total(face_area), 1e-9))
    thick = g.math('MINIMUM', g.math('MAXIMUM', thick, g.math('MULTIPLY', size, 0.05)),
                   g.math('MULTIPLY', size, 0.5))

    reach = g.math('MULTIPLY', g.math('MULTIPLY', gi["Billows"], BILLOW_REACH), size)
    erosion = g.math('MULTIPLY', g.math('MULTIPLY', gi["Erosion"], EROSION_REACH), size)
    soft = g.math('MULTIPLY', g.math('MULTIPLY', gi["Softness"], SOFT_REACH), size)
    # Puffs reach a part of the thickness rather than of the size: measured
    # on the whole blockout, its thinner pieces would be rounded away.
    puff = g.math('MULTIPLY', g.math('MULTIPLY', gi["Puffs"], PUFF_REACH), thick)
    # Erosion, fuzzy edge and puffs all move the surface, and together they
    # may not go deeper than the shape is thick, or nothing of it is left:
    # past SURFACE_BUDGET of the thickness all three shrink alike.
    wanted = g.math('ADD', g.math('ADD', erosion, soft), g.math('MULTIPLY', puff, PUFF_LUMP * (1.0 + PUFF_SWELL)))
    fit = g.math('MINIMUM', 1.0, g.math('DIVIDE', g.math('MULTIPLY', thick, SURFACE_BUDGET),
                                        g.math('MAXIMUM', wanted, 1e-9)))
    erosion = g.math('MULTIPLY', erosion, fit)
    soft = g.math('MAXIMUM', g.math('MULTIPLY', soft, fit), voxel)
    puff = g.math('MULTIPLY', puff, fit)
    # The surface needs this much room on each side: the deepest hollow plus
    # the fuzzy edge, or a fully eroded spot could never reach full density
    # below it.
    gradient = g.math('ADD', erosion, soft)

    def solid(mesh_, cell, gradient_):
        return g.node("GeometryNodeMeshToDensityGrid", {
            "Mesh": mesh_, "Density": 1.0, "Voxel Size": cell, "Gradient Width": gradient_,
        }).outputs[0]

    def grown(grid_, distance, cell):
        """The grid's active voxels grown by a distance on every axis,
        corners included, and its tiles turned into voxels: Field to Grid
        gives a tile, a block of 8 x 8 x 8, one single value."""
        steps = g.math('ADD', g.math('CEIL', g.math('DIVIDE', distance, cell)), 1.0)
        wide = g.node("GeometryNodeGridDilateAndErode", {
            "Grid": grid_, "Connectivity": "Vertex", "Steps": steps}).outputs[0]
        return g.node("GeometryNodeGridVoxelize", {"Grid": wide}).outputs[0]

    def to_grid(topology_, field, kind='FLOAT'):
        n = g.node("GeometryNodeFieldToGrid")
        n.grid_items.new(kind, "Value")
        g.link(n, {"Topology": topology_, "Value": field})
        # Background left at its default, 0 for either kind.
        return g.node("GeometryNodeSetGridBackground", {"Grid": n.outputs["Value"]},
                      data_type=kind).outputs[0]

    def room(cell):
        """All the room the cloud can reach, on voxels of a size."""
        return grown(solid(mesh, cell, cell), g.math('ADD', reach, ramp), cell)

    # The rough shape, blurred. A box filter turns the mesh's hard edge into
    # a ramp `ramp` wide on each side of it, 0.5 on the surface, and rounds
    # every corner by about as much: the wider, the less the cloud follows
    # the mesh. The ramp is also all the room the puffs and the erosion have
    # to move the surface in, outwards as well as inwards.
    # Measured on 5.2: Grid Mean with Width W makes the ramp 2 W + 1 voxels
    # wide in all, and the 0.5 sits half a voxel inside the mesh, where Mesh
    # to Density Grid's own one-voxel gradient puts it.
    ramp = g.math('ADD', gradient, g.math('MULTIPLY', puff, PUFF_LUMP * (1.0 + PUFF_SWELL)))
    cell = g.math('MAXIMUM', g.math('DIVIDE', ramp, BLUR_VOXELS), g.math('MULTIPLY', voxel, SHAPE_VOXELS))
    width = g.math('MAXIMUM', g.math('CEIL', g.math('SUBTRACT', g.math('DIVIDE', ramp, cell), 0.5)), 1.0)
    ramp = g.math('MULTIPLY', g.math('ADD', width, 0.5), cell)
    shape = g.node("GeometryNodeGridMean", {
        "Grid": grown(solid(mesh, cell, cell), g.math('ADD', ramp, cell), cell),
        "Width": width, "Iterations": 1}).outputs[0]

    position = g.node("GeometryNodeInputPosition").outputs[0]
    # Noise is read in 3D, the seed moving it somewhere else: a 4D Voronoi
    # has 81 neighbouring cells to visit where 3D has 27. The move stays
    # within SEED_SPAN whatever the seed: added as it is, a seed in the tens
    # of thousands put the noise so far out that single precision broke it
    # into square blocks.
    per_size = g.math('DIVIDE', 1.0, size)
    seed = g.vmath('SCALE', g.vmath('FRACTION', g.vmath('SCALE', SEED_STEP, scale=gi["Seed"])),
                   scale=SEED_SPAN)

    # The push. The billows move every voxel's place before the shape is
    # read there, by a Noise Texture's colour. Worked out on each final
    # voxel that noise is the costliest node of the group, 0.5 s on 3.4
    # million voxels, more than one layer of the erosion: its colour is three
    # noises of three layers each. Next to the voxels of a render it is a
    # smooth thing, so there it is worked out once on voxels PUSH_VOXELS
    # larger, 64 times fewer, and the final voxels read it from that grid.
    #
    # Only where the grid is fine enough for the noise, though. Between two
    # of its voxels the push is a straight line, and the noise's finest
    # layer has 4 x Billow Scale lumps across the cloud: with about one grid
    # voxel to such a lump, the lumps turn into flat facets as large as the
    # grid's voxels. 0.5.0 read the push from the grid always, and a cloud
    # with Billow Scale 6 came out of the viewport's 96 voxels as crumpled
    # paper. So the grid is used when it has PUSH_CELLS voxels to a lump of
    # the first layer, which is four to a lump of the finest; the cloud then
    # has Billow Scale x PUSH_CELLS x PUSH_VOXELS voxels or more across, 128
    # at Billow Scale 2. Below that the push is worked out on every voxel,
    # as it was up to 0.4.0. With Billows at 0 nothing of it is worked out.
    billow = g.node("ShaderNodeTexNoise", {
        "Vector": g.vmath('ADD', g.vmath('SCALE', position, scale=per_size), seed),
        "Scale": gi["Billow Scale"], "Detail": 2.0, "Roughness": 0.5,
    }, noise_dimensions='3D').outputs["Color"]
    # The colour sits around 0.5 and seldom leaves 0.2 to 0.8: stretched and
    # clamped, the push uses its whole reach and never goes past it.
    push = g.vmath('SCALE', g.vmath('SUBTRACT', billow, (0.5, 0.5, 0.5)), scale=1.0 / 0.3)
    push = g.vmath('MINIMUM', g.vmath('MAXIMUM', push, (-1.0, -1.0, -1.0)), (1.0, 1.0, 1.0))
    coarse = g.math('MULTIPLY', voxel, COARSE_VOXELS)
    coarse_room = room(coarse)
    calm = g.math('MULTIPLY', voxel, PUSH_VOXELS)
    pushes = to_grid(coarse_room if PUSH_VOXELS == COARSE_VOXELS else room(calm), push, 'VECTOR')
    read = g.node("GeometryNodeSampleGrid", {"Grid": pushes, "Position": position},
                  data_type='VECTOR').outputs[0]
    smooth = g.math('GREATER_THAN', resolution,
                    g.math('SUBTRACT', g.math('MULTIPLY', gi["Billow Scale"], PUSH_CELLS * PUSH_VOXELS), 0.5))
    push = g.node("GeometryNodeSwitch", {"Switch": smooth, "False": push, "True": read},
                  input_type='VECTOR').outputs[0]
    pushed = g.node("GeometryNodeSwitch", {
        "Switch": g.math('GREATER_THAN', gi["Billows"], 1e-4), "False": position,
        "True": g.vmath('ADD', position, g.vmath('SCALE', push, scale=reach)),
    }, input_type='VECTOR').outputs[0]
    # Growth, the first half. The shape is read as if it were the whole
    # cloud made smaller about the middle of its base: a place is asked what
    # the full shape has that many times farther from there. Only the shape:
    # the noises are read where the place is, so lumps and hollows keep
    # their size. Smaller by Growth to GROW_SPREAD, so a young cloud already
    # lies over much of its place. At 1 nothing is changed, a Switch leaving
    # the place as it is. The second half, the fraying, is with the erosion.
    seat = g.node("ShaderNodeCombineXYZ", {
        "X": g.separate(middle_of_box)["X"], "Y": g.separate(middle_of_box)["Y"],
        "Z": g.separate(box["Min"])["Z"]}).outputs[0]
    growing = g.math('LESS_THAN', gi["Growth"], 0.9999)
    grown_to = g.math('POWER', g.math('MAXIMUM', gi["Growth"], 1e-3), GROW_SPREAD)
    pushed = g.node("GeometryNodeSwitch", {
        "Switch": growing, "False": pushed,
        "True": g.vmath('ADD', seat, g.vmath('SCALE', g.vmath('SUBTRACT', pushed, seat),
                                             scale=g.math('DIVIDE', 1.0, grown_to))),
    }, input_type='VECTOR').outputs[0]
    blurred = g.math('MULTIPLY', g.math('SUBTRACT', g.node("GeometryNodeSampleGrid", {
        "Grid": shape, "Position": pushed}).outputs[0], 0.5), g.math('MULTIPLY', ramp, 2.0))
    blurred = g.math('ADD', blurred, g.math('MULTIPLY', cell, 0.5))

    # The blur fills every crease of the mesh, and a heap of spheres is all
    # creases: they are what makes it read as a cloud. So below PUFF_BLEND
    # the blurred shape gives way to the mesh as it is, the depth Mesh to
    # Density Grid measures inwards from the surface, and at Puffs 0 nothing
    # of the blur is left. Each Switch takes a single value, so only the
    # shapes really used are worked out.
    crisp = g.math('MULTIPLY', g.node("GeometryNodeSampleGrid", {
        "Grid": solid(mesh, g.math('MULTIPLY', voxel, SHAPE_VOXELS), gradient),
        "Position": pushed}).outputs[0], gradient)
    follow = g.math('SUBTRACT', 1.0, g.math('DIVIDE', gi["Puffs"], PUFF_BLEND), clamp=True)
    mixed = g.node("ShaderNodeMix", {0: follow, 2: blurred, 3: crisp}, data_type='FLOAT').outputs[0]
    depth = g.node("GeometryNodeSwitch", {
        "Switch": g.math('GREATER_THAN', follow, 0.999), "False": mixed, "True": crisp,
    }, input_type='FLOAT').outputs[0]
    depth = g.node("GeometryNodeSwitch", {
        "Switch": g.math('LESS_THAN', follow, 0.001), "False": depth, "True": blurred,
    }, input_type='FLOAT').outputs[0]

    # Puffs: one round lump for each cell of a coarse Voronoi, its centre
    # pushed out and its border pulled in. Not worked out with Puffs at 0.
    lumps = g.node("ShaderNodeTexVoronoi", {
        "Vector": g.vmath('ADD', g.vmath('SCALE', pushed, scale=per_size), g.vmath('SCALE', seed, scale=-1.7)),
        "Scale": gi["Puff Scale"], "Detail": 0.0,
    }, voronoi_dimensions='3D', feature='F1').outputs["Distance"]
    dome = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', lumps, lumps), 2.0))
    dome = g.math('MAXIMUM', dome, -1.0)
    lumps = g.math('MULTIPLY', g.math('ADD', dome, PUFF_SWELL), g.math('MULTIPLY', puff, PUFF_LUMP))
    depth = g.node("GeometryNodeSwitch", {
        "Switch": g.math('GREATER_THAN', gi["Puffs"], 1e-4), "False": depth,
        "True": g.math('ADD', depth, lumps),
    }, input_type='FLOAT').outputs[0]

    # A layer of the erosion whose cells are smaller than CELL_VOXELS voxels
    # cannot be told from grain, and each layer costs as much as the first:
    # so the layers stop where the voxels do. Layer k has Erosion Scale x 2^k
    # cells across the cloud, the cloud has `resolution` voxels across. The
    # viewport, with fewer voxels, works out fewer layers than a render.
    layers = g.math('LOGARITHM', g.math('DIVIDE', resolution, g.math(
        'MAXIMUM', g.math('MULTIPLY', gi["Erosion Scale"], CELL_VOXELS), 1e-3)), 2.0)
    detail = g.math('MAXIMUM', g.math('MINIMUM', EROSION_LAYERS, layers), 0.0)
    cells = g.node("ShaderNodeTexVoronoi", {
        "Vector": g.vmath('ADD', g.vmath('SCALE', pushed, scale=per_size), seed),
        "Scale": gi["Erosion Scale"], "Detail": detail, "Roughness": 0.6,
    }, voronoi_dimensions='3D', feature='F1', normalize=True).outputs["Distance"]
    # Growth, the second half. Made smaller alone, a young cloud is the
    # grown one seen small: as solid, as sharp. So a noise eats into it as
    # well, deeper than the shape's inside goes at Growth 0 and not at all
    # at 1: what is left of a young cloud is the shreds where that noise is
    # low, and they widen and close up as it grows. Its fuzzy edge is wider
    # too, so the shreds are thin haze and the cloud gets its body last.
    # The noise is read where the place is, like the others, and not worked
    # out at all at Growth 1.
    young = g.math('SUBTRACT', 1.0, gi["Growth"], clamp=True)
    shreds = g.node("ShaderNodeTexNoise", {
        "Vector": g.vmath('ADD', g.vmath('SCALE', position, scale=per_size), g.vmath('SCALE', seed, scale=2.3)),
        "Scale": FRAY_SCALE, "Detail": 3.0, "Roughness": 0.6, "Distortion": FRAY_TWIST,
    }, noise_dimensions='3D').outputs["Fac"]
    # The noise sits around 0.5 and seldom leaves 0.25 to 0.75.
    shreds = g.math('MULTIPLY', g.math('SUBTRACT', shreds, 0.25), 2.0, clamp=True)
    fray = g.math('MULTIPLY', g.math('MULTIPLY', g.math('POWER', young, FRAY_POWER), FRAY), ramp)
    depth = g.node("GeometryNodeSwitch", {
        "Switch": growing, "False": depth,
        "True": g.math('SUBTRACT', depth, g.math('MULTIPLY', shreds, fray)),
    }, input_type='FLOAT').outputs[0]
    edge = g.math('ADD', soft, g.math('MULTIPLY', g.math('MULTIPLY', young, FRAY_SOFT), ramp))
    density = g.math('DIVIDE', g.math('SUBTRACT', depth, g.math('MULTIPLY', cells, erosion)),
                     edge, clamp=True)

    # Flat base: fade to nothing below a height, over a wider band than the
    # edge elsewhere, since a real base is flat but hazy. Off at 0.
    z = g.separate(position)["Z"]
    floor = g.math('ADD', g.separate(box["Min"])["Z"],
                   g.math('MULTIPLY', gi["Flat Base"], g.separate(dims)["Z"]))
    above = g.math('DIVIDE', g.math('SUBTRACT', z, floor), gradient, clamp=True)
    above = g.math('MAXIMUM', above, g.math('LESS_THAN', gi["Flat Base"], 1e-4))
    density = g.math('MULTIPLY', density, above)
    # Nothing at all at Growth 0, where the smallest cloud the division
    # above allows could still leave a voxel.
    density = g.math('MULTIPLY', density, g.math('GREATER_THAN', gi["Growth"], 1e-4))

    # Density is per metre in a render, and a scaled object is not
    # compensated, so divide by the size the cloud really has in the scene.
    this = g.node("GeometryNodeSelfObject").outputs[0]
    scale = g.node("GeometryNodeObjectInfo", {"Object": this},
                   transform_space='ORIGINAL').outputs["Scale"]
    world_size = g.math('MULTIPLY', size, g.math('MAXIMUM', g.max3(g.vmath('ABSOLUTE', scale)), 1e-6))
    scaled = g.math('MULTIPLY', density, g.math('DIVIDE', gi["Density"], world_size))

    # Two passes. The billows can carry the cloud `reach` away from the mesh
    # on any axis, and most of the voxels that far out end up empty. So the
    # field is first worked out on coarse voxels over all of that room; the
    # hull of what came out non-empty, one coarse voxel wider, is then the
    # only place the fine voxels are worked out. (HULL_MARGIN of a coarse
    # voxel wider, to be exact.)
    rough = to_grid(coarse_room, density)
    hull = g.node("GeometryNodeGridToMesh", {
        "Grid": rough, "Threshold": 0.001, "Adaptivity": 0.0}).outputs[0]
    grid = to_grid(grown(solid(hull, voxel, voxel), g.math('MULTIPLY', coarse, HULL_MARGIN), voxel), scaled)
    volume = g.node("GeometryNodeStoreNamedGrid", {"Name": GRID, "Grid": grid}).outputs[0]

    # What the material cannot work out. A shader sees one place of the
    # volume at a time: not where the cloud begins and ends, nor how dense
    # it gets, which changes with the cloud's size (Density is across the
    # whole cloud). So a second grid tells it, a vector at each voxel: X the
    # height in the cloud, 0 at its base and 1 at its top; Y one over the
    # density of a voxel deep inside; Z 1, which tells a cloud from a volume
    # without this grid, where a shader reads 0 (measured on 5.2, both
    # engines, also on a copy made by another object's nodes).
    # X is a straight line and the others are flat, so voxels as coarse as
    # the first pass's hold them exactly. X is left to run below 0 and past
    # 1 for that: cut off here, it was a hundredth out next to the cut. They
    # reach INFO_MARGIN coarse voxels past the hull: a shader reads between
    # voxels, and at the last one it would mix in the nothing outside.
    info_room = grown(solid(hull, coarse, coarse), g.math('MULTIPLY', coarse, INFO_MARGIN), coarse)
    top = g.separate(box["Max"])["Z"]
    height = g.math('DIVIDE', g.math('SUBTRACT', z, floor),
                    g.math('MAXIMUM', g.math('SUBTRACT', top, floor), 1e-6))
    per_full = g.math('DIVIDE', world_size, g.math('MAXIMUM', gi["Density"], 1e-6))
    info = to_grid(info_room, g.node("ShaderNodeCombineXYZ", {
        "X": height, "Y": per_full, "Z": 1.0}).outputs[0], 'VECTOR')
    # Store Named Grid has a type of its own, FLOAT unless told: left there,
    # the vector is stored as the mean of its three parts.
    volume = g.node("GeometryNodeStoreNamedGrid", {"Volume": volume, "Name": INFO, "Grid": info},
                    data_type='VECTOR_FLOAT').outputs[0]
    # The way out. The coarse pass's density, blurred, falls from the inside
    # of the cloud to its outside, so its slope points in; turned round and
    # made one long it is the way out, as a surface's normal would be. With
    # a little of the plain way from the middle of the cloud mixed in, which
    # is all there is deep inside, where nothing slopes.
    wide = g.node("GeometryNodeGridMean", {
        "Grid": grown(rough, g.math('MULTIPLY', coarse, INFO_MARGIN + OUT_BLUR), coarse),
        "Width": OUT_BLUR, "Iterations": 2}).outputs[0]
    slope = g.node("GeometryNodeSampleGrid", {
        "Grid": g.node("GeometryNodeGridGradient", {"Grid": wide}).outputs[0], "Position": position,
    }, data_type='VECTOR').outputs[0]
    middle = g.vmath('SCALE', g.vmath('ADD', box["Min"], box["Max"]), scale=0.5)
    away = g.vmath('DIVIDE', g.vmath('SUBTRACT', position, middle), g.vmath('MAXIMUM', dims, (1e-6, 1e-6, 1e-6)))
    way = g.vmath('NORMALIZE', g.vmath('ADD', g.vmath('SCALE', slope, scale=g.math('MULTIPLY', coarse, -OUT_BLUR * 2.0)),
                                       g.vmath('SCALE', away, scale=OUT_ROUND * 2.0)))
    volume = g.node("GeometryNodeStoreNamedGrid", {"Volume": volume, "Name": OUT, "Grid": to_grid(info_room, way, 'VECTOR')},
                    data_type='VECTOR_FLOAT').outputs[0]
    out = g.node("GeometryNodeSetMaterial", {
        "Geometry": volume, "Material": gi["Material"]}).outputs[0]
    ng.links.new(out, go.inputs[0])
    return ng


# The kinds of cloud a field holds, each with a collection of its own to
# repeat and an amount: (label, amount to begin with, home). The label is the
# cloud type's (cloud.TYPES) and names the two inputs, "Cumulus" and "Cumulus
# Clouds". Home is where in a patch the kind stands when Sorting is up, from
# 0 at the heart to 1 at the rim: the masses run together and the heaped
# cumulus inside, the small flat ones round them, the shreds at the rim,
# where a patch of real cloud frays out. That order is a choice made here,
# not read off a source.
FIELD_KINDS = (
    ("Cumulus", 1.0, 0.3),
    ("Puff", 1.0, 0.7),
    ("Sheet", 0.5, 0.0),
    ("Flock", 0.5, 0.5),
    ("Shreds", 0.5, 1.0),
)
# How far from its home a kind still stands at Sorting 1, as a part of the
# way from heart to rim: its share falls off as a bell this wide, and never
# to nothing, so a field of one kind keeps a cloud on every place.
SORT_REACH = 0.3

FIELD_INPUTS = (
    ("Clouds", 'NodeSocketCollection', None, None, None, None),
    *((f"{label} Clouds", 'NodeSocketCollection', None, None, None, None) for label, _a, _h in FIELD_KINDS),
    *((label, 'NodeSocketFloat', amount, 0.0, 1.0, 'FACTOR') for label, amount, _h in FIELD_KINDS),
    ("Sorting", 'NodeSocketFloat', 0.7, 0.0, 1.0, 'FACTOR'),
    ("Coverage", 'NodeSocketFloat', 0.6, 0.0, 1.0, 'FACTOR'),
    ("Patch Size", 'NodeSocketFloat', 2500.0, 0.01, 1000000.0, 'DISTANCE'),
    ("Spacing", 'NodeSocketFloat', 600.0, 0.01, 1000000.0, 'DISTANCE'),
    ("Smallest", 'NodeSocketFloat', 0.6, 0.01, 100.0, 'NONE'),
    ("Largest", 'NodeSocketFloat', 1.4, 0.01, 100.0, 'NONE'),
    ("Scatter Seed", 'NodeSocketInt', 0, -100000, 100000, 'NONE'),
    ("Patch Seed", 'NodeSocketInt', 0, -100000, 100000, 'NONE'),
    ("Mix Seed", 'NodeSocketInt', 0, -100000, 100000, 'NONE'),
    ("Paint", 'NodeSocketString', "", None, None, None),
    ("Show Plane", 'NodeSocketBool', False, None, None, None),
)

FIELD_DESCRIPTIONS = {
    "Clouds": ("The collection that holds the field's clouds, a collection for each kind inside. "
               "CocoClouds shows and hides them by it"),
    **{f"{label} Clouds": f"The clouds repeated as {label}. Any cloud linked into the collection joins in"
       for label, _a, _h in FIELD_KINDS},
    **{label: f"How much of the field is {label}, against the other kinds. 0 leaves it out"
       for label, _a, _h in FIELD_KINDS},
    "Sorting": ("0 mixes the kinds by chance. Higher, each keeps to its part of a patch: Sheet and Cumulus "
                "at the heart, Puff round them, Shreds at the rim, also where the paint thins the clouds out"),
    "Coverage": "How much of the sky has clouds: a texture cast on the plane leaves them in patches. 1 is everywhere",
    "Patch Size": "Width of the patches of clouds and of the gaps between them. Below Spacing, clouds go one by one",
    "Spacing": "Least distance between two clouds",
    "Smallest": "Scale of the smallest copy",
    "Largest": "Scale of the largest copy. A copy scaled up is also more opaque",
    "Scatter Seed": "Other places for the clouds to stand",
    "Patch Seed": "Other patches: it moves the texture, not the places",
    "Mix Seed": "Another draw of which cloud stands where, turned and scaled how",
    "Paint": "A vertex group of the plane. Weight 0 takes the clouds away, 1 leaves them to Coverage",
    "Show Plane": "Draw the plane as well as the clouds. CocoClouds turns it on while the plane is painted on",
}

# The texture that says where a field's clouds stand: a Noise Texture of
# this Detail. Its values crowd round 0.5 like a bell, PATCH_SPREAD being
# their standard deviation (measured on 5.2, 640 000 places: 0.0814 at
# Detail 2, the tenth and ninetieth of a hundred at 0.394 and 0.607).
PATCH_DETAIL = 2.0
PATCH_SPREAD = 0.0814
# The noise has one high and one low to each cell of its lattice: a patch of
# clouds, or a gap, is this part of a cell wide.
PATCH_CELL = 0.5


def _build_field():
    """Points scattered over the mesh's faces, a cloud on each of those a
    texture and a painted vertex group leave: of one of the kinds, by their
    amounts and by how deep in its patch the point is, one of that kind's
    collection, turned about Z and scaled."""
    ng = _new_group(FIELD_NAME, FIELD_INPUTS, FIELD_DESCRIPTIONS)
    g = Graph(ng)
    gi = g.node("NodeGroupInput").outputs
    go = g.node("NodeGroupOutput")
    mesh = gi["Geometry"]

    # The painted vertex group, 1 all over where there is none by that name.
    # It is read on the mesh and carried to the points, which get it mixed
    # from the corners of the face each stands on.
    painted = g.node("GeometryNodeInputNamedAttribute", {"Name": gi["Paint"]}, data_type='FLOAT').outputs
    carry = g.node("GeometryNodeCaptureAttribute", {"Geometry": mesh}, domain='POINT')
    carry.capture_items.new('FLOAT', "Weight")
    g.link(carry, {"Weight": g.node("GeometryNodeSwitch", {
        "Switch": painted["Exists"], "False": 1.0, "True": painted["Attribute"]}, input_type='FLOAT').outputs[0]})

    # Poisson disk: the density only has to be more than the spacing lets
    # through.
    points = g.node("GeometryNodeDistributePointsOnFaces", {
        "Mesh": carry.outputs["Geometry"], "Distance Min": gi["Spacing"],
        "Density Max": g.math('DIVIDE', 4.0, g.math('MAXIMUM', g.math('MULTIPLY', gi["Spacing"], gi["Spacing"]), 1e-6)),
        "Seed": gi["Scatter Seed"],
    }, distribute_method='POISSON').outputs["Points"]

    # Where the clouds stand. A noise is read at each point, on the plane's
    # own scale, and turned into a number spread evenly from 0 to 1: the
    # part of all places with less noise than this one. A cloud stands where
    # that is below Coverage times the painted weight, so Coverage is the
    # part of the places kept, and lowering it takes clouds off the rims of
    # the patches first. The noise being a bell, the logistic curve of the
    # same spread is that part to within a hundredth.
    spot = g.vmath('ADD', g.vmath('SCALE', g.node("GeometryNodeInputPosition").outputs[0],
                                  scale=g.math('DIVIDE', PATCH_CELL, g.math('MAXIMUM', gi["Patch Size"], 1e-6))),
                   g.vmath('SCALE', g.vmath('FRACTION', g.vmath('SCALE', SEED_STEP, scale=gi["Patch Seed"])),
                           scale=SEED_SPAN))
    noise = g.node("ShaderNodeTexNoise", {
        "Vector": spot, "Scale": 1.0, "Detail": PATCH_DETAIL, "Roughness": 0.5,
    }, noise_dimensions='3D').outputs["Fac"]
    rank = g.math('DIVIDE', 1.0, g.math('ADD', 1.0, g.math('EXPONENT', g.math(
        'MULTIPLY', g.math('SUBTRACT', noise, 0.5), -1.702 / PATCH_SPREAD))))
    room = g.math('MULTIPLY', gi["Coverage"], carry.outputs["Weight"])
    stands = g.math('LESS_THAN', rank, room)
    # How deep in its patch a point is: 0 at the heart, 1 on the rim, where
    # the next point out has no cloud. The rim is where Coverage puts it and
    # where the paint does, so clouds thinned out by a soft brush are rim
    # clouds too.
    depth = g.math('DIVIDE', rank, g.math('MAXIMUM', room, 1e-6), clamp=True)

    # Drawn by each point's own number, which Distribute Points on Faces
    # gives it and it keeps: a cloud taken away by Coverage leaves the
    # others where they were, turned and scaled as they were.
    def drawn(kind, low, high, offset):
        return g.node("FunctionNodeRandomValue", {
            "Min": low, "Max": high, "Seed": g.math('ADD', gi["Mix Seed"], offset)}, data_type=kind).outputs["Value"]

    # Each kind's share at a point: its amount, less the farther the point
    # is from the kind's home in the patch, none while its collection is
    # empty. The shares are laid end to end and a number drawn along them
    # says which kind stands there.
    kinds, total = [], 0.0
    for label, _amount, home in FIELD_KINDS:
        # Each cloud of the collection an instance of its own, where it was
        # made: a cloud moved, turned or scaled as an object is repeated as
        # if it were not.
        clouds = g.node("GeometryNodeCollectionInfo", {
            "Collection": gi[f"{label} Clouds"], "Separate Children": True, "Reset Children": True}).outputs[0]
        count = g.node("GeometryNodeAttributeDomainSize", {"Geometry": clouds},
                       component='INSTANCES').outputs["Instance Count"]
        away = g.math('DIVIDE', g.math('SUBTRACT', depth, home), SORT_REACH)
        near = g.math('EXPONENT', g.math('MULTIPLY', g.math('MULTIPLY', away, away),
                                         g.math('MULTIPLY', gi["Sorting"], -1.0)))
        share = g.math('MULTIPLY', g.math('MULTIPLY', gi[label], near), g.math('GREATER_THAN', count, 0.5))
        low, total = total, g.math('ADD', total, share)
        kinds.append((clouds, count, low, total))
    pick = g.math('MULTIPLY', g.math('MULTIPLY', drawn('FLOAT', 0.0, 1.0, 4.0), total), 0.999999)

    turn = g.node("FunctionNodeEulerToRotation", {
        0: g.node("ShaderNodeCombineXYZ", {"Z": drawn('FLOAT', 0.0, 6.2831853, 1.0)}).outputs[0]}).outputs[0]
    scale = drawn('FLOAT', gi["Smallest"], gi["Largest"], 3.0)
    both = g.node("GeometryNodeJoinGeometry")
    for clouds, count, low, high in kinds:
        this = g.math('MULTIPLY', g.math('SUBTRACT', 1.0, g.math('LESS_THAN', pick, low)),
                      g.math('LESS_THAN', pick, high))
        copies = g.node("GeometryNodeInstanceOnPoints", {
            "Points": points, "Selection": g.math('MULTIPLY', stands, this), "Instance": clouds,
            "Pick Instance": True, "Instance Index": drawn('INT', 0, g.math('SUBTRACT', count, 1.0), 2.0),
            "Rotation": turn, "Scale": scale,
        }).outputs[0]
        ng.links.new(copies, both.inputs[0])
    # The plane itself is left out: it would render as a grey sheet under
    # the clouds. Weight Paint draws the mesh that comes out of the
    # modifiers, though, and with none there is nothing to paint on, so
    # Show Plane lets it through.
    plane = g.node("GeometryNodeSwitch", {"Switch": gi["Show Plane"], "True": mesh}, input_type='GEOMETRY').outputs[0]
    ng.links.new(plane, both.inputs[0])
    ng.links.new(both.outputs[0], go.inputs[0])
    return ng


_VERSIONS = {CLOUD_NAME: GROUP_VERSION, FIELD_NAME: FIELD_VERSION}
_BUILDERS = {CLOUD_NAME: _build_cloud, FIELD_NAME: _build_field}


def get_group(name=CLOUD_NAME):
    """The current version of the group, building it when missing.

    A group of another version keeps working for the clouds that use it: it
    is renamed out of the way rather than rebuilt, since rebuilding would
    change its socket identifiers and drop every value stored on them."""
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.get("cococlouds_version") == _VERSIONS[name]:
        return ng
    if ng is not None:
        ng.name = f"{name} v{ng.get('cococlouds_version', 0)}"
    ng = _BUILDERS[name]()
    arrange(ng)
    return ng


def is_group(ng, name=CLOUD_NAME):
    """True for any version of the group, whatever it has been renamed to."""
    return ng is not None and ng.get("cococlouds_kind") == name


def is_current(ng):
    """False for a group of an earlier version than this code builds."""
    return ng.get("cococlouds_version") == _VERSIONS.get(ng.get("cococlouds_kind"))


def socket_id(ng, name):
    item = ng.interface.items_tree.get(name)
    return item.identifier if item is not None else None
