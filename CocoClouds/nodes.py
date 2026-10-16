"""The geometry node group CocoClouds runs on.

**Cloud** sits on a mesh object, the cloud's rough shape, and outputs a
volume in its place. On a curve object (a Cirrus) each stroke is first made
a tube, Stroke Thickness wide and thinning towards its end, and the tubes are
the rough shape. It works the way Cloud Creator Lite does (read in its
own file, rebuilt here, nothing of it copied):

1. the mesh is filled with points on a grid, Spacing of a ball apart;
2. one noise moves every point and sets its size: a ball as large as Puff
   Size where the noise is high, small where it is low. The noise moves the
   points more the higher they are, so the base stays where it is;
3. Flat Base shrinks the balls near the floor and drops the ones under it;
   Growth shrinks and drops balls by an order that runs from the middle of
   the base outwards, broken up by a second noise;
4. the balls become a volume, "density", their union with soft edges.

That is all that shapes a cloud: the noise both moves and sizes the balls,
so its settings work together, where the earlier cloud had four ways of
moving one surface that fought each other.

Two coarse grids go with it, for the material (look.py): "cococlouds", how
high in the cloud a place is, and "cococlouds_out", the way out of the cloud
at each place, by which the material lights the cloud in EEVEE.

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

GROUP_VERSION = 16
CLOUD_NAME = "CocoClouds Cloud"
GRID = "density"
# The grid the cloud's material reads besides, and how many coarse voxels it
# reaches past the cloud: a shader reads between voxels.
INFO = "cococlouds"
INFO_MARGIN = 2.0
# The way out of the cloud at each place, a vector one long. OUT_BLUR is how
# many coarse voxels the shape is blurred over before its slope is taken,
# OUT_ROUND how much of the plain way from the cloud's middle is mixed in:
# deep inside the slope is nothing.
OUT = "cococlouds_out"
OUT_BLUR = 1
OUT_ROUND = 0.08
# The helper grids' voxels, in final voxels.
COARSE_VOXELS = 4.0

# Points are this part of the largest ball apart. Closer gives a smoother
# cloud and costs more; Lite has its balls about this far apart for their
# size.
SPACING = 0.4
# The noise's lacunarity, Lite's default; and how far up the cloud, as a
# part of its height, the noise's push grows from nothing to full.
LACUNARITY = 4.0
RISE = 0.25
# Near Flat Base's floor a ball may reach FLAT_SOFT of the largest ball
# below it: a little softness under the flat base.
FLAT_SOFT = 0.3
# Growth: a ball's turn comes by GROW_SHAPE its distance from the middle of
# the base and the rest a noise of GROW_SCALE lumps across the cloud; it
# swells from nothing to its size over GROW_EDGE of Growth.
GROW_SHAPE = 0.55
GROW_SCALE = 3.0
GROW_EDGE = 0.2
# The seed moves the noise in its fourth dimension by the fraction of seed x
# SEED_STEP, times SEED_SPAN: added as it is, a seed in the tens of
# thousands put the noise so far out that single precision broke it.
# A ball is never smaller than BALL_VOXELS voxels: a smaller one does not
# show, and its points would only cost (Puff Size 0.005 took 13 s at the
# viewport's voxels, 0.01 1.8 s).
BALL_VOXELS = 1.0
SEED_STEP = 0.6180339
SEED_SPAN = 97.0
# A stroke's tube: as thick as Stroke Thickness times the point's radius,
# swelling to it over the first STROKE_HEAD of its length and thinning to
# STROKE_TAIL of it at its end; a profile of STROKE_SIDES.
STROKE_HEAD = 0.1
STROKE_TAIL = 0.2
STROKE_SIDES = 8
# A stroke is FIBRES fibres, the copies of it fanning apart towards its end
# by up to FIBRE_FAN times Stroke Thickness (as the factor along it to
# FIBRE_CURVE), each FIBRE_THIN as thick as the stroke: the streaks of a
# cirrus are hair-like, not tubes.
FIBRES = 9
FIBRE_FAN = 8.0
FIBRE_CURVE = 1.4
FIBRE_THIN = 0.6

# (name, socket type, default, min, max, subtype) for the group's inputs. The
# operators and the UI address them by name. The limits are where a setting
# stops making a cloud, measured on a Cumulus (0.21.0): a Puff Size under
# 0.005 takes ever longer (the time goes as one over its cube: 13 s at 0.005
# at the viewport's voxels before BALL_VOXELS) and over 0.1 is a few bubbles;
# a Noise Scale over 100, a Detail over 6 or a Distortion over 20 change
# nothing more that shows, Detail only costs; Flat Base over 0.7 leaves a
# sliver; Density under 1 is next to nothing and over 500 a dark lump; a
# Viewport Resolution over 512 takes seconds at every change.
INPUTS = (
    ("Puff Size", 'NodeSocketFloat', 0.025, 0.005, 0.1, 'FACTOR'),
    ("Noise Strength", 'NodeSocketFloat', 0.05, 0.0, 0.5, 'FACTOR'),
    ("Noise Scale", 'NodeSocketFloat', 10.0, 0.0, 100.0, 'NONE'),
    ("Noise Detail", 'NodeSocketFloat', 1.0, 0.0, 6.0, 'NONE'),
    ("Noise Roughness", 'NodeSocketFloat', 0.5, 0.0, 1.0, 'FACTOR'),
    ("Noise Distortion", 'NodeSocketFloat', 1.0, 0.0, 20.0, 'NONE'),
    ("Seed", 'NodeSocketInt', 0, -100000, 100000, 'NONE'),
    ("Stroke Thickness", 'NodeSocketFloat', 0.3, 0.02, 10.0, 'DISTANCE'),
    ("Flat Base", 'NodeSocketFloat', 0.0, 0.0, 0.7, 'FACTOR'),
    ("Growth", 'NodeSocketFloat', 1.0, 0.0, 1.0, 'FACTOR'),
    ("Density", 'NodeSocketFloat', 90.0, 1.0, 500.0, 'NONE'),
    ("Resolution", 'NodeSocketInt', 256, 16, 2048, 'NONE'),
    ("Viewport Resolution", 'NodeSocketInt', 96, 16, 512, 'NONE'),
    ("Show Geometry", 'NodeSocketBool', False, None, None, None),
    ("Material", 'NodeSocketMaterial', None, None, None, None),
)

DESCRIPTIONS = {
    "Puff Size": ("Size of the largest balls the cloud is made of, as a part of its longest side. "
                  "Smaller is finer and slower"),
    "Noise Strength": "How far the noise moves the balls, as a part of the cloud's longest side",
    "Noise Scale": "How many bumps of the noise across the cloud",
    "Noise Detail": "Layers of ever smaller bumps in the noise",
    "Noise Roughness": "How strong the smaller layers of the noise are",
    "Noise Distortion": "How much the noise twists itself",
    "Seed": "Another variation of the same cloud: it changes the noise, not the shape",
    "Show Geometry": ("Show the cloud's rough shape in the viewport in place of the cloud, as if the cloud were "
                      "off: its mesh, or its strokes as tubes. A render still shows the cloud"),
    "Stroke Thickness": ("How thick a stroke of a curve is made, at its thickest: a curve's strokes are the "
                         "cloud's rough shape. Ignored on a mesh"),
    "Flat Base": "Part of the cloud's height cut flat at the bottom",
    "Growth": ("How far the cloud has grown: nothing at 0, its whole shape at 1. It fills in from the middle "
               "of its base outwards, in scattered puffs that swell and join"),
    "Density": "How opaque the cloud is across its longest side, whatever its size",
    "Resolution": "Voxels along the cloud's longest side in a render",
    "Viewport Resolution": "Voxels along the cloud's longest side in the viewport",
    "Material": "Volume material of the cloud. CocoClouds keeps it equal to the object's first material slot",
}

# Inputs the modifier does not show: CocoClouds sets them by itself.
HIDDEN = ("Material",)


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

    def switch(self, kind, on, off, when):
        return self.node("GeometryNodeSwitch", {"Switch": when, "False": off, "True": on}, input_type=kind).outputs[0]


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
        here.sort(key=lambda n: -(sum(y[t] for t in feeds[n]) / len(feeds[n]) if feeds[n] else 0.0))
        top = sum(height[n] + 30.0 for n in here) / 2.0
        for n in here:
            y[n] = top - height[n] / 2.0
            n.location = (-at * 220.0, top)
            top -= height[n] + 30.0


def _new_group():
    ng = bpy.data.node_groups.new(CLOUD_NAME, 'GeometryNodeTree')
    ng.is_modifier = True
    ng["cococlouds_version"] = GROUP_VERSION
    ng["cococlouds_kind"] = CLOUD_NAME
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    for name, stype, default, lo, hi, subtype in INPUTS:
        s = ng.interface.new_socket(name, in_out='INPUT', socket_type=stype, description=DESCRIPTIONS.get(name, ""))
        if subtype and subtype != 'NONE':
            s.subtype = subtype
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value, s.max_value = lo, hi
        # The cloud's material is set in the object's material slot, like
        # any object's, and copied here (cloud.py): shown in the modifier
        # as well, it would be a second place to set it that does not hold.
        if name in HIDDEN:
            s.hide_in_modifier = True
    return ng


def _build_cloud():
    ng = _new_group()
    g = Graph(ng)
    gi = g.node("NodeGroupInput").outputs
    go = g.node("NodeGroupOutput")
    # A curve's strokes as fibres, closed tubes, joined to whatever mesh
    # there is.
    fibres = g.node("GeometryNodeDuplicateElements", {"Geometry": gi["Geometry"], "Amount": FIBRES},
                    domain='SPLINE').outputs["Geometry"]
    which = g.node("GeometryNodeFieldOnDomain", {"Value": g.node("GeometryNodeInputIndex").outputs[0]},
                   domain='CURVE', data_type='INT').outputs[0]
    way = g.node("FunctionNodeRandomValue", {"Min": (-1.0, -1.0, -0.4), "Max": (1.0, 1.0, 0.4), "ID": which,
                                             "Seed": 7}, data_type='FLOAT_VECTOR').outputs[0]
    along = g.math('POWER', g.node("GeometryNodeSplineParameter").outputs["Factor"], FIBRE_CURVE)
    fan = g.math('MULTIPLY', g.math('MULTIPLY', along, gi["Stroke Thickness"]), FIBRE_FAN)
    fibres = g.node("GeometryNodeSetPosition", {"Geometry": fibres, "Offset": g.vmath('SCALE', way, scale=fan)}
                    ).outputs[0]
    taper = g.node("GeometryNodeSplineParameter").outputs["Factor"]
    taper = g.math('MULTIPLY', g.math('DIVIDE', taper, STROKE_HEAD, clamp=True),
                   g.math('SUBTRACT', 1.0, g.math('MULTIPLY', taper, 1.0 - STROKE_TAIL)))
    tubes = g.node("GeometryNodeCurveToMesh", {
        "Curve": fibres,
        "Profile Curve": g.node("GeometryNodeCurvePrimitiveCircle", {"Resolution": STROKE_SIDES, "Radius": 1.0},
                                mode='RADIUS').outputs["Curve"],
        "Scale": g.math('MULTIPLY', g.math('MULTIPLY', g.node("GeometryNodeInputRadius").outputs[0], taper),
                        g.math('MULTIPLY', gi["Stroke Thickness"], FIBRE_THIN)),
        "Fill Caps": True}).outputs[0]
    joined = g.node("GeometryNodeJoinGeometry").outputs[0]
    ng.links.new(tubes, joined.node.inputs[0])
    ng.links.new(gi["Geometry"], joined.node.inputs[0])
    # A Switch works out only the side it takes: a mesh is not slowed by this.
    strokes = g.node("GeometryNodeAttributeDomainSize", {"Geometry": gi["Geometry"]}, component='CURVE').outputs["Point Count"]
    mesh = g.switch('GEOMETRY', joined, gi["Geometry"], g.math('GREATER_THAN', strokes, 0.5))

    # Yardsticks, in the object's own space: the shape's longest side, the
    # voxel, the largest ball and the points' spacing.
    box = g.node("GeometryNodeBoundBox", {"Geometry": mesh}).outputs
    dims = g.vmath('SUBTRACT', box["Max"], box["Min"])
    size = g.math('MAXIMUM', g.max3(dims), 1e-4)
    zmin = g.separate(box["Min"])["Z"]
    tall = g.math('MAXIMUM', g.separate(dims)["Z"], 1e-6)
    viewport = g.node("GeometryNodeIsViewport").outputs[0]
    resolution = g.switch('INT', gi["Viewport Resolution"], gi["Resolution"], viewport)
    voxel = g.math('DIVIDE', size, resolution)
    ball = g.math('MAXIMUM', g.math('MULTIPLY', gi["Puff Size"], size), g.math('MULTIPLY', voxel, BALL_VOXELS))
    spacing = g.math('MULTIPLY', ball, SPACING)

    # 1. The shape filled with points on a grid. Mesh to Density Grid keeps
    # its solid core as tiles, and points are put on voxels only.
    solid = g.node("GeometryNodeMeshToDensityGrid", {
        "Mesh": mesh, "Voxel Size": spacing, "Gradient Width": spacing}).outputs[0]
    solid = g.node("GeometryNodeGridVoxelize", {"Grid": solid}).outputs[0]
    fill = g.node("GeometryNodeDistributePointsInGrid", mode='DENSITY_GRID')
    g.link(fill, {"Grid": solid, "Threshold": 0.5,
                  "Spacing": g.node("ShaderNodeCombineXYZ", {"X": spacing, "Y": spacing, "Z": spacing}).outputs[0]})
    points = fill.outputs["Points"]

    # 2. One noise moves each point and sizes its ball.
    position = g.node("GeometryNodeInputPosition").outputs[0]
    per_size = g.math('DIVIDE', 1.0, size)
    seed = g.math('MULTIPLY', g.math('FRACT', g.math('MULTIPLY', gi["Seed"], SEED_STEP)), SEED_SPAN)
    noise = g.node("ShaderNodeTexNoise", {
        "Vector": g.vmath('SCALE', position, scale=per_size), "W": seed,
        "Scale": gi["Noise Scale"], "Detail": gi["Noise Detail"], "Roughness": gi["Noise Roughness"],
        "Lacunarity": LACUNARITY, "Distortion": gi["Noise Distortion"],
    }, noise_dimensions='4D', noise_type='FBM', normalize=True).outputs
    z = g.separate(position)["Z"]
    rise = g.math('DIVIDE', g.math('SUBTRACT', z, zmin), g.math('MULTIPLY', tall, RISE), clamp=True)
    push = g.vmath('SCALE', g.vmath('SUBTRACT', noise["Color"], (0.5, 0.5, 0.5)),
                   scale=g.math('MULTIPLY', g.math('MULTIPLY', gi["Noise Strength"], size), rise))
    # The size is captured before the move: it belongs to the place the
    # point was given, like the push.
    sized = g.node("GeometryNodeCaptureAttribute", {"Geometry": points}, domain='POINT')
    sized.capture_items.new('FLOAT', "Radius")
    g.link(sized, {"Radius": g.math('MULTIPLY', noise["Fac"], ball)})
    moved = g.node("GeometryNodeSetPosition", {"Geometry": sized.outputs["Geometry"], "Offset": push}).outputs[0]
    radius = sized.outputs["Radius"]

    # 3. Flat base: below the floor no ball, near it only as large as its
    # height over the floor and a little more. Off at 0.
    moved_z = g.separate(g.node("GeometryNodeInputPosition").outputs[0])["Z"]
    floor = g.math('ADD', zmin, g.math('MULTIPLY', gi["Flat Base"], tall))
    under = g.math('ADD', g.math('SUBTRACT', moved_z, floor), g.math('MULTIPLY', ball, FLAT_SOFT))
    radius = g.switch('FLOAT', g.math('MINIMUM', radius, under), radius,
                      g.math('GREATER_THAN', gi["Flat Base"], 1e-4))

    # Growth: each ball's turn, from the middle of the base outwards broken
    # up by a noise; it swells from nothing to its size over GROW_EDGE of
    # Growth. At 1 every ball has its whole size. Off at 1.
    middle = g.vmath('SCALE', g.vmath('ADD', box["Min"], box["Max"]), scale=0.5)
    seat = g.node("ShaderNodeCombineXYZ", {"X": g.separate(middle)["X"], "Y": g.separate(middle)["Y"],
                                           "Z": zmin}).outputs[0]
    reach = g.math('MAXIMUM', g.vmath('LENGTH', g.vmath('MULTIPLY', dims, (0.5, 0.5, 1.0))).node.outputs["Value"], 1e-6)
    away = g.math('DIVIDE', g.vmath('DISTANCE', position, seat).node.outputs["Value"], reach, clamp=True)
    scatter = g.node("ShaderNodeTexNoise", {
        "Vector": g.vmath('SCALE', position, scale=per_size), "W": g.math('ADD', seed, 31.7),
        "Scale": GROW_SCALE, "Detail": 2.0, "Roughness": 0.5,
    }, noise_dimensions='4D', noise_type='FBM', normalize=True).outputs["Fac"]
    scatter = g.math('MULTIPLY', g.math('SUBTRACT', scatter, 0.25), 2.0, clamp=True)
    turn = g.math('ADD', g.math('MULTIPLY', away, GROW_SHAPE), g.math('MULTIPLY', scatter, 1.0 - GROW_SHAPE))
    swell = g.math('DIVIDE', g.math('SUBTRACT', g.math('MULTIPLY', gi["Growth"], 1.0 + GROW_EDGE), turn),
                   GROW_EDGE, clamp=True)
    radius = g.switch('FLOAT', g.math('MULTIPLY', radius, swell), radius,
                      g.math('LESS_THAN', gi["Growth"], 0.9999))
    # The turn is read where the point was put: captured with the radius.
    kept = g.node("GeometryNodeCaptureAttribute", {"Geometry": moved}, domain='POINT')
    kept.capture_items.new('FLOAT', "Radius")
    g.link(kept, {"Radius": radius})
    balls = g.node("GeometryNodeDeleteGeometry", {
        "Geometry": kept.outputs["Geometry"], "Selection": g.math('LESS_THAN', kept.outputs["Radius"], 1e-6),
    }, domain='POINT').outputs[0]
    balls = g.node("GeometryNodeSetPointRadius", {"Points": balls, "Radius": kept.outputs["Radius"]}).outputs[0]
    radius = g.node("GeometryNodeInputRadius").outputs[0]

    # 4. The balls as a volume. Density is per metre in a render, and a
    # scaled object is not compensated, so it is divided by the size the
    # cloud really has in the scene.
    this = g.node("GeometryNodeSelfObject").outputs[0]
    scale = g.node("GeometryNodeObjectInfo", {"Object": this}, transform_space='ORIGINAL').outputs["Scale"]
    world_size = g.math('MULTIPLY', size, g.math('MAXIMUM', g.max3(g.vmath('ABSOLUTE', scale)), 1e-6))
    per_metre = g.math('DIVIDE', gi["Density"], world_size)
    fine = g.node("GeometryNodePointsToVolume", {"Points": balls, "Density": per_metre, "Voxel Size": voxel,
                                                  "Radius": radius})
    fine.inputs["Resolution Mode"].default_value = 'Size'
    volume = fine.outputs[0]

    # What the material cannot work out: a coarse copy of the balls, from
    # which how high a place is and the way out of the cloud.
    coarse = g.math('MULTIPLY', voxel, COARSE_VOXELS)
    rough = g.node("GeometryNodePointsToVolume", {"Points": balls, "Density": 1.0, "Voxel Size": coarse,
                                                   "Radius": g.math('ADD', radius, g.math('MULTIPLY', coarse, 0.5))})
    rough.inputs["Resolution Mode"].default_value = 'Size'
    rough = g.node("GeometryNodeGetNamedGrid", {"Volume": rough.outputs[0], "Name": GRID}, data_type='FLOAT')
    rough = rough.outputs["Grid"]

    def grown(grid_, distance, cell):
        steps = g.math('ADD', g.math('CEIL', g.math('DIVIDE', distance, cell)), 1.0)
        wide = g.node("GeometryNodeGridDilateAndErode", {"Grid": grid_, "Connectivity": "Vertex", "Steps": steps}).outputs[0]
        return g.node("GeometryNodeGridVoxelize", {"Grid": wide}).outputs[0]

    def to_grid(topology_, field, kind='FLOAT'):
        n = g.node("GeometryNodeFieldToGrid")
        n.grid_items.new(kind, "Value")
        g.link(n, {"Topology": topology_, "Value": field})
        return g.node("GeometryNodeSetGridBackground", {"Grid": n.outputs["Value"]}, data_type=kind).outputs[0]

    room = grown(rough, g.math('MULTIPLY', coarse, INFO_MARGIN), coarse)
    # X the height in the cloud, 0 at the floor and 1 at the top, left to
    # run past both (a straight line is exact between coarse voxels, a
    # clamped one is not); Y one over the density of a voxel deep inside;
    # Z 1, which tells a cloud from a volume without this grid.
    top = g.separate(box["Max"])["Z"]
    height = g.math('DIVIDE', g.math('SUBTRACT', z, floor), g.math('MAXIMUM', g.math('SUBTRACT', top, floor), 1e-6))
    per_full = g.math('DIVIDE', world_size, g.math('MAXIMUM', gi["Density"], 1e-6))
    info = to_grid(room, g.node("ShaderNodeCombineXYZ", {"X": height, "Y": per_full, "Z": 1.0}).outputs[0], 'VECTOR')
    volume = g.node("GeometryNodeStoreNamedGrid", {"Volume": volume, "Name": INFO, "Grid": info},
                    data_type='VECTOR_FLOAT').outputs[0]
    # The way out: the coarse density, blurred, falls from the inside to the
    # outside, so its slope points in; turned round and made one long.
    wide = g.node("GeometryNodeGridMean", {
        "Grid": grown(rough, g.math('MULTIPLY', coarse, INFO_MARGIN + OUT_BLUR), coarse),
        "Width": OUT_BLUR, "Iterations": 2}).outputs[0]
    slope = g.node("GeometryNodeSampleGrid", {
        "Grid": g.node("GeometryNodeGridGradient", {"Grid": wide}).outputs[0], "Position": position,
    }, data_type='VECTOR').outputs[0]
    from_middle = g.vmath('DIVIDE', g.vmath('SUBTRACT', position, middle), g.vmath('MAXIMUM', dims, (1e-6, 1e-6, 1e-6)))
    way = g.vmath('NORMALIZE', g.vmath('ADD', g.vmath('SCALE', slope, scale=g.math('MULTIPLY', coarse, -OUT_BLUR * 2.0)),
                                       g.vmath('SCALE', from_middle, scale=OUT_ROUND * 2.0)))
    volume = g.node("GeometryNodeStoreNamedGrid", {"Volume": volume, "Name": OUT, "Grid": to_grid(room, way, 'VECTOR')},
                    data_type='VECTOR_FLOAT').outputs[0]
    out = g.node("GeometryNodeSetMaterial", {"Geometry": volume, "Material": gi["Material"]}).outputs[0]

    # Show Geometry: in the viewport the rough shape itself in place of the
    # cloud, as if it were off: the mesh, a curve's strokes as their tubes,
    # no material (the cloud's would fill it with fog). A Switch works out
    # only the side it takes, so the cloud costs nothing meanwhile.
    shape = g.node("GeometryNodeSeparateComponents", {"Geometry": mesh}).outputs["Mesh"]
    shape = g.node("GeometryNodeSetMaterial", {"Geometry": shape}).outputs[0]
    out = g.switch('GEOMETRY', shape, out, g.math('MINIMUM', gi["Show Geometry"], viewport))
    ng.links.new(out, go.inputs[0])
    return ng


def get_group():
    """The current version of the group, building it when missing.

    A group of another version keeps working for the clouds that use it: it
    is renamed out of the way rather than rebuilt, since rebuilding would
    change its socket identifiers and drop every value stored on them."""
    ng = bpy.data.node_groups.get(CLOUD_NAME)
    if ng is not None and ng.get("cococlouds_version") == GROUP_VERSION:
        return ng
    if ng is not None:
        ng.name = f"{CLOUD_NAME} v{ng.get('cococlouds_version', 0)}"
    ng = _build_cloud()
    arrange(ng)
    return ng


def is_group(ng):
    """True for any version of the group, whatever it has been renamed to."""
    return ng is not None and ng.get("cococlouds_kind") == CLOUD_NAME


def is_current(ng):
    """False for a group of an earlier version than this code builds."""
    return ng.get("cococlouds_version") == GROUP_VERSION


def socket_id(ng, name):
    item = ng.interface.items_tree.get(name)
    return item.identifier if item is not None else None
