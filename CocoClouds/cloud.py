"""What a cloud is, and how one is made.

A cloud is a mesh object carrying the Cloud modifier. The mesh is the rough
shape, an ordinary mesh that stays editable. It can be as plain as a box or
a few of them: the modifier's Puffs setting rounds it and breaks it into
lumps. A cloud added from nothing starts as a heap of overlapping spheres,
another heap every time (shapes.py), and remembers the seed of it: Shape
Seed draws the heap again. Overlapping closed pieces need no boolean: the
density grid takes their union (measured on 5.2).
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, IntProperty, PointerProperty
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
    """False for an input added after the group version this cloud uses."""
    return nodes.socket_id(mod.node_group, name) is not None


def cloud_modifier(ob):
    if ob is None or ob.type != 'MESH':
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
# silhouette whichever way the slot was linked, EEVEE only read an
# object-linked one, and neither a copy made by another object's nodes). The
# group has to set it on the volume, and no node reads a slot. So the group
# keeps its Material input, and a handler copies the slot into it whenever
# the two differ (_follow_slots).
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


def sync_material(ob):
    """Copy the first slot's material into the cloud's modifier when they
    differ. An empty slot, or none, changes nothing: the cloud keeps the
    material it has."""
    mod = cloud_modifier(ob)
    if mod is None:
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
    return mod


def is_current(mod):
    """False for a cloud, or a field, still on a group of an earlier
    version."""
    return nodes.is_current(mod.node_group)


def update_cloud(mod):
    """Move a cloud to the current group, keeping the settings both have.
    Sockets are matched by name: their identifiers differ between versions."""
    old = mod.node_group
    kept = {name: get(mod, name) for name, *_ in nodes.INPUTS if nodes.socket_id(old, name)}
    mod.node_group = nodes.get_group()
    for name, value in kept.items():
        put(mod, name, value)
    # A cloud from before the material moved to the slot: its material goes
    # there now.
    ob = mod.id_data
    if SLOT_KEY not in ob:
        _give_slot(ob, kept.get("Material") or look.material())
    # The material from before it had controls, if nothing was changed in
    # it, gives way to the one that has them. One the user changed stays.
    if ob.material_slots and look.is_plain(slot_material(ob)):
        ob.material_slots[0].material = look.material()
    put(mod, "Material", slot_material(ob))


# Types: (identifier, label, description, settings). A type is a set of the
# Shape settings, all but Puffs and Seed, so giving it to a cloud leaves
# nothing of the type the cloud had; it can be given to any mesh. The rough
# shape a new cloud of each type starts from is in shapes.py, under the same
# identifier.
#
# Puffs is not a type's to set: it says how far to leave the mesh, and that
# depends on the mesh. A heap of spheres is a cloud's shape already; a box
# is not.
#
# The scales count across the cloud's longest side, so a type made of many
# small pieces needs them high.

def _settings(puff_scale, billows, billow_scale, erosion, erosion_scale, softness, flat_base):
    return {"Puff Scale": puff_scale, "Billows": billows, "Billow Scale": billow_scale,
            "Erosion": erosion, "Erosion Scale": erosion_scale,
            "Softness": softness, "Flat Base": flat_base}


TYPES = (
    ('CUMULUS', "Cumulus", "Cumulus: a heaped fair-weather cloud with a flat base",
     _settings(3.0, 0.3, 2.0, 0.19, 7.0, 0.05, 0.15)),
    ('PUFF', "Puff", "Cumulus humilis: a small, low, soft cloud, wider than tall",
     _settings(2.0, 0.4, 1.5, 0.19, 5.0, 0.14, 0.2)),
    ('TOWER', "Tower", "Cumulus congestus: a tall, crisp cloud growing upwards",
     _settings(4.5, 0.2, 2.5, 0.16, 9.0, 0.03, 0.1)),
    ('ANVIL', "Anvil", "Cumulonimbus: a thunderstorm tower spreading into a flat anvil at the top",
     _settings(4.5, 0.2, 2.5, 0.14, 9.0, 0.06, 0.06)),
    ('SHEET', "Sheet", "Stratocumulus: a low patch of rounded masses grown into one another",
     _settings(5.0, 0.2, 4.0, 0.16, 12.0, 0.08, 0.25)),
    ('FLOCK', "Flock", "Altocumulus: a field of small separate cloudlets",
     _settings(8.0, 0.15, 6.0, 0.12, 30.0, 0.2, 0.2)),
    ('LENS', "Lens", "Lenticular: a smooth lens, or a stack of them, as over mountains",
     _settings(3.0, 0.1, 1.5, 0.04, 6.0, 0.25, 0.0)),
    ('SHREDS', "Shreds", "Fractus: small ragged pieces torn by the wind",
     _settings(4.0, 0.8, 3.0, 0.5, 6.0, 0.5, 0.0)),
    ('LAYER', "Layer", "Stratus: a flat, soft, featureless sheet",
     _settings(4.0, 0.35, 3.0, 0.15, 8.0, 0.35, 0.0)),
)

# Puffs for a new cloud's own heap, and for a mesh made into a cloud.
HEAP_PUFFS = 0.0
MESH_PUFFS = 0.6

# Where an object remembers the type it was last given, for the panel.
TYPE_KEY = "cococlouds_type"


def cloud_type(identifier):
    for item in TYPES:
        if item[0] == identifier:
            return item
    raise KeyError(identifier)


def type_of(ob):
    """The TYPES item an object was last given, or None."""
    identifier = ob.get(TYPE_KEY)
    return next((item for item in TYPES if item[0] == identifier), None)


def set_type(ob, identifier, puffs=MESH_PUFFS):
    """Give a mesh object a type: every setting the type owns is written,
    whatever it was. A mesh that is not a cloud becomes one, with `puffs`;
    a cloud keeps the Puffs it has.

    A cloud still on the heap of spheres it was added as gets the new
    type's heap as well, of the same seed and as wide: the settings of two
    types are close, and on the same heap a Cumulus made a Tower looked the
    same cloud. A heap edited by hand is a shape of the user's own by then
    and stays."""
    before = type_of(ob)
    if (before is not None and before[0] != identifier and ob.cococlouds.heap and ob.mode == 'OBJECT'
            and shapes.is_heap(ob.data, before[0], ob.cococlouds.shape_seed)):
        shapes.fill_mesh(ob.data, identifier, ob.cococlouds.shape_seed, shapes.width(ob.data))
    mod = cloud_modifier(ob)
    settings = dict(cloud_type(identifier)[3])
    if mod is None:
        settings["Puffs"] = puffs
    elif not is_current(mod):
        update_cloud(mod)
    mod = make_cloud(ob, settings)
    ob[TYPE_KEY] = identifier
    return mod


def remove_cloud(ob):
    mod = cloud_modifier(ob)
    if mod is not None:
        ob.modifiers.remove(mod)
        _take_slot(ob)
    if TYPE_KEY in ob:
        del ob[TYPE_KEY]


# The heap of spheres a cloud was added as can be drawn again. Its seed is
# kept on the object, as a real property so that the panel can show it as a
# slider, next to whether the mesh is such a heap at all: a mesh of the
# user's own is never written to, whatever ends up in its seed (a value
# dragged with Alt held goes to every selected object).
SEEDS = 99999
_quiet = False


def _reshape(self, context):
    """Shape Seed changed: build the heap again, as the type the cloud has
    now, in the mesh the object already has and as wide as that is."""
    ob = self.id_data
    kind = type_of(ob)
    if _quiet or not self.heap or kind is None or ob.type != 'MESH' or ob.mode != 'OBJECT':
        return
    shapes.fill_mesh(ob.data, kind[0], self.shape_seed, shapes.width(ob.data) or 1.0)


class CocoCloudsObject(PropertyGroup):
    heap: BoolProperty(options={'HIDDEN'})
    shape_seed: IntProperty(
        name="Shape Seed",
        description=("Another heap of spheres of the cloud's type, as wide as this one. "
                     "It replaces the mesh: whatever was edited on it is gone"),
        default=1, min=1, max=SEEDS, update=_reshape)


def heap_seed(ob):
    """The seed of the heap an object was added as, None for a mesh of the
    user's own."""
    return ob.cococlouds.shape_seed if ob.cococlouds.heap else None


def set_heap_seed(ob, seed):
    """Record that an object's mesh is the heap of a seed, already built."""
    global _quiet
    _quiet = True
    try:
        ob.cococlouds.heap = True
        ob.cococlouds.shape_seed = seed
    finally:
        _quiet = False


def register():
    bpy.utils.register_class(CocoCloudsObject)
    bpy.types.Object.cococlouds = PointerProperty(type=CocoCloudsObject)
    bpy.app.handlers.depsgraph_update_post.append(_follow_slots)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_follow_slots)
    del bpy.types.Object.cococlouds
    bpy.utils.unregister_class(CocoCloudsObject)
