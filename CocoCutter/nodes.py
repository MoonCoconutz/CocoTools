"""The two geometry node groups CocoCutter runs on.

- **Sheet** sits on the cutter, a curve object holding the drawn stroke. It
  sweeps the stroke along the cutter's local Z into a grid, pushes the grid
  along its normals with noise (and an optional image), and outputs that
  noisy sheet. Every setting of a cut lives on this modifier, so a cutter
  carries its own settings and Ctrl+Z covers them. The settings the cut
  side needs (Keep, Gap, Solver, Cyclic) travel to it as point attributes.
- **Cut** sits on each object being cut. It reads the cutter's sheet, closes
  it into a volume, and booleans the object against it: side A is the
  object minus the volume, side B the object minus everything else.

An open sheet is closed into a slab by the Cut group: its two end columns
are first carried far out along the stroke's chord (start to end) as flat
strips, then the whole thing is extruded far to the side square to the
chord, and capped with a flipped copy. The walls the extrusion raises at the
strips' ends then run square to the chord, well past the object, so they
cannot cross it, and the slab's only face inside the object is the sheet.
Extruding along the sheet's mean normal instead, with the ends where they
were drawn, let the wall at one end of a tilted stroke run diagonally
through the bottom of a tall column (2026-10-02). The strips live in the
Cut group, not on the cutter, so they neither show on the cutter nor take
cells from Resolution. A cyclic stroke is already
a closed tube once its two ends are capped.

The groups are built here, never shipped as a .blend, and carry
GROUP_VERSION. A change to either graph bumps it; older groups are left
alone for the cutters already using them (see get_group).
"""

import bpy

GROUP_VERSION = 3
SHEET_NAME = "CocoCutter Sheet"
CUT_NAME = "CocoCutter Cut"

# Names of the attributes the sheet hands to the cut. The cut removes every
# "cococutter_*" attribute before output, so none reaches the real mesh.
A_UV = "cococutter_uv"
A_CUT = "cococutter_cut"
A_KEEP = "cococutter_keep"
A_GAP = "cococutter_gap"
A_SOLVER = "cococutter_solver"
A_CLOSED = "cococutter_closed"
A_CHORD = "cococutter_chord"  # unit start-to-end direction, in cutter space
A_U = "cococutter_u"          # 0 on the sheet's start column, 1 on its end column
# Kept on the output in Keep Both, so the Cut operator can split the result
# into its two pieces. The operator removes it.
A_SIDE = "coco_cut_side"

KEEP_BOTH, KEEP_A, KEEP_B = 0, 1, 2
SOLVERS = ('EXACT', 'MANIFOLD', 'FLOAT')

# (name, socket type, default, min, max, subtype) for the sheet's inputs, in
# panel order. The operators and the UI address them by name.
SHEET_INPUTS = (
    ("Resolution", 'NodeSocketInt', 64, 2, 1024, 'NONE'),
    ("Length", 'NodeSocketFloat', 2.0, 0.0, 1e6, 'DISTANCE'),
    ("Offset", 'NodeSocketFloat', 0.0, -1e6, 1e6, 'DISTANCE'),
    ("Cyclic", 'NodeSocketBool', False, None, None, None),
    ("Strength", 'NodeSocketFloat', 0.05, -1e6, 1e6, 'DISTANCE'),
    ("Scale", 'NodeSocketFloat', 2.0, 0.0, 1e6, 'NONE'),
    ("Detail", 'NodeSocketFloat', 6.0, 0.0, 15.0, 'NONE'),
    ("Roughness", 'NodeSocketFloat', 0.6, 0.0, 1.0, 'FACTOR'),
    ("Distortion", 'NodeSocketFloat', 0.0, -1e6, 1e6, 'NONE'),
    ("Seed", 'NodeSocketInt', 0, -100000, 100000, 'NONE'),
    ("Image", 'NodeSocketImage', None, None, None, None),
    ("Image Strength", 'NodeSocketFloat', 0.0, -1e6, 1e6, 'DISTANCE'),
    ("Image Size", 'NodeSocketFloat', 1.0, 0.0001, 1e6, 'DISTANCE'),
    ("Image Rotation", 'NodeSocketFloat', 0.0, -1e6, 1e6, 'ANGLE'),
    ("Keep", 'NodeSocketInt', KEEP_BOTH, 0, 2, 'NONE'),
    ("Gap", 'NodeSocketFloat', 0.0, 0.0, 1e6, 'DISTANCE'),
    ("Solver", 'NodeSocketInt', 0, 0, 2, 'NONE'),
)


class _Graph:
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
        for key, value in (ins or {}).items():
            sock = n.inputs[key]
            if isinstance(value, bpy.types.NodeSocket):
                self.ng.links.new(value, sock)
            else:
                sock.default_value = value
        return n

    def math(self, op, a, b=None, c=None):
        ins = {0: a}
        if b is not None:
            ins[1] = b
        if c is not None:
            ins[2] = c
        return self.node("ShaderNodeMath", ins, operation=op).outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        ins = {0: a}
        if b is not None:
            ins[1] = b
        if scale is not None:
            ins[3] = scale
        n = self.node("ShaderNodeVectorMath", ins, operation=op)
        return n.outputs[1] if op in ('LENGTH', 'DOT_PRODUCT', 'DISTANCE') else n.outputs[0]

    def xyz(self, x=0.0, y=0.0, z=0.0):
        return self.node("ShaderNodeCombineXYZ", {"X": x, "Y": y, "Z": z}).outputs[0]

    def named(self, name, data_type):
        return self.node("GeometryNodeInputNamedAttribute", {"Name": name},
                         data_type=data_type).outputs[0]

    def store(self, geo, name, value, data_type, domain, selection=None):
        ins = {"Geometry": geo, "Name": name, "Value": value}
        if selection is not None:
            ins["Selection"] = selection
        return self.node("GeometryNodeStoreNamedAttribute", ins,
                         data_type=data_type, domain=domain).outputs[0]

    def sample0(self, geo, name, data_type):
        """The value of a constant point attribute, read off point 0."""
        return self.node("GeometryNodeSampleIndex",
                         {"Geometry": geo, "Value": self.named(name, data_type), "Index": 0},
                         data_type=data_type, domain='POINT').outputs[0]

    def switch(self, type_, cond, false, true):
        return self.node("GeometryNodeSwitch", {"Switch": cond, "False": false, "True": true},
                         input_type=type_).outputs[0]

    def index_switch(self, type_, index, *items):
        n = self.node("GeometryNodeIndexSwitch", {"Index": index}, data_type=type_)
        while len(n.index_switch_items) < len(items):
            n.index_switch_items.new()
        for i, item in enumerate(items):
            self.ng.links.new(item, n.inputs[i + 1])
        return n.outputs[0]

    def join(self, *geos):
        n = self.node("GeometryNodeJoinGeometry")
        for g in reversed(geos):
            self.ng.links.new(g, n.inputs[0])
        return n.outputs[0]


def _new_group(name):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.is_modifier = True
    ng["cococutter_version"] = GROUP_VERSION
    ng["cococutter_kind"] = name
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    return ng


def _build_sheet():
    ng = _new_group(SHEET_NAME)
    for name, stype, default, lo, hi, subtype in SHEET_INPUTS:
        s = ng.interface.new_socket(name, in_out='INPUT', socket_type=stype)
        if subtype and subtype != 'NONE':
            s.subtype = subtype
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value, s.max_value = lo, hi

    g = _Graph(ng)
    gi = g.node("NodeGroupInput").outputs
    go = g.node("NodeGroupOutput")

    curve = g.node("GeometryNodeSetSplineCyclic",
                   {"Curve": gi["Geometry"], "Cyclic": gi["Cyclic"]}).outputs[0]
    length = gi["Length"]
    curve_len = g.node("GeometryNodeCurveLength", {"Curve": curve}).outputs[0]

    # Square-ish cells: the longer side gets Resolution cells.
    seg = g.math('DIVIDE', g.math('MAXIMUM', curve_len, length), g.math('MAXIMUM', gi["Resolution"], 2))
    seg = g.math('MAXIMUM', seg, 1e-6)
    nu = g.math('ADD', g.math('CEIL', g.math('DIVIDE', curve_len, seg)), 1)
    nv = g.math('ADD', g.math('CEIL', g.math('DIVIDE', length, seg)), 1)

    grid = g.node("GeometryNodeMeshGrid",
                  {"Size X": 1.0, "Size Y": 1.0, "Vertices X": nu, "Vertices Y": nv}).outputs[0]
    sep = g.node("ShaderNodeSeparateXYZ", {0: g.node("GeometryNodeInputPosition").outputs[0]}).outputs
    u = g.math('ADD', sep[0], 0.5)
    v = g.math('ADD', sep[1], 0.5)
    # Cut-face UVs in metres: along the stroke, and across it.
    grid = g.store(grid, A_U, u, 'FLOAT', 'POINT')
    grid = g.store(grid, A_UV, g.xyz(g.math('MULTIPLY', u, curve_len), g.math('MULTIPLY', v, length)),
                   'FLOAT2', 'CORNER')
    on_curve = g.node("GeometryNodeSampleCurve", {"Curves": curve, "Factor": u},
                      mode='FACTOR').outputs["Position"]
    z = g.math('MULTIPLY_ADD', g.math('SUBTRACT', v, 0.5), length, gi["Offset"])
    tube = g.node("GeometryNodeSetPosition",
                  {"Geometry": grid, "Position": g.vmath('ADD', on_curve, g.xyz(z=z))}).outputs[0]

    # Cyclic: cap both ends of the tube and weld the seam, so the sheet is a
    # closed volume by itself. Neither the tube nor the fill follows the
    # stroke's winding in a way worth trusting, so both are oriented from
    # the geometry: the tube is flipped when its normals point inward on
    # average (towards the ring's centre), each cap when it faces the tube.
    ring = g.node("GeometryNodeResampleCurve",
                  {"Curve": curve, "Count": g.math('SUBTRACT', nu, 1)}).outputs[0]
    fill = g.node("GeometryNodeFillCurve", {"Curve": ring, "Mode": "N-gons"}).outputs[0]
    fpos = g.node("ShaderNodeSeparateXYZ", {0: g.node("GeometryNodeInputPosition").outputs[0]}).outputs
    fill = g.store(fill, A_UV, g.xyz(fpos[0], fpos[1]), 'FLOAT2', 'CORNER')
    centre = g.node("GeometryNodeAttributeStatistic", {
        "Geometry": ring, "Attribute": g.node("GeometryNodeInputPosition").outputs[0]},
        data_type='FLOAT_VECTOR', domain='POINT').outputs["Mean"]
    outward = g.vmath('DOT_PRODUCT', g.node("GeometryNodeInputNormal").outputs[0],
                      g.vmath('SUBTRACT', g.node("GeometryNodeInputPosition").outputs[0], centre))
    outward = g.node("GeometryNodeAttributeStatistic", {"Geometry": tube, "Attribute": outward},
                     data_type='FLOAT', domain='FACE').outputs["Mean"]
    inward = g.node("FunctionNodeCompare", {0: outward, 1: 0.0}, data_type='FLOAT',
                    operation='LESS_THAN').outputs[0]
    normal_z = g.node("ShaderNodeSeparateXYZ", {0: g.node("GeometryNodeInputNormal").outputs[0]}).outputs[2]
    faces_up = g.node("FunctionNodeCompare", {0: normal_z, 1: 0.0}, data_type='FLOAT',
                      operation='GREATER_THAN').outputs[0]
    faces_down = g.node("FunctionNodeBooleanMath", {0: faces_up}, operation='NOT').outputs[0]
    half = g.math('MULTIPLY', length, 0.5)
    bottom = g.node("GeometryNodeSetPosition", {
        "Geometry": fill, "Offset": g.xyz(z=g.math('SUBTRACT', gi["Offset"], half))}).outputs[0]
    top = g.node("GeometryNodeSetPosition", {
        "Geometry": fill, "Offset": g.xyz(z=g.math('ADD', gi["Offset"], half))}).outputs[0]
    closed = g.join(
        g.node("GeometryNodeFlipFaces", {"Mesh": tube, "Selection": inward}).outputs[0],
        g.node("GeometryNodeFlipFaces", {"Mesh": bottom, "Selection": faces_up}).outputs[0],
        g.node("GeometryNodeFlipFaces", {"Mesh": top, "Selection": faces_down}).outputs[0],
    )
    closed = g.node("GeometryNodeMergeByDistance",
                    {"Geometry": closed, "Distance": g.math('MULTIPLY', seg, 0.01)}).outputs[0]
    sheet = g.switch('GEOMETRY', gi["Cyclic"], tube, closed)

    # Displacement along the normals: centred noise, plus a centred image.
    # The image's alpha gates it, so no image means no offset.
    noise = g.node("ShaderNodeTexNoise", {
        "Vector": g.node("GeometryNodeInputPosition").outputs[0],
        "W": g.math('MULTIPLY', gi["Seed"], 1.618),
        "Scale": gi["Scale"], "Detail": gi["Detail"], "Roughness": gi["Roughness"],
        "Distortion": gi["Distortion"],
    }, noise_dimensions='4D').outputs[0]
    disp = g.math('MULTIPLY', g.math('SUBTRACT', noise, 0.5), g.math('MULTIPLY', gi["Strength"], 2.0))
    uv = g.node("ShaderNodeVectorRotate", {
        "Vector": g.named(A_UV, 'FLOAT_VECTOR'), "Angle": gi["Image Rotation"]},
        rotation_type='Z_AXIS').outputs[0]
    uv = g.vmath('DIVIDE', uv, g.xyz(gi["Image Size"], gi["Image Size"], 1.0))
    img = g.node("GeometryNodeImageTexture", {"Image": gi["Image"], "Vector": uv}).outputs
    # Linking a colour into a float socket converts it to grey.
    gray = img["Color"]
    img_disp = g.math('MULTIPLY', g.math('MULTIPLY', g.math('SUBTRACT', gray, 0.5),
                                         g.math('MULTIPLY', gi["Image Strength"], 2.0)), img["Alpha"])
    disp = g.math('ADD', disp, img_disp)
    sheet = g.node("GeometryNodeSetPosition", {
        "Geometry": sheet,
        "Offset": g.vmath('SCALE', g.node("GeometryNodeInputNormal").outputs[0], scale=disp)}).outputs[0]

    sheet = g.node("GeometryNodeSetShadeSmooth", {"Mesh": sheet, "Shade Smooth": True}).outputs[0]
    sheet = g.store(sheet, A_CUT, True, 'BOOLEAN', 'FACE')
    sheet = g.store(sheet, A_KEEP, gi["Keep"], 'INT', 'POINT')
    sheet = g.store(sheet, A_GAP, gi["Gap"], 'FLOAT', 'POINT')
    sheet = g.store(sheet, A_SOLVER, gi["Solver"], 'INT', 'POINT')
    sheet = g.store(sheet, A_CLOSED, gi["Cyclic"], 'BOOLEAN', 'POINT')
    ends = [g.node("GeometryNodeSampleCurve", {"Curves": curve, "Factor": f},
                   mode='FACTOR').outputs["Position"] for f in (0.0, 1.0)]
    chord = g.vmath('NORMALIZE', g.vmath('SUBTRACT', ends[1], ends[0]))
    sheet = g.store(sheet, A_CHORD, chord, 'FLOAT_VECTOR', 'POINT')
    ng.links.new(sheet, go.inputs[0])
    return ng


def _build_cut():
    ng = _new_group(CUT_NAME)
    ng.interface.new_socket("Cutter", in_out='INPUT', socket_type='NodeSocketObject')
    s = ng.interface.new_socket("UV Map", in_out='INPUT', socket_type='NodeSocketString')
    s.default_value = "UVMap"
    ng.interface.new_socket("Material", in_out='INPUT', socket_type='NodeSocketMaterial')

    g = _Graph(ng)
    gi = g.node("NodeGroupInput").outputs
    go = g.node("NodeGroupOutput")
    target = gi["Geometry"]

    info = g.node("GeometryNodeObjectInfo", {"Object": gi["Cutter"]},
                  transform_space='RELATIVE').outputs
    sheet = info["Geometry"]
    keep = g.sample0(sheet, A_KEEP, 'INT')
    gap = g.sample0(sheet, A_GAP, 'FLOAT')
    solver = g.sample0(sheet, A_SOLVER, 'INT')
    closed = g.sample0(sheet, A_CLOSED, 'BOOLEAN')

    # Attributes are not transformed by Object Info, positions are: the chord
    # and the side (square to it, in the cutter's plane) are worked out in
    # cutter space and carried here with the same matrix.
    chord_c = g.sample0(sheet, A_CHORD, 'FLOAT_VECTOR')
    side_c = g.vmath('CROSS_PRODUCT', g.xyz(z=1.0), chord_c)

    def to_here(direction):
        return g.vmath('NORMALIZE', g.node("FunctionNodeTransformDirection", {
            "Direction": direction, "Transform": info["Transform"]}).outputs[0])

    chord = to_here(chord_c)
    side = to_here(side_c)
    mean_normal = g.node("GeometryNodeAttributeStatistic", {
        "Geometry": sheet, "Attribute": g.node("GeometryNodeInputNormal").outputs[0]},
        data_type='FLOAT_VECTOR', domain='FACE').outputs["Mean"]
    # Extruded along its normal, the slab comes out with outward normals;
    # extruded against it, inside out. The sign of normal . side survives any
    # object transform, so it is safe to test here.
    inside_out = g.node("FunctionNodeCompare", {0: g.vmath('DOT_PRODUCT', mean_normal, side), 1: 0.0},
                        data_type='FLOAT', operation='LESS_THAN').outputs[0]

    def diagonal(geo):
        bb = g.node("GeometryNodeBoundBox", {"Geometry": geo}).outputs
        return g.vmath('DISTANCE', bb["Min"], bb["Max"])

    reach = g.math('ADD', diagonal(target), diagonal(sheet))

    # The end columns, carried out along the chord as flat strips.
    u = g.named(A_U, 'FLOAT')
    first = g.node("FunctionNodeCompare", {0: u, 1: 1e-4}, data_type='FLOAT',
                   operation='LESS_THAN').outputs[0]
    last = g.node("FunctionNodeCompare", {0: u, 1: 1.0 - 1e-4}, data_type='FLOAT',
                  operation='GREATER_THAN').outputs[0]
    strips = g.node("GeometryNodeExtrudeMesh", {
        "Mesh": sheet, "Selection": first, "Offset": chord,
        "Offset Scale": g.math('MULTIPLY', reach, -1.0)}, mode='EDGES').outputs["Mesh"]
    strips = g.node("GeometryNodeExtrudeMesh", {
        "Mesh": strips, "Selection": last, "Offset": chord, "Offset Scale": reach},
        mode='EDGES').outputs["Mesh"]

    slab = g.node("GeometryNodeExtrudeMesh", {
        "Mesh": strips, "Offset": side, "Offset Scale": reach, "Individual": False},
        mode='FACES').outputs["Mesh"]
    slab = g.join(slab, g.node("GeometryNodeFlipFaces", {"Mesh": strips}).outputs[0])
    slab = g.node("GeometryNodeMergeByDistance", {"Geometry": slab, "Distance": 1e-6}).outputs[0]
    slab = g.node("GeometryNodeFlipFaces", {"Mesh": slab, "Selection": inside_out}).outputs[0]
    volume = g.switch('GEOMETRY', closed, slab, sheet)

    # Side B is the object minus everything but the volume: a box around
    # both, holding the volume as an inward-facing cavity. Intersect would
    # give the same piece, but on 5.2 it drops empty material slots from the
    # list and keeps the indices, so after an earlier cut had given a plain
    # object [None, cut material], its outer faces turned into cut material
    # (a column with three cutters, 2026-10-02). Difference keeps the list.
    bb = g.node("GeometryNodeBoundBox", {"Geometry": g.join(target, volume)}).outputs
    centre = g.vmath('SCALE', g.vmath('ADD', bb["Min"], bb["Max"]), scale=0.5)
    extent = g.vmath('SUBTRACT', bb["Max"], bb["Min"])
    box = g.node("GeometryNodeMeshCube", {
        "Size": g.vmath('ADD', g.vmath('SCALE', extent, scale=1.2), g.xyz(1.0, 1.0, 1.0))}).outputs[0]
    box = g.node("GeometryNodeSetPosition", {"Geometry": box, "Offset": centre}).outputs[0]
    outside = g.join(box, g.node("GeometryNodeFlipFaces", {"Mesh": volume}).outputs[0])

    side_a, side_b = [], []
    for solver_id in SOLVERS:
        for cutter_volume, pieces in ((volume, side_a), (outside, side_b)):
            diff = g.node("GeometryNodeMeshBoolean", operation='DIFFERENCE', solver=solver_id)
            ng.links.new(target, diff.inputs["Mesh 1"])
            ng.links.new(cutter_volume, diff.inputs["Mesh 2"])
            pieces.append(diff.outputs["Mesh"])
    a = g.index_switch('GEOMETRY', solver, *side_a)
    b = g.index_switch('GEOMETRY', solver, *side_b)

    moved = g.node("GeometryNodeSetPosition", {"Geometry": b, "Offset": g.vmath('SCALE', side, scale=gap)}).outputs[0]
    both = g.join(a, g.store(moved, A_SIDE, True, 'BOOLEAN', 'FACE'))
    out = g.index_switch('GEOMETRY', keep, both, a, b)

    # The cut faces' material is set here, after the boolean, rather than on
    # the sheet: on 5.2 the Exact and Manifold solvers give the sheet's faces
    # an index one past the merged material list (the empty slot Set Material
    # adds to a mesh without materials is dropped from the list, not from the
    # indices). So the material lives on this modifier, kept in step with the
    # cutter's by the add-on.
    is_cut = g.named(A_CUT, 'BOOLEAN')
    out = g.node("GeometryNodeSetMaterial", {
        "Geometry": out, "Selection": is_cut, "Material": gi["Material"]}).outputs[0]
    out = g.node("GeometryNodeStoreNamedAttribute", {
        "Geometry": out, "Selection": is_cut, "Name": gi["UV Map"],
        "Value": g.named(A_UV, 'FLOAT_VECTOR')}, data_type='FLOAT2', domain='CORNER').outputs[0]
    out = g.node("GeometryNodeRemoveAttribute", {
        "Geometry": out, "Pattern Mode": "Wildcard", "Name": "cococutter_*"}).outputs[0]
    ng.links.new(out, go.inputs[0])
    return ng


_BUILDERS = {SHEET_NAME: _build_sheet, CUT_NAME: _build_cut}


def get_group(name):
    """The current version of a group, building it when missing.

    A group of another version keeps working for the cutters that use it:
    it is renamed out of the way rather than rebuilt, since rebuilding would
    change its socket identifiers and drop every value stored on them."""
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.get("cococutter_version") == GROUP_VERSION:
        return ng
    if ng is not None:
        ng.name = f"{name} v{ng.get('cococutter_version', 0)}"
    return _BUILDERS[name]()


def is_group(ng, name):
    """True for any version of the group, whatever it has been renamed to."""
    return ng is not None and ng.get("cococutter_kind") == name


def socket_id(ng, name):
    item = ng.interface.items_tree.get(name)
    return item.identifier if item is not None else None
