"""The cloud's material, and the few things to set on it.

The material is laid out in the Shader Editor as a handful of nodes to read
from left to right, and to cut into:

    Cloud Data ──> Color ──> Many Bounces ──> two Principled Volumes, added ──> Output (Cycles)
               └─> Glow ──────────────────────>       "
    Scene Light ──> Preview Light ──> (light, colour, glow) ──> Principled Volume ──> Output (EEVEE)

Cycles. A cloud is white and soft because light scatters in it many times.
Two Principled Volumes, added: one at the Anisotropy control, light going
on forwards; the other with an anisotropy that halves at every bounce (0.5,
0.25, 0.125...), read from the ray's depth. A first bounce off a droplet
throws light forwards, the light that has bounced many times comes out every
way. This is how Cloud Creator Lite's material works (its graph read and
rebuilt here, not copied); rendered on the same cloud, the rebuilt pair and
Lite's own gave the same picture to the third decimal (2026-10-15). Both
scatter white and absorb nothing, so it is the bounces that make the cloud.

The nodes before them are small groups built here (the parts), one job each.
The controls of the Look panel are sockets of those nodes, found by the kind
of group a node holds (controls()): the panel shows whichever of them the
material still has, so nodes can be put between, taken out or swapped for
others. A copy of the material has values of its own; the groups inside are
the same for all.

Cloud Data reads the cloud's grids (nodes.py): "density", and the coarse
"cococlouds", how high in the cloud a place is. On a volume without it,
another add-on's, Dark Base does nothing and the rest works.

What a control costs. Cycles renders a Principled Volume that reads its grid
by itself, everything else on it a fixed number, a good deal quicker than
one with an Attribute node anywhere in its material (measured on 5.2, about
6 s more to prepare a render of a field of 77 clouds). So Color and
Anisotropy are free, and the two controls that read a grid, Dark Base and
Glow, are cut out of the graph while they are at the value that does
nothing (`_unless`): each part ends in a Mix whose factor is then a fixed 0,
and Cycles drops what hangs on it.

EEVEE lights a volume once, and a cloud is what it is by light scattered
many times: left to its own lighting a cloud is either a pale ghost or a dark
lump with a lit skin (both tried on 5.2). So in EEVEE the cloud's volume
scatters nothing and gives off, as light of its own, what Cycles would have
scattered: the part Preview Light works that out from the way out of the
cloud at each place (nodes.OUT) and from where the sun is, which a shader
cannot ask; the sun, its light and the sky's are numbers in one more group,
Scene Light, that a handler copies from the scene (_follow_light). What that
leaves out: every light but the strongest sun, and a cloud's shadow on
itself and on other clouds, stood in for by a darker base under a high sun.

Like the geometry group the parts are built here and carry a version; a
change to a graph bumps SHADER_VERSION, and a group of another version is
renamed out of the way for the materials that use it (see get_part).
"""

import bpy

from . import nodes

MATERIAL_NAME = "CocoClouds Cloud"
SHADER_VERSION = 5

# The parts, by the name of their group.
DATA = "CocoClouds Data"
COLOR = "CocoClouds Color"
GLOW = "CocoClouds Glow"
PREVIEW = "CocoClouds Preview Light"
LIGHT = "CocoClouds Scene Light"
# The names the Principled Volume nodes are given.
CYCLES = "Cycles"
CYCLES_BOUNCED = "Cycles, Many Bounces"
EEVEE = "EEVEE"

# (name, socket type, default, min, max, subtype, where) for the controls.
# Where: the part whose node has the control as an input of the same name,
# or the name of a Principled Volume and of its socket.
CONTROLS = (
    ("Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None, None, COLOR),
    ("Dark Base", 'NodeSocketFloat', 0.0, 0.0, 1.0, 'FACTOR', COLOR),
    ("Glow", 'NodeSocketFloat', 0.0, 0.0, 1000.0, 'NONE', GLOW),
    ("Glow Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None, None, GLOW),
    ("Anisotropy", 'NodeSocketFloat', 1.0, 0.0, 1.0, 'FACTOR', (CYCLES, "Anisotropy")),
)

DESCRIPTIONS = {
    "Color": "The colour of the cloud. White is a white cloud whatever the light",
    "Dark Base": ("Darken the cloud towards its base, as under a thick cloud. "
                  "Above 0, Cycles takes longer to prepare a render"),
    "Glow": ("Light the cloud gives off by itself, for night skies and lightning. 1 is about a white wall "
             "in daylight. Above 0, Cycles takes longer to prepare a render"),
    "Glow Color": "Colour of the glow",
    "Anisotropy": ("Cycles only. How much of the light a first bounce throws forwards: higher, the edges "
                   "glow against the sun and the cloud is softer with the sun behind you"),
    # What the other nodes hand a part.
    "Density": "The cloud's density, from Cloud Data",
    "Height": "How high in the cloud, 0 at its base to 1 at its top, from Cloud Data",
    "Is Cloud": "1 on a cloud that says so, from Cloud Data. At 0 the control is left out",
    "Way Out": "The way out of the cloud at each place, from Cloud Data",
    "To Sun": "The way to the sun, from Scene Light",
    "Sunlight": "The sun's colour times its strength, from Scene Light",
    "Skylight": "The world's colour times its strength, from Scene Light",
}

# Preview Light, tuned on 5.2 against Cycles with 64 bounces, a Cumulus, a
# Tower and a Puff under a sun of strength 5 from the front, the side, the
# back and above, in a plain blue world (probes/lookdev_match.py, 0.11.0);
# again in 0.21.0 against Cycles with 128 bounces at Density 90, a sun in
# front, at the side, behind, above and at sunset (probes/probe_light.py),
# where LIT went from 0.32 to 0.2.
# The lit side: the sunlight times LIT, by how far a place faces the sun.
# Wrapped, since light gets round a cloud: a place facing LIT_WRAP away
# from the sun is the first in the dark.
LIT = 0.2
LIT_WRAP = 0.6
LIT_POWER = 1.6
# Looked at against the sun (0.21.0, against Cycles under a sun behind the
# cloud and at sunset): a thick cloud's body goes dark, the light no longer
# wrapping round it, and only its edges, thin as the camera sees them, shine:
# the silver lining, LIT_RIM times the lit side at most, sharper by
# RIM_POWER. Before, the whole face was brightened and a sunset turned the
# cloud orange all over.
LIT_RIM = 8.0
RIM_POWER = 3.0
# With the sun overhead the base is this much darker: the cloud's own
# shadow, which nothing here can work out.
LIT_SHADOW = 0.5
# The shade: this much of the sky's light and of the sun's.
FILL_SKY = 0.6
FILL_SUN = 0.04
# Looked at against the sun the shade is the sky's light only (the sun's share
# goes, see _build_preview), and a little more of it: Cycles' cloud lit from
# behind is the sky's blue, about as dark as this makes it (0.21.0).
FILL_AGAINST = -0.15
# The sky's light when the world gives no plain colour to read.
SKY_ELSE = (0.3, 0.5, 0.9)
# A scene without a Sun light (a new one has a point light) still shows its
# clouds lit in EEVEE, by this sun from the upper left, as strong as a sun
# of strength 3: without it they were dark smoke in Material Preview.
SUN_ELSE = ((-0.38, -0.46, 0.80), 3.0)
# Dark Base at 1 takes this much off the colour at the very base, fading out
# by BASE_REACH of the cloud's height.
BASE_DEPTH = 0.9
BASE_REACH = 0.6
# Light is scattered many times on its way through a cloud, each time taking
# the scattering colour once more off it: a cloud of scattering colour c
# comes out about c to this power as bright as a white one (measured on 5.2
# at 12 bounces: 0.94 for 0.99, 0.55 for 0.9). So the colour asked for is
# turned into its BOUNCES-th root. White stays white.
BOUNCES = 5.0
# The many-bounce lobe's anisotropy: this to the power of the ray's depth
# plus one.
BOUNCE_FADE = 0.5


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
    """What the cloud tells its material, read from its grids."""
    ng, g, _gi, go = _part(DATA, (), (("Density", 'NodeSocketFloat'), ("Height", 'NodeSocketFloat'),
                                      ("Is Cloud", 'NodeSocketFloat'), ("Way Out", 'NodeSocketVector')))
    density = g.node("ShaderNodeAttribute", attribute_name=nodes.GRID)
    density.label = "Density Grid"
    told = g.node("ShaderNodeAttribute", attribute_name=nodes.INFO)
    told.label = "Height, 1 / Full Density, 1"
    info = g.separate(told.outputs["Vector"])
    way = g.node("ShaderNodeAttribute", attribute_name=nodes.OUT)
    way.label = "Way Out Grid"
    g.link(go, {"Density": density.outputs["Fac"], "Height": info["X"], "Is Cloud": info["Z"],
                "Way Out": way.outputs["Vector"]})
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
    round unless looked at against the sun; then its edges shine instead;
    darker at the base under a high sun; and never darker than the shade, a
    part of the sky's light and of the sun's."""
    ng, g, gi, go = _part(PREVIEW, ("Way Out", "Height", "To Sun", "Sunlight", "Skylight"),
                          (("Light", 'NodeSocketColor'),))
    world = g.node("ShaderNodeVectorTransform", {0: gi["Way Out"]}, vector_type='NORMAL',
                   convert_from='OBJECT', convert_to='WORLD')
    world.label = "Way Out, in the World"
    out = g.vmath('NORMALIZE', world.outputs[0])
    facing = g.vmath('DOT_PRODUCT', out, gi["To Sun"]).node.outputs["Value"]
    view = g.node("ShaderNodeNewGeometry").outputs["Incoming"]
    against = g.math('MAXIMUM', g.math('MULTIPLY', g.vmath('DOT_PRODUCT', view, gi["To Sun"]).node.outputs["Value"], -1.0), 0.0)
    wrap = g.math('MULTIPLY', LIT_WRAP, g.math('SUBTRACT', 1.0, against))
    lit = g.math('POWER', g.math('MAXIMUM', g.math('DIVIDE', g.math('ADD', facing, wrap), g.math('ADD', wrap, 1.0)), 0.0),
                 LIT_POWER)
    lit.node.label = "Facing the Sun"
    edge = g.math('SUBTRACT', 1.0, g.math('ABSOLUTE', g.vmath('DOT_PRODUCT', out, view).node.outputs["Value"]))
    # On the edges towards the sun only: at an edge the way out is across
    # the view, and how far it points at the sun, over how far the sun is
    # off the view's line, says which side of the cloud the sun is on.
    off = g.math('MAXIMUM', g.math('SQRT', g.math('SUBTRACT', 1.0, g.math('MULTIPLY', against, against))), 0.1)
    towards = g.math('DIVIDE', facing, off, clamp=True)
    rim = g.math('MULTIPLY', g.math('MULTIPLY', g.math('MULTIPLY', against, against), g.math('POWER', edge, RIM_POWER)),
                 g.math('MULTIPLY', towards, LIT_RIM))
    rim.node.label = "Silver Lining"
    overhead = g.math('MAXIMUM', g.separate(gi["To Sun"])["Z"], 0.0)
    shadow = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', overhead, LIT_SHADOW),
                                            g.math('SUBTRACT', 1.0, g.math('MAXIMUM', g.math('MINIMUM', gi["Height"], 1.0), 0.0))))
    shadow.node.label = "Its Own Shadow"
    level = g.math('MULTIPLY', g.math('MULTIPLY', g.math('ADD', lit, rim), shadow), LIT)
    # The sun's share of the shade is light it threw through the cloud: none comes
    # out on the near side of a cloud lit from behind.
    sun = g.vmath('SCALE', gi["Sunlight"], scale=g.math('ADD', level, g.math('MULTIPLY', FILL_SUN, g.math('SUBTRACT', 1.0, against))))
    sky = g.vmath('SCALE', gi["Skylight"], scale=g.math('MULTIPLY', FILL_SKY,
                                                        g.math('SUBTRACT', 1.0, g.math('MULTIPLY', against, FILL_AGAINST))))
    g.link(go, {"Light": g.vmath('ADD', sun, sky)})
    return ng


def _build_color():
    """The colour of the cloud, darker towards the base by Dark Base."""
    ng, g, gi, go = _part(COLOR, ("Color", "Dark Base", "Height", "Is Cloud"), (("Color", 'NodeSocketColor'),))
    low = g.node("ShaderNodeMapRange", {
        "Value": gi["Height"], "From Min": 0.0, "From Max": BASE_REACH, "To Min": 1.0, "To Max": 0.0,
    }, interpolation_type='SMOOTHSTEP')
    low.label = "1 at the Base, 0 Higher Up"
    shade = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', gi["Dark Base"], BASE_DEPTH),
                                           g.math('MULTIPLY', low.outputs[0], gi["Is Cloud"])))
    g.link(go, {"Color": _unless(g, g.math('GREATER_THAN', gi["Dark Base"], 1e-3), gi["Color"],
                                 g.vmath('SCALE', gi["Color"], scale=shade), 'RGBA')})
    return ng


def _build_glow():
    """Glow: the emission's strength, in the cloud's shape.

    Principled Volume does not shape its emission by the density (measured
    on 5.2: with a strength of 1 the whole box of voxels glowed), so the
    glow is multiplied by it here."""
    ng, g, gi, go = _part(GLOW, ("Glow", "Glow Color", "Density"),
                          (("Strength", 'NodeSocketFloat'), ("Color", 'NodeSocketColor'), ("Amount", 'NodeSocketFloat')))
    shaped = g.math('MULTIPLY', gi["Glow"], gi["Density"])
    g.link(go, {"Strength": _unless(g, g.math('GREATER_THAN', gi["Glow"], 1e-6), 0.0, shaped, 'FLOAT'),
                "Color": gi["Glow Color"], "Amount": gi["Glow"]})
    return ng


_BUILDERS = {DATA: _build_data, COLOR: _build_color, GLOW: _build_glow, PREVIEW: _build_preview, LIGHT: _build_light}


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

    def frame(label, members):
        f = node("NodeFrame", label, (0, 0))
        for member in members:
            member.parent = f

    data = part(DATA, "Cloud Data", (-900, 60))
    color = part(COLOR, "Color", (-620, 160))
    glow = part(GLOW, "Glow", (-620, -100))
    for target, socket in ((color, "Height"), (color, "Is Cloud"), (glow, "Density")):
        links.new(data.outputs[socket], target.inputs[socket])

    # Cycles: two lobes added, see the top of this file.
    bounces = node("ShaderNodeGamma", "Many Bounces", (-300, 300))
    bounces.inputs["Gamma"].default_value = 1.0 / BOUNCES
    links.new(color.outputs["Color"], bounces.inputs["Color"])
    depth = node("ShaderNodeLightPath", "Light Path", (-300, 620))
    later = node("ShaderNodeMath", "Bounces So Far, Plus One", (-120, 620), operation='ADD')
    links.new(depth.outputs["Ray Depth"], later.inputs[0])
    later.inputs[1].default_value = 1.0
    fade = node("ShaderNodeMath", "Anisotropy Halving per Bounce", (40, 620), operation='POWER')
    fade.inputs[0].default_value = BOUNCE_FADE
    links.new(later.outputs[0], fade.inputs[1])
    lobes = []
    for name, at in ((CYCLES, (240, 520)), (CYCLES_BOUNCED, (240, 160))):
        volume = node("ShaderNodeVolumePrincipled", name, at)
        volume.inputs["Density Attribute"].default_value = nodes.GRID
        volume.inputs["Density"].default_value = 1.0
        volume.inputs["Absorption Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        links.new(bounces.outputs["Color"], volume.inputs["Color"])
        lobes.append(volume)
    links.new(fade.outputs[0], lobes[1].inputs["Anisotropy"])
    # The glow on one lobe only, or it would count twice.
    links.new(glow.outputs["Strength"], lobes[1].inputs["Emission Strength"])
    links.new(glow.outputs["Color"], lobes[1].inputs["Emission Color"])
    both = node("ShaderNodeAddShader", "Both Lobes", (520, 340))
    links.new(lobes[0].outputs[0], both.inputs[0])
    links.new(lobes[1].outputs[0], both.inputs[1])
    out = node("ShaderNodeOutputMaterial", "Output for Cycles", (700, 340), target='CYCLES')
    links.new(both.outputs[0], out.inputs["Volume"])
    frame("Cycles: two Principled Volumes, one throwing light forwards, one for light bounced many times",
          (bounces, depth, later, fade, *lobes, both, out))

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
    tinted = node("ShaderNodeMix", "In the Cloud's Color", (-300, -300), data_type='RGBA', blend_type='MULTIPLY')
    tinted.inputs[0].default_value = 1.0
    links.new(preview.outputs["Light"], tinted.inputs[6])
    links.new(color.outputs["Color"], tinted.inputs[7])
    glowing = node("ShaderNodeVectorMath", "Glow's Light", (-300, -520), operation='SCALE')
    links.new(glow.outputs["Color"], glowing.inputs[0])
    links.new(glow.outputs["Amount"], glowing.inputs[3])
    lit = node("ShaderNodeVectorMath", "Light and Glow", (-120, -400), operation='ADD')
    links.new(tinted.outputs[2], lit.inputs[0])
    links.new(glowing.outputs[0], lit.inputs[1])
    eevee = node("ShaderNodeVolumePrincipled", EEVEE, (240, -300))
    eevee.inputs["Density Attribute"].default_value = nodes.GRID
    eevee.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    eevee.inputs["Anisotropy"].default_value = 0.0
    links.new(data.outputs["Density"], eevee.inputs["Emission Strength"])
    links.new(lit.outputs[0], eevee.inputs["Emission Color"])
    out = node("ShaderNodeOutputMaterial", "Output for EEVEE", (560, -300), target='EEVEE')
    links.new(eevee.outputs[0], out.inputs["Volume"])
    frame("EEVEE: a volume that gives off the light worked out for it", (tinted, glowing, lit, eevee, out))
    frame("What goes into it: CocoClouds' parts, a group each (Tab)", (data, color, glow, light, preview))

    found = controls_of(tree)
    for name, _stype, default, *_rest in CONTROLS:
        found[name].default_value = (values or {}).get(name, default)
    follow_light(bpy.context.scene)


def controls_of(tree):
    """{control: socket} for the controls a material's tree has, in the
    order of CONTROLS. A socket something is linked into is not a control:
    the link has the say."""
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


def is_old(mat):
    """True for a cloud material of an earlier version: nodes holding parts
    this version builds otherwise. Update Material makes it this version's
    with the values it has."""
    tree = mat.node_tree if mat is not None else None
    if tree is None:
        return False
    held = [n.node_tree for n in tree.nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree is not None
            and n.node_tree.get("cococlouds_kind", "").startswith("CocoClouds")]
    return bool(held) and any(ng.get("cococlouds_version") != SHADER_VERSION for ng in held)


def rebuild(mat):
    """Lay a material out as this version's nodes, with the control values
    it has. What else is in its tree goes."""
    _build_tree(mat.node_tree, {name: (tuple(s.default_value) if hasattr(s.default_value, "__len__") else s.default_value)
                                for name, s in controls(mat).items()})


def material():
    """The cloud material all clouds share, made on first use. One of an
    earlier version is made this version's on the way."""
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is not None and (controls(mat) or is_old(mat)):
        if is_old(mat):
            rebuild(mat)
        return mat
    if mat is not None:
        mat.name = MATERIAL_NAME + " (old)"
    mat = bpy.data.materials.new(MATERIAL_NAME)
    _build_tree(mat.node_tree)
    return mat


def scene_light(scene):
    """(the way to the sun, its light, the sky's light) as a scene has
    them, for Preview Light. The sun is the strongest Sun light that
    renders; without one, SUN_ELSE. The sky's light is the
    world's Background colour times its strength where that is a plain
    colour, SKY_ELSE times the strength where something is linked into it."""
    to_sun, sunlight, best = SUN_ELSE[0], (SUN_ELSE[1],) * 3, 0.0
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
