"""What a cloud is, and how one is made.

A cloud is a mesh or curve object carrying the Cloud modifier, in four
parts, as the panel shows them:

- Geometry: the mesh, the cloud's rough outline. Either the generator's
  heap of spheres (shapes.py), drawn again whenever one of its settings,
  kept on the object, changes; or a mesh of the user's own, as plain as a
  box, which is never written to. A Cirrus is a curve instead: its strokes,
  drawn by the generator or by the user with the Draw tool, are the
  outline.
- Deform: the modifier fills the mesh with balls moved and sized by one
  noise (nodes.py).
- Material: the object's first material slot (look.py).
- Render: the modifier's voxels in the viewport and in a render.

A genus (a real cloud genus) is a set of starting values for Geometry and
Deform. Giving a cloud a genus writes them all.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup

from . import look, nodes, shapes

MODIFIER_NAME = "CocoClouds"


def inp(mod, name):
    """The modifier's input struct for a group socket; its `value` is the
    setting. On 5.2 a Geometry Nodes modifier keeps its inputs under
    `properties.inputs.<identifier>`, not as ID properties."""
    return getattr(mod.properties.inputs, nodes.socket_id(mod.node_group, name))


def get(mod, name):
    return inp(mod, name).value


def put(mod, name, value):
    inp(mod, name).value = value


def has_input(mod, name):
    """False for an input the group this cloud uses does not have."""
    return nodes.socket_id(mod.node_group, name) is not None


# The object types a cloud can be: a mesh, or a curve whose strokes the
# group makes tubes of.
KINDS = ('MESH', 'CURVE')


def cloud_modifier(ob):
    if ob is None or ob.type not in KINDS:
        return None
    for mod in ob.modifiers:
        if mod.type == 'NODES' and nodes.is_group(mod.node_group):
            return mod
    return None


def is_cloud(ob):
    return cloud_modifier(ob) is not None


# The cloud's material sits in the object's first material slot, where any
# object's material is looked for and changed: the Material tab, the Shader
# Editor. Blender does not render a volume made by nodes with it, though
# (measured on 5.2: with the material only in the slot, Cycles drew a black
# silhouette whichever way the slot was linked). The group has to set it on
# the volume, and no node reads a slot. So the group keeps its Material
# input, and a handler copies the slot into it whenever the two differ
# (_follow_slots).
#
# SLOT_KEY says how an object got the slot, for Back to Mesh to undo it:
# 'ADDED', the mesh had no material and was given one; 'OBJECT', the mesh
# had a material of its own there, which was left in the mesh and covered
# by the cloud's, linked to the object.
SLOT_KEY = "cococlouds_slot"


def _is_volume(mat):
    tree = mat.node_tree if mat is not None else None
    return tree is not None and any(
        n.bl_idname == "ShaderNodeOutputMaterial" and n.inputs["Volume"].is_linked for n in tree.nodes)


def slot_material(ob):
    """The material in an object's first slot, None without one."""
    return ob.material_slots[0].material if ob.material_slots else None


def _give_slot(ob, mat):
    """Put a cloud's material in the object's first slot, unless a volume
    material is there already."""
    slots = ob.material_slots
    if not slots:
        ob.data.materials.append(mat)
        ob[SLOT_KEY] = 'ADDED'
    elif slots[0].material is None:
        slots[0].material = mat
        ob[SLOT_KEY] = 'ADDED'
    elif slots[0].material != mat and not _is_volume(slots[0].material):
        slots[0].link = 'OBJECT'
        slots[0].material = mat
        ob[SLOT_KEY] = 'OBJECT'


def _take_slot(ob):
    """Undo _give_slot."""
    how = ob.get(SLOT_KEY)
    if how == 'OBJECT' and ob.material_slots:
        ob.material_slots[0].material = None
        ob.material_slots[0].link = 'DATA'
    elif how == 'ADDED' and len(ob.data.materials) == 1:
        ob.data.materials.clear()
    if SLOT_KEY in ob:
        del ob[SLOT_KEY]


def set_material(ob, mat):
    """Put a material in a cloud's first slot and in its modifier."""
    if ob.material_slots:
        ob.material_slots[0].material = mat
    else:
        _give_slot(ob, mat)
    put(cloud_modifier(ob), "Material", mat)
    ob.update_tag()


def sync_material(ob):
    """Copy the first slot's material into the cloud's modifier when they
    differ. An empty slot, or none, changes nothing: the cloud keeps the
    material it has."""
    mod = cloud_modifier(ob)
    if mod is None or not has_input(mod, "Material"):
        return
    want = slot_material(ob)
    if want is not None and get(mod, "Material") != want:
        put(mod, "Material", want)
        # Written from a handler, the input alone does not have the modifier
        # worked out again (seen without a window).
        ob.update_tag()


@persistent
def _follow_slots(scene, depsgraph):
    """After every change in the viewport's scene: the objects that changed
    and the active one, which is the one the Material tab and the Shader
    Editor write to. Writing the modifier brings this round again, with
    nothing left to copy."""
    if depsgraph.mode != 'VIEWPORT':
        return
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Object):
            sync_material(update.id.original)
    active = depsgraph.view_layer.objects.active
    if active is not None:
        sync_material(active.original)


def make_cloud(ob, settings=None):
    """Give a mesh object the Cloud modifier, or return the one it has."""
    mod = cloud_modifier(ob)
    if mod is None:
        mod = ob.modifiers.new(MODIFIER_NAME, 'NODES')
        mod.node_group = nodes.get_group()
        _give_slot(ob, look.material())
        put(mod, "Material", slot_material(ob))
    for name, value in (settings or {}).items():
        put(mod, name, value)
    ob.update_tag()
    return mod


def is_current(mod):
    """False for a cloud still on a group of an earlier version."""
    return nodes.is_current(mod.node_group)


def update_cloud(mod):
    """Move a cloud to the current group, keeping the settings both have.
    Sockets are matched by name: their identifiers differ between versions.
    A cloud from before 0.20.0 keeps little: its shape was made otherwise."""
    old = mod.node_group
    kept = {name: get(mod, name) for name, *_ in nodes.INPUTS if nodes.socket_id(old, name)}
    mod.node_group = nodes.get_group()
    for name, value in kept.items():
        put(mod, name, value)
    ob = mod.id_data
    if SLOT_KEY not in ob:
        _give_slot(ob, kept.get("Material") or look.material())
    put(mod, "Material", slot_material(ob))
    ob.update_tag()


# ---------------------------------------------------------------- genera
#
# A genus: (identifier, label, description, settings), the identifier the
# builder's in shapes.py. Settings holds the generator's (lower case, kept
# on the object: the dimensions and shapes.SETTINGS) and the modifier's
# Deform settings (by socket name). Lengths are metres for the dimensions,
# parts of the cloud's longest side for the rest.

def _genus(dimensions, generator, puff, strength, scale, detail, roughness, distortion, flat_base, density=90.0,
           thickness=None):
    settings = dict(zip(("length", "width", "height"), dimensions))
    settings.update(generator)
    settings.update({"Puff Size": puff, "Noise Strength": strength, "Noise Scale": scale, "Noise Detail": detail,
                     "Noise Roughness": roughness, "Noise Distortion": distortion, "Flat Base": flat_base,
                     "Density": density})
    if thickness is not None:
        settings["Stroke Thickness"] = thickness
    return settings


TYPES = (
    ('CUMULUS', "Cumulus", "Cumulus: a heaped fair-weather cloud with a flat base",
     _genus((8.0, 6.0, 5.0), dict(lumps=4, spread=0.65, height_variation=1.0), 0.02, 0.08, 15.0, 2.0, 0.5, 1.0, 0.1)),
    ('STRATOCUMULUS', "Stratocumulus", "Stratocumulus: a low layer of large rounded masses in loose rolls",
     _genus((16.0, 12.0, 2.5), dict(lumps=1, spread=0.3, distortion=0.2, height_variation=0.6), 0.016, 0.04, 20.0, 2.0, 0.5, 1.0, 0.15)),
    ('ALTOCUMULUS', "Altocumulus", "Altocumulus: a mid-level layer of small rounded cloudlets",
     _genus((14.0, 12.0, 1.5), dict(lumps=1, spread=0.5, height_variation=0.3), 0.012, 0.02, 30.0, 1.0, 0.5, 1.0, 0.0)),
    ('CIRROCUMULUS', "Cirrocumulus", "Cirrocumulus: a thin high sheet of tiny grains in ripples",
     _genus((14.0, 12.0, 0.6), dict(lumps=0, distortion=0.2), 0.006, 0.01, 60.0, 1.0, 0.5, 1.0, 0.0, 90.0)),
    ('STRATUS', "Stratus",
     "Stratus: a flat, featureless grey layer. Thicker (Height) and darker (Density, Dark Base) it is a "
     "Nimbostratus, thinner and higher an Altostratus",
     _genus((16.0, 12.0, 1.6), dict(lumps=1, spread=0.6), 0.02, 0.03, 8.0, 1.0, 0.5, 1.0, 0.0)),
    ('CIRRUS', "Cirrus", "Cirrus: thin high strokes and hooks of ice. Draw more strokes with the Draw tool",
     _genus((14.0, 8.0, 2.0), dict(lumps=0, distortion=0.2), 0.008, 0.015, 20.0, 1.0, 0.5, 3.0, 0.0, 150.0,
            thickness=0.25)),
)
DIMENSIONS = ("length", "width", "height")
GENERATOR = DIMENSIONS + ("height_variation",) + tuple(s[0] for s in shapes.SETTINGS)

# Where an object remembers the genus it was last given, for the panel.
TYPE_KEY = "cococlouds_type"


def cloud_type(identifier):
    for item in TYPES:
        if item[0] == identifier:
            return item
    raise KeyError(identifier)


# Genera that are gone, and the one that took their place.
RENAMED = {'ALTOSTRATUS': 'STRATUS', 'NIMBOSTRATUS': 'STRATUS'}  # 0.22.0


def type_of(ob):
    """The TYPES item an object was last given, or None."""
    identifier = ob.get(TYPE_KEY) if ob is not None else None
    identifier = RENAMED.get(identifier, identifier)
    return next((item for item in TYPES if item[0] == identifier), None)


def generator_settings(ob):
    """The generator's settings an object holds, as shapes.fill_mesh takes them."""
    return {name: getattr(ob.cococlouds, name) for name, *_ in shapes.SETTINGS}


def dimensions(ob):
    return tuple(getattr(ob.cococlouds, name) for name in DIMENSIONS)


def kind_of(identifier):
    """The object type a genus is drawn into."""
    return 'CURVE' if identifier in shapes.CURVES else 'MESH'


def reshape(ob):
    """Draw the object's heap again from its genus and generator settings.
    Never on a shape of the user's own, nor while it is being edited."""
    kind = type_of(ob)
    if kind is None or not ob.cococlouds.heap or ob.type != kind_of(kind[0]) or ob.mode != 'OBJECT':
        return
    fill = shapes.fill_curve if ob.type == 'CURVE' else shapes.fill_mesh
    fill(ob.data, kind[0], ob.cococlouds.shape_seed, dimensions(ob), generator_settings(ob),
         ob.cococlouds.height_variation)


def _new_data(identifier, name):
    if kind_of(identifier) == 'CURVE':
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        return curve
    return bpy.data.meshes.new(name)


def new_heap(identifier, name="Cloud"):
    """An object for the generator to draw a genus into, linked nowhere."""
    ob = bpy.data.objects.new(name, _new_data(identifier, name))
    ob.cococlouds.heap = True
    return ob


def _in_its_place(ob, identifier):
    """A heap given a genus of the other kind, strokes for spheres or
    spheres for strokes: an object's data cannot change type, so a new
    object takes its place, the same in all but its data, and the old one
    is removed. Returns the new one."""
    name, data = ob.name, ob.data
    new = bpy.data.objects.new(name + " new", _new_data(identifier, data.name))
    for collection in ob.users_collection:
        collection.objects.link(new)
    new.parent = ob.parent
    new.matrix_parent_inverse = ob.matrix_parent_inverse.copy()
    new.matrix_world = ob.matrix_world.copy()
    for key in (TYPE_KEY,):
        if key in ob:
            new[key] = ob[key]
    quietly(new, {name_: getattr(ob.cococlouds, name_) for name_ in ("heap", "shape_seed") + GENERATOR})
    old = cloud_modifier(ob)
    mod = new.modifiers.new(MODIFIER_NAME, 'NODES')
    mod.node_group = nodes.get_group()
    for input_, *_rest in nodes.INPUTS:
        if old is not None and has_input(old, input_):
            put(mod, input_, get(old, input_))
    mat = slot_material(ob) or look.material()
    _give_slot(new, mat)
    put(mod, "Material", mat)
    view_layer = bpy.context.view_layer
    selected, active = ob.select_get(), view_layer.objects.active == ob
    bpy.data.objects.remove(ob)
    if data.users == 0:
        (bpy.data.curves if isinstance(data, bpy.types.Curve) else bpy.data.meshes).remove(data)
    new.name = name
    new.data.name = name
    new.select_set(selected)
    if active:
        view_layer.objects.active = new
    return new


def set_type(ob, identifier):
    """Give a mesh object a genus: every Deform setting of the genus is
    written, whatever it was, and on a heap the generator's too, which draws
    it again. A shape of the user's own keeps its shape. A mesh or curve that is not a
    cloud becomes one. Returns the cloud's modifier, whose object is not
    the one given when a heap had to change kind (_in_its_place)."""
    settings = cloud_type(identifier)[3]
    if ob.cococlouds.heap and ob.type != kind_of(identifier):
        ob = _in_its_place(ob, identifier)
    ob[TYPE_KEY] = identifier
    if ob.cococlouds.heap:
        quietly(ob, {name: value for name, value in settings.items() if name in GENERATOR},
                {**shapes.defaults(), "height_variation": 0.0})
        reshape(ob)
    mod = cloud_modifier(ob)
    if mod is not None and not is_current(mod):
        update_cloud(mod)
    return make_cloud(ob, {name: value for name, value in settings.items() if name not in GENERATOR})


def remove_cloud(ob):
    mod = cloud_modifier(ob)
    if mod is not None:
        ob.modifiers.remove(mod)
        _take_slot(ob)
    if TYPE_KEY in ob:
        del ob[TYPE_KEY]


# ---------------------------------------------------------------- the generator's settings
#
# Kept on the object, as real properties so that the panel can show them as
# sliders; each draws the heap again. `heap` says the mesh is one the
# generator built: a mesh of the user's own is never written to, whatever
# ends up in these (a value dragged with Alt held goes to every selected
# object).
SEEDS = 99999
_quiet = False


def _reshape(self, context):
    if not _quiet:
        reshape(self.id_data)


def quietly(ob, values, base=None):
    """Write generator settings without drawing the heap at each one:
    `base` first, then `values` over it."""
    global _quiet
    _quiet = True
    try:
        for name, value in {**(base or {}), **values}.items():
            setattr(ob.cococlouds, name, value)
    finally:
        _quiet = False


def _setting(name, default, lo, hi, description):
    if isinstance(default, int):
        return IntProperty(name=name.replace("_", " ").title(), description=description, default=default,
                           min=lo, max=hi, update=_reshape)
    return FloatProperty(name=name.replace("_", " ").title(), description=description, default=default,
                         min=lo, soft_max=hi, update=_reshape)


def _dimension(name, description):
    return FloatProperty(name=name, description=description, default=8.0, min=0.001, soft_max=10000.0,
                         subtype='DISTANCE', update=_reshape)


# Made with type(): the generator's settings come from a table.
CocoCloudsObject = type("CocoCloudsObject", (PropertyGroup,), {"__annotations__": {
    "heap": BoolProperty(options={'HIDDEN'}),
    "shape_seed": IntProperty(
        name="Shape Seed",
        description="Another heap of spheres of the cloud's genus. It replaces the mesh: whatever was edited on it is gone",
        default=1, min=1, max=SEEDS, update=_reshape),
    "length": _dimension("Length", "Size of the cloud along X"),
    "width": _dimension("Width", "Size of the cloud along Y"),
    "height": _dimension("Height", "Size of the cloud along Z"),
    "height_variation": FloatProperty(
        name="Height ±",
        description=("How far the cloud's tops rise above Height or sink below it, from place to place over the "
                     "cloud, by its Shape Seed; at most half of Height. Its base stays flat"),
        default=0.0, min=0.0, soft_max=100.0, subtype='DISTANCE', update=_reshape),
    **{name: _setting(name, default, lo, hi, description) for name, default, lo, hi, description in shapes.SETTINGS},
}})


def heap_seed(ob):
    """The seed of the heap an object was added as, None for a mesh of the
    user's own."""
    return ob.cococlouds.shape_seed if ob.cococlouds.heap else None


def register():
    bpy.utils.register_class(CocoCloudsObject)
    bpy.types.Object.cococlouds = PointerProperty(type=CocoCloudsObject)
    bpy.app.handlers.depsgraph_update_post.append(_follow_slots)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_follow_slots)
    del bpy.types.Object.cococlouds
    bpy.utils.unregister_class(CocoCloudsObject)
