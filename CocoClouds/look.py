"""The cloud's material, and the few things to set on it.

The material is laid out in the Shader Editor as a handful of nodes to read
from left to right, and to cut into:

    Cloud Data ──> Wispy Edges ──────────────────> Principled Volume ──> Output (Cycles)
               ├─> Color ──> Many Bounces ──────>      "
               └─> Glow ─────────────────────────>     "
                    (the same three, the density and the glow thinned) ──> Principled Volume ──> Output (EEVEE)

Blender's Principled Volume does the lighting, one for each engine. The
nodes before it are small groups built here (the parts), one job each, that
say what goes into it. The controls of the Look panel are sockets of those
nodes, found by the kind of group a node holds (controls()): the panel shows
whichever of them the material still has, so nodes can be put between, taken
out or swapped for others. A copy of the material has values of its own; the
groups inside are the same for all.

Cloud Data reads two grids of the cloud (nodes.py): "density", and the
coarse "cococlouds" that says how high in the cloud a place is and how dense
the cloud gets. On a volume without the second one, another add-on's or an
older cloud, Dark Base and Wispy Edges do nothing and the rest works.

What a control costs. Cycles renders a Principled Volume that reads its
grid by itself, everything else on it a fixed number, a good deal quicker
than one with an Attribute node anywhere in its material (measured on 5.2,
a field of 77 copies of 5 clouds at 1600 x 900: 9.1 s, and 15.4 to 17.9 s
with an Attribute node feeding the density, the colour or the emission;
about 6 s more whether 8 samples or 256, so it is in preparing the render,
plus a tenth on each sample). Fixed numbers cost nothing. So Color,
Brightness and Anisotropy are free, and the three controls that must
read a grid, Dark Base, Wispy Edges and Glow, are cut out of the graph
while they are at the value that does nothing (`_unless`): each part ends in
a Mix whose factor is then a fixed 0, Cycles drops what hangs on it, and
Cloud Data with it once nothing reads it. EEVEE takes the same time either
way.

EEVEE is the preview, and is made to look like Cycles by other means than
Cycles'. It lights a volume once, and a cloud is what it is by light
scattered many times: left to its own lighting a cloud is either a pale
ghost or a dark lump with a lit skin (both tried on 5.2). So in EEVEE the
cloud's volume scatters nothing and gives off, as light of its own, what
Cycles would have scattered: the part Preview Light works that out from
the way out of the cloud at each place, a third grid of the cloud's
(nodes.OUT), and from where the sun is, which a shader cannot ask. The
sun, its light and the sky's are numbers inside one more group, Scene
Light, that a handler copies from the scene (_follow_light). What that
leaves out: every light but the strongest sun, and a cloud's shadow on
itself and on other clouds, stood in for by a darker base under a high sun.

Like the geometry groups the parts are built here and carry a version; a
change to a graph bumps SHADER_VERSION, and a group of another version is
renamed out of the way for the materials that use it (see get_part).
Until 0.10.0 the material was one node, the group "CocoClouds Shader",
with the controls as its inputs: such a material goes on working, and
split() lays it out as the nodes above with the values it has.
"""

import bpy

from . import nodes

MATERIAL_NAME = "CocoClouds Cloud"
# What the material of 0.8.0 and before is renamed to, once.
PLAIN_NAME = "CocoClouds Cloud (plain)"
# The one group of 0.9.0, all the controls its inputs.
BLOCK_NAME = "CocoClouds Shader"
SHADER_VERSION = 3

# The parts, by the name of their group.
DATA = "CocoClouds Data"
WISP = "CocoClouds Wispy Edges"
COLOR = "CocoClouds Color"
GLOW = "CocoClouds Glow"
PREVIEW = "CocoClouds Preview Light"
LIGHT = "CocoClouds Scene Light"
# The names the two Principled Volume nodes are given.
CYCLES = "Cycles"
EEVEE = "EEVEE"

# (name, socket type, default, min, max, subtype, where) for the controls.
# Where: the part whose node has the control as an input of the same name,
# or the name of a Principled Volume and of its socket.
CONTROLS = (
    ("Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None, None, COLOR),
    ("Brightness", 'NodeSocketFloat', 1.0, 0.0, 1.0, 'FACTOR', COLOR),
    ("Dark Base", 'NodeSocketFloat', 0.0, 0.0, 1.0, 'FACTOR', COLOR),
    ("Wispy Edges", 'NodeSocketFloat', 0.0, -1.0, 1.0, 'FACTOR', WISP),
    ("Anisotropy", 'NodeSocketFloat', 0.6, 0.0, 0.9, 'FACTOR', (CYCLES, "Anisotropy")),
    ("Glow", 'NodeSocketFloat', 0.0, 0.0, 1000.0, 'NONE', GLOW),
    ("Glow Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None, None, GLOW),
)

# What a control was called in the one node of 0.9.0, where it differs.
BLOCK_NAMES = {"Anisotropy": "Silver Lining"}

DESCRIPTIONS = {
    "Color": "The colour of the cloud where it is thick and lit. Thin parts stay whiter",
    "Brightness": "How white the thick, lit parts are: lower for a grey cloud under the same light",
    "Dark Base": ("Darken the cloud towards its base, as under a thick cloud. "
                  "Above 0, Cycles takes longer to prepare a render"),
    "Wispy Edges": ("Above 0 the edges thin out into wisps, below 0 they harden. The inside stays as dense. "
                    "Away from 0, Cycles takes longer to prepare a render"),
    "Glow": ("Light the cloud gives off by itself, for night skies and lightning. 1 is about a white wall "
             "in daylight. Above 0, Cycles takes longer to prepare a render"),
    "Glow Color": "Colour of the glow",
    # What the other nodes hand a part.
    "Density": "The cloud's density, from Cloud Data",
    "Edge to Core": "0 at the cloud's surface to 1 where it is as dense as it gets, from Cloud Data",
    "Height": "How high in the cloud, 0 at its base to 1 at its top, from Cloud Data",
    "Is Cloud": "1 on a cloud that says so, from Cloud Data. At 0 the control is left out",
    "Thinning": "What Wispy Edges makes of the density, for the glow to thin out with the edges",
    "Way Out": "The way out of the cloud at each place, from Cloud Data",
    "To Sun": "The way to the sun, from Scene Light",
    "Sunlight": "The sun's colour times its strength, from Scene Light",
    "Skylight": "The world's colour times its strength, from Scene Light",
}

# The Density of EEVEE's Principled Volume in the material of 0.8.0, which
# is_plain() knows it by.
EEVEE_DENSITY = 0.1
# Preview Light, tuned on 5.2 against Cycles with 64 bounces, a Cumulus, a
# Tower and a Puff under a sun of strength 5 from the front, the side, the
# back and above, in a plain blue world (probes/lookdev_match.py).
# The lit side: the sunlight times LIT, by how far a place faces the sun.
# Wrapped, since light gets round a cloud: a place facing LIT_WRAP away
# from the sun is the first in the dark.
LIT = 0.32
LIT_WRAP = 0.6
LIT_POWER = 1.6
# Looked at against the sun, what is lit is this many times brighter at
# most: the silver lining.
LIT_FORWARD = 2.0
# With the sun overhead the base is this much darker: the cloud's own
# shadow, which nothing here can work out.
LIT_SHADOW = 0.5
# The shade: this much of the sky's light and of the sun's.
FILL_SKY = 0.6
FILL_SUN = 0.04
# The sky's light when the world gives no plain colour to read.
SKY_ELSE = (0.3, 0.5, 0.9)
# Wispy Edges raises the density's ramp through the edge to a power: 2 to
# the slider's value, and 2 to twice that above 0, so 4 at 1 and a half at
# -1. Hardening has the shorter way to go: at a quarter the edge was a step
# from one voxel to the next, and the voxels showed.
WISP_POWER = 2.0
# Dark Base at 1 takes this much off the colour at the very base, fading out
# by BASE_REACH of the cloud's height.
BASE_DEPTH = 0.9
BASE_REACH = 0.6
# How many times, as it shows in the picture, light is scattered on its way
# through a cloud in Cycles with the 12 bounces Set Up Render allows: a
# cloud of scattering colour c comes out about c to this power as bright as
# a white one (measured on 5.2 on a Cumulus, about: 0.94 for 0.99, 0.55 for 0.9,
# 0.32 for 0.8, which are the powers 6.2, 5.7 and 5.1; lower for darker
# colours, 3.6 at 0.5).
BOUNCES = 5.0


# The sockets of the parts that are not numbers.
LINKED = {"Way Out": 'NodeSocketVector', "To Sun": 'NodeSocketVector',
          "Sunlight": 'NodeSocketColor', "Skylight": 'NodeSocketColor'}


def _part(name, inputs, outputs):
    """A new group for a part, with its sockets: `inputs` are names of
    controls or of DESCRIPTIONS, the latter plain numbers meant to be
    linked; `outputs` are (name, socket type)."""
    ng = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    ng["cococlouds_version"] = SHADER_VERSION
    ng["cococlouds_kind"] = name
    controls = {c[0]: c for c in CONTROLS}
    for item in inputs:
        if item in controls:
            _n, stype, default, lo, hi, subtype, _where = controls[item]
            s = ng.interface.new_socket(item, in_out='INPUT', socket_type=stype, description=DESCRIPTIONS[item])
            if subtype:
                s.subtype = subtype
            s.default_value = default
            if lo is not None:
                s.min_value, s.max_value = lo, hi
        else:
            s = ng.interface.new_socket(item, in_out='INPUT', socket_type=LINKED.get(item, 'NodeSocketFloat'),
                                        description=DESCRIPTIONS[item])
            s.hide_value = True
    for item, stype in outputs:
        ng.interface.new_socket(item, in_out='OUTPUT', socket_type=stype)
    g = nodes.Graph(ng)
    return ng, g, g.node("NodeGroupInput").outputs, g.node("NodeGroupOutput")


def _unless(g, on, plain, changed, kind):
    """`changed`, or `plain` while a control is at the value that does
    nothing. Cycles drops what hangs on a Mix whose factor is a fixed 0,
    and that is the point: see "What a control costs" above."""
    ins = {0: on, 6: plain, 7: changed} if kind == 'RGBA' else {0: on, 2: plain, 3: changed}
    node = g.node("ShaderNodeMix", ins, data_type=kind)
    node.label = "Left Out at Rest"
    return node.outputs[2 if kind == 'RGBA' else 0]


def _build_data():
    """What the cloud tells its material, read from its two grids."""
    ng, g, _gi, go = _part(DATA, (), (("Density", 'NodeSocketFloat'), ("Edge to Core", 'NodeSocketFloat'),
                                      ("Height", 'NodeSocketFloat'), ("Is Cloud", 'NodeSocketFloat'),
                                      ("Way Out", 'NodeSocketVector')))
    density = g.node("ShaderNodeAttribute", attribute_name=nodes.GRID)
    density.label = "Density Grid"
    told = g.node("ShaderNodeAttribute", attribute_name=nodes.INFO)
    told.label = "Height, 1 / Full Density, 1"
    info = g.separate(told.outputs["Vector"])
    # The grid rises from 0 at the cloud's surface to the density of its
    # inside. Never quite 0: Wispy Edges raises it to a power below 0.
    core = g.node("ShaderNodeMath", {0: density.outputs["Fac"], 1: info["Y"]}, operation='MULTIPLY', use_clamp=True)
    core.label = "Part of Full Density"
    way = g.node("ShaderNodeAttribute", attribute_name=nodes.OUT)
    way.label = "Way Out Grid"
    g.link(go, {"Density": density.outputs["Fac"], "Edge to Core": g.math('MAXIMUM', core.outputs[0], 1e-4),
                "Height": info["X"], "Is Cloud": info["Z"], "Way Out": way.outputs["Vector"]})
    return ng


def _build_light():
    """The scene's light, as numbers a handler keeps up (_follow_light):
    one group for every material, so one place to write them."""
    ng, g, _gi, go = _part(LIGHT, (), (("To Sun", 'NodeSocketVector'), ("Sunlight", 'NodeSocketColor'),
                                       ("Skylight", 'NodeSocketColor')))
    for name, value in (("To Sun", (0.0, 0.0, 1.0)), ("Sunlight", (0.0, 0.0, 0.0)), ("Skylight", SKY_ELSE)):
        held = g.node("ShaderNodeCombineXYZ", dict(zip("XYZ", value)))
        held.name = held.label = name
        g.link(go, {name: held.outputs[0]})
    return ng


def _build_preview():
    """EEVEE's lighting, done by the shader: the light a place of the cloud
    is to give off, standing in for all that Cycles scatters.

    Lit by how far the way out of the cloud points at the sun, wrapped
    round; brighter looked at against the sun; darker at the base under a
    high sun; and never darker than the shade, a part of the sky's light
    and of the sun's."""
    ng, g, gi, go = _part(PREVIEW, ("Way Out", "Height", "To Sun", "Sunlight", "Skylight"),
                          (("Light", 'NodeSocketColor'),))
    world = g.node("ShaderNodeVectorTransform", {0: gi["Way Out"]}, vector_type='NORMAL',
                   convert_from='OBJECT', convert_to='WORLD')
    world.label = "Way Out, in the World"
    facing = g.vmath('DOT_PRODUCT', g.vmath('NORMALIZE', world.outputs[0]), gi["To Sun"]).node.outputs["Value"]
    lit = g.math('POWER', g.math('MAXIMUM', g.math('DIVIDE', g.math('ADD', facing, LIT_WRAP), 1.0 + LIT_WRAP), 0.0),
                 LIT_POWER)
    lit.node.label = "Facing the Sun"
    view = g.node("ShaderNodeNewGeometry").outputs["Incoming"]
    against = g.math('MAXIMUM', g.math('MULTIPLY', g.vmath('DOT_PRODUCT', view, gi["To Sun"]).node.outputs["Value"], -1.0), 0.0)
    forward = g.math('ADD', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', against, against), LIT_FORWARD))
    forward.node.label = "Silver Lining"
    overhead = g.math('MAXIMUM', g.separate(gi["To Sun"])["Z"], 0.0)
    shadow = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', overhead, LIT_SHADOW),
                                            g.math('SUBTRACT', 1.0, g.math('MAXIMUM', g.math('MINIMUM', gi["Height"], 1.0), 0.0))))
    shadow.node.label = "Its Own Shadow"
    level = g.math('MULTIPLY', g.math('MULTIPLY', g.math('MULTIPLY', lit, forward), shadow), LIT)
    sun = g.vmath('SCALE', gi["Sunlight"], scale=g.math('ADD', level, FILL_SUN))
    sky = g.vmath('SCALE', gi["Skylight"], scale=FILL_SKY)
    g.link(go, {"Light": g.vmath('ADD', sun, sky)})
    return ng


def _build_wisp():
    """Wispy Edges: a factor on the density, 1 while the control is at 0.

    The density's part of the full one, 0 to 1 through the edge, is raised
    to a power: above 1 the low values sink and the edge thins out, below 1
    they rise and it hardens. Principled Volume multiplies the grid by its
    Density, so what it is given is that part to the power less one."""
    ng, g, gi, go = _part(WISP, ("Wispy Edges", "Edge to Core", "Is Cloud"), (("Density", 'NodeSocketFloat'),))
    steep = g.math('MULTIPLY', gi["Wispy Edges"], g.math('ADD', g.math('MAXIMUM', gi["Wispy Edges"], 0.0), 1.0))
    power = g.node("ShaderNodeMath", {0: WISP_POWER, 1: steep}, operation='POWER')
    power.label = "Power for the Edge"
    wisp = g.math('POWER', gi["Edge to Core"], g.math('SUBTRACT', power.outputs[0], 1.0))
    known = g.node("ShaderNodeMix", {0: gi["Is Cloud"], 2: 1.0, 3: wisp}, data_type='FLOAT')
    known.label = "Only on a Cloud"
    g.link(go, {"Density": _unless(g, g.math('GREATER_THAN', g.math('ABSOLUTE', gi["Wispy Edges"]), 1e-3),
                                   1.0, known.outputs[0], 'FLOAT')})
    return ng


def _build_color():
    """The colour the cloud is to have where it is thick and lit: Color
    times Brightness, darker towards the base by Dark Base."""
    ng, g, gi, go = _part(COLOR, ("Color", "Brightness", "Dark Base", "Height", "Is Cloud"),
                          (("Color", 'NodeSocketColor'),))
    lit = g.vmath('SCALE', gi["Color"], scale=gi["Brightness"])
    low = g.node("ShaderNodeMapRange", {
        "Value": gi["Height"], "From Min": 0.0, "From Max": BASE_REACH, "To Min": 1.0, "To Max": 0.0,
    }, interpolation_type='SMOOTHSTEP')
    low.label = "1 at the Base, 0 Higher Up"
    shade = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', gi["Dark Base"], BASE_DEPTH),
                                           g.math('MULTIPLY', low.outputs[0], gi["Is Cloud"])))
    g.link(go, {"Color": _unless(g, g.math('GREATER_THAN', gi["Dark Base"], 1e-3), lit,
                                 g.vmath('SCALE', lit, scale=shade), 'RGBA')})
    return ng


def _build_glow():
    """Glow: the emission's strength, in the cloud's shape.

    Principled Volume does not shape its emission by the density (measured
    on 5.2: with a strength of 1 the whole box of voxels glowed), so the
    glow is multiplied by it here. By the density, so that a cloud glows
    the same whatever its size."""
    ng, g, gi, go = _part(GLOW, ("Glow", "Glow Color", "Density", "Thinning"),
                          (("Strength", 'NodeSocketFloat'), ("Color", 'NodeSocketColor'), ("Amount", 'NodeSocketFloat')))
    shaped = g.math('MULTIPLY', gi["Glow"], g.math('MULTIPLY', gi["Density"], gi["Thinning"]))
    g.link(go, {"Strength": _unless(g, g.math('GREATER_THAN', gi["Glow"], 1e-6), 0.0, shaped, 'FLOAT'),
                "Color": gi["Glow Color"], "Amount": gi["Glow"]})
    return ng


_BUILDERS = {DATA: _build_data, WISP: _build_wisp, COLOR: _build_color, GLOW: _build_glow,
             PREVIEW: _build_preview, LIGHT: _build_light}


def get_part(kind):
    """The current version of a part's group, building it when missing. One
    of another version is renamed out of the way and left to the materials
    that use it."""
    ng = bpy.data.node_groups.get(kind)
    if ng is not None and ng.get("cococlouds_version") == SHADER_VERSION and ng.get("cococlouds_kind") == kind:
        return ng
    if ng is not None:
        ng.name = f"{kind} v{ng.get('cococlouds_version', 0)}"
    ng = _BUILDERS[kind]()
    nodes.arrange(ng)
    return ng


def _build_tree(tree, values=None):
    """Lay a material's tree out as the cloud material, from nothing.
    `values`: {control: value} to begin with."""
    tree.nodes.clear()
    links = tree.links

    def node(type_, name, at, **props):
        n = tree.nodes.new(type_)
        for key, value in props.items():
            setattr(n, key, value)
        n.name = n.label = name
        n.location = at
        return n

    def part(kind, name, at):
        n = node("ShaderNodeGroup", name, at, node_tree=get_part(kind))
        n.width = 180
        return n

    data = part(DATA, "Cloud Data", (-900, 60))
    wisp = part(WISP, "Wispy Edges", (-620, 260))
    color = part(COLOR, "Color", (-620, 40))
    glow = part(GLOW, "Glow", (-620, -240))
    for target, socket in ((wisp, "Edge to Core"), (wisp, "Is Cloud"), (color, "Height"), (color, "Is Cloud"),
                           (glow, "Density")):
        links.new(data.outputs[socket], target.inputs[socket])
    links.new(wisp.outputs["Density"], glow.inputs["Thinning"])

    # Cycles. Light bounces in a cloud many times, each bounce taking the
    # scattering colour once more off it: with that colour a middle grey the
    # cloud comes out nearly black. So the colour asked for is turned into
    # the scattering colour that ends up as it, its BOUNCES-th root. White
    # stays white.
    bounces = node("ShaderNodeGamma", "Many Bounces", (-300, 300))
    bounces.inputs["Gamma"].default_value = 1.0 / BOUNCES
    links.new(color.outputs["Color"], bounces.inputs["Color"])
    # EEVEE. Its volume scatters nothing (a black Color) and gives off the
    # light Preview Light works out, in the cloud's colour, with the glow on
    # top. A volume that only dims and glows comes out, where it is thick,
    # as bright as its emission over its density: so the strength is the
    # density, and the colour is the light wanted.
    light = part(LIGHT, "Scene Light", (-900, -420))
    preview = part(PREVIEW, "Preview Light", (-620, -470))
    for socket in ("Way Out", "Height"):
        links.new(data.outputs[socket], preview.inputs[socket])
    for socket in ("To Sun", "Sunlight", "Skylight"):
        links.new(light.outputs[socket], preview.inputs[socket])
    tinted = node("ShaderNodeMix", "In the Cloud's Color", (-300, -200), data_type='RGBA', blend_type='MULTIPLY')
    tinted.inputs[0].default_value = 1.0
    links.new(preview.outputs["Light"], tinted.inputs[6])
    links.new(color.outputs["Color"], tinted.inputs[7])
    glowing = node("ShaderNodeVectorMath", "Glow's Light", (-300, -420), operation='SCALE')
    links.new(glow.outputs["Color"], glowing.inputs[0])
    links.new(glow.outputs["Amount"], glowing.inputs[3])
    both = node("ShaderNodeVectorMath", "Light and Glow", (-120, -300), operation='ADD')
    links.new(tinted.outputs[2], both.inputs[0])
    links.new(glowing.outputs[0], both.inputs[1])
    shaped = node("ShaderNodeMath", "In the Cloud's Shape", (-300, -600), operation='MULTIPLY')
    links.new(data.outputs["Density"], shaped.inputs[0])
    links.new(wisp.outputs["Density"], shaped.inputs[1])

    # The Anisotropy control (Silver Lining up to 0.14.0) is that of Cycles'
    # volume alone.
    for name, at, target, feed in (
            (CYCLES, (120, 420), 'CYCLES', (bounces.outputs["Color"], wisp.outputs["Density"], glow.outputs["Strength"],
                                            glow.outputs["Color"])),
            (EEVEE, (120, -120), 'EEVEE', (None, wisp.outputs["Density"], shaped.outputs[0], both.outputs[0]))):
        volume = node("ShaderNodeVolumePrincipled", name, at)
        volume.inputs["Density Attribute"].default_value = nodes.GRID
        volume.inputs["Anisotropy"].default_value = 0.0
        volume.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        for socket, source in zip(("Color", "Density", "Emission Strength", "Emission Color"), feed):
            if source is not None:
                links.new(source, volume.inputs[socket])
        out = node("ShaderNodeOutputMaterial", f"Output for {name}", (at[0] + 320, at[1]), target=target)
        links.new(volume.outputs[0], out.inputs["Volume"])
        frame = node("NodeFrame", "Cycles: Blender's own volume shader" if target == 'CYCLES'
                     else "EEVEE, the preview: a volume that gives off the light worked out for it", (0, 0))
        for member in (volume, out) + ((bounces,) if target == 'CYCLES' else (tinted, glowing, both, shaped)):
            member.parent = frame
    frame = node("NodeFrame", "What goes into it: CocoClouds' parts, a group each (Tab)", (0, 0))
    for member in (data, wisp, color, glow, light, preview):
        member.parent = frame

    found = controls_of(tree)
    for name, _stype, default, *_rest in CONTROLS:
        found[name].default_value = (values or {}).get(name, default)
    follow_light(bpy.context.scene)


def _block(tree):
    """The one node of a material of 0.9.0, the group with every control."""
    return next((n for n in tree.nodes if n.bl_idname == "ShaderNodeGroup"
                 and n.node_tree is not None and n.node_tree.get("cococlouds_kind") == BLOCK_NAME), None)


def controls_of(tree):
    """{control: socket} for the controls a material's tree has, in the
    order of CONTROLS. A socket something is linked into is not a control:
    the link has the say."""
    block = _block(tree)
    if block is not None:
        named = ((c[0], BLOCK_NAMES.get(c[0], c[0])) for c in CONTROLS)
        return {name: block.inputs[old] for name, old in named if old in block.inputs}
    parts = {}
    for n in tree.nodes:
        if n.bl_idname == "ShaderNodeGroup" and n.node_tree is not None:
            parts.setdefault(n.node_tree.get("cococlouds_kind"), n)
    found = {}
    for name, *_rest, where in CONTROLS:
        if isinstance(where, str):
            holder, socket = parts.get(where), name
        else:
            holder, socket = tree.nodes.get(where[0]), where[1]
            if holder is not None and holder.bl_idname != "ShaderNodeVolumePrincipled":
                holder = None
        if holder is not None and socket in holder.inputs and not holder.inputs[socket].is_linked:
            found[name] = holder.inputs[socket]
    return found


def controls(mat):
    """{control: socket} for the controls a material has, to draw and to
    set (`.default_value`). Empty for a material without any."""
    tree = mat.node_tree if mat is not None else None
    return controls_of(tree) if tree is not None else {}


def is_block(mat):
    """True for a material still as 0.9.0 made it: one node with every
    control, which split() lays out as nodes."""
    tree = mat.node_tree if mat is not None else None
    return tree is not None and _block(tree) is not None


def is_old(mat):
    """True for a cloud material of an earlier version: the one node of
    0.9.0, or nodes holding parts this version builds otherwise. It works
    as it did; split() makes it this version's, with the values it has."""
    tree = mat.node_tree if mat is not None else None
    if tree is None:
        return False
    if _block(tree) is not None:
        return True
    held = [n.node_tree for n in tree.nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree is not None
            and n.node_tree.get("cococlouds_kind") in _BUILDERS]
    return bool(held) and any(ng.get("cococlouds_version") != SHADER_VERSION for ng in held)


def _untouched(tree):
    """True for a tree as an earlier version laid it out, nothing added:
    the one node of 0.9.0 and its outputs, or 0.10.0's fourteen nodes."""
    if _block(tree) is not None:
        return len(tree.nodes) == 3
    names = {n.name for n in tree.nodes}
    return len(tree.nodes) == 14 and {"Cloud Data", "Wispy Edges", "Color", "Glow", "Many Bounces",
                                      "Thinner for EEVEE", "Glow for EEVEE", CYCLES, EEVEE} <= names


def split(mat):
    """Lay a material of an earlier version out as this one's nodes, with
    the values it has. What else is in its tree goes."""
    _build_tree(mat.node_tree, {name: (tuple(s.default_value) if hasattr(s.default_value, "__len__") else s.default_value)
                                for name, s in controls(mat).items()})


def is_plain(mat):
    """True for the material of 0.8.0 and before, as CocoClouds made it:
    two white Principled Volumes and their outputs, nothing changed."""
    tree = mat.node_tree if mat is not None else None
    if tree is None or len(tree.nodes) != 4:
        return False
    volumes = [n for n in tree.nodes if n.bl_idname == "ShaderNodeVolumePrincipled"]
    made = {(1.0, 0.6), (EEVEE_DENSITY, 0.0)}
    return len(volumes) == 2 and all(
        not any(s.is_linked for s in n.inputs)
        and all(abs(c - 1.0) < 1e-6 for c in n.inputs["Color"].default_value)
        and n.inputs["Emission Strength"].default_value == 0.0
        and any(abs(n.inputs["Density"].default_value - d) < 1e-6
                and abs(n.inputs["Anisotropy"].default_value - a) < 1e-6 for d, a in made)
        for n in volumes)


def material():
    """The cloud material all clouds share, made on first use.

    A material by that name without a control is the one of 0.8.0 and
    before, or one the user emptied: it is renamed and stays with the
    clouds that have it. One of an earlier version that nothing was added
    to is made this version's on the way: in Cycles it renders the same."""
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is not None and controls(mat):
        if is_old(mat) and _untouched(mat.node_tree):
            split(mat)
        return mat
    if mat is not None:
        mat.name = PLAIN_NAME
    mat = bpy.data.materials.new(MATERIAL_NAME)
    _build_tree(mat.node_tree)
    return mat


def scene_light(scene):
    """(the way to the sun, its light, the sky's light) as a scene has
    them, for Preview Light. The sun is the strongest Sun light that
    renders; without one its light is nothing. The sky's light is the
    world's Background colour times its strength where that is a plain
    colour, SKY_ELSE times the strength where something is linked into it."""
    to_sun, sunlight, best = (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 0.0
    for ob in scene.objects:
        if ob.type == 'LIGHT' and ob.data.type == 'SUN' and not ob.hide_render and ob.data.energy > best:
            best = ob.data.energy
            to_sun = tuple(ob.matrix_world.to_3x3().col[2].normalized())
            sunlight = tuple(c * best for c in ob.data.color)
    skylight = (0.0, 0.0, 0.0)
    world = scene.world
    tree = world.node_tree if world is not None else None
    back = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeBackground" and n.outputs[0].is_linked), None) \
        if tree is not None else None
    if back is not None:
        strength = back.inputs["Strength"].default_value
        color = SKY_ELSE if back.inputs["Color"].is_linked else tuple(back.inputs["Color"].default_value)[:3]
        skylight = tuple(c * strength for c in color)
    elif world is not None:
        skylight = tuple(world.color)
    return to_sun, sunlight, skylight


def follow_light(scene):
    """Copy a scene's light into Scene Light, where it differs. Returns
    whether anything was written."""
    ng = bpy.data.node_groups.get(LIGHT)
    if ng is None or ng.get("cococlouds_kind") != LIGHT:
        return False
    wrote = False
    for name, value in zip(("To Sun", "Sunlight", "Skylight"), scene_light(scene)):
        held = ng.nodes.get(name)
        if held is None:
            continue
        for socket, part in zip(held.inputs, value):
            if abs(socket.default_value - part) > 1e-5:
                socket.default_value = part
                wrote = True
    return wrote


@bpy.app.handlers.persistent
def _follow_light(scene, depsgraph=None):
    """After every change in the viewport's scene, and before a render."""
    if depsgraph is not None and depsgraph.mode != 'VIEWPORT':
        return
    follow_light(scene)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_follow_light)
    bpy.app.handlers.render_pre.append(_follow_light)


def unregister():
    bpy.app.handlers.render_pre.remove(_follow_light)
    bpy.app.handlers.depsgraph_update_post.remove(_follow_light)
