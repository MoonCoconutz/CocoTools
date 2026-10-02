"""What a cutter is, and the properties that edit it.

A cutter is a curve object carrying the Sheet modifier. Each object it cuts
carries a Cut modifier whose Cutter input points back at it, so the targets
of a cutter are found from the modifiers, never stored: deleting a target or
a modifier by hand cannot leave a stale list behind.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup

from . import nodes

MODIFIER_NAME = "CocoCutter"


def inp(mod, name):
    """The modifier's input struct for a group socket; its `value` is the
    setting. On 5.2 a Geometry Nodes modifier keeps its inputs under
    `properties.inputs.<identifier>`, not as ID properties."""
    return getattr(mod.properties.inputs, nodes.socket_id(mod.node_group, name))


def get(mod, name):
    return inp(mod, name).value


def put(mod, name, value):
    inp(mod, name).value = value


def sheet_modifier(ob):
    if ob is None or ob.type != 'CURVE':
        return None
    for mod in ob.modifiers:
        if mod.type == 'NODES' and nodes.is_group(mod.node_group, nodes.SHEET_NAME):
            return mod
    return None


def cut_modifiers(ob):
    if ob is None or ob.type != 'MESH':
        return []
    return [m for m in ob.modifiers
            if m.type == 'NODES' and nodes.is_group(m.node_group, nodes.CUT_NAME)]


def is_cutter(ob):
    return sheet_modifier(ob) is not None


def cutter_of(ob):
    """The cutter to show for the active object: itself, or the cutter of
    its last Cut modifier that still has one."""
    if is_cutter(ob):
        return ob
    for mod in reversed(cut_modifiers(ob)):
        cutter = get(mod, "Cutter")
        if is_cutter(cutter):
            return cutter
    return None


def targets_of(cutter, scene):
    """Every (object, Cut modifier) pair in the scene cut by this cutter."""
    pairs = []
    for ob in scene.objects:
        for mod in cut_modifiers(ob):
            if get(mod, "Cutter") == cutter:
                pairs.append((ob, mod))
    return pairs


# Keep and Solver are plain ints on the Sheet modifier (a menu socket cannot
# be drawn from Python); these enums put names on them.

_KEEP_ITEMS = (
    ('BOTH', "Both", "Keep both sides, as two separate objects", nodes.KEEP_BOTH),
    ('A', "A", "Keep only side A", nodes.KEEP_A),
    ('B', "B", "Keep only side B", nodes.KEEP_B),
)
_SOLVER_ITEMS = (
    ('EXACT', "Exact", "Slowest, and works on any mesh", 0),
    ('MANIFOLD', "Manifold", "Fast, but only for closed meshes without holes", 1),
    ('FLOAT', "Float", "Fastest and least accurate", 2),
)


def _int_enum(name):
    def getter(self):
        mod = sheet_modifier(self.id_data)
        return get(mod, name) if mod else 0

    def setter(self, value):
        mod = sheet_modifier(self.id_data)
        if mod:
            put(mod, name, value)
            self.id_data.update_tag()

    return getter, setter


def _material_updated(self, context):
    cutter = self.id_data
    for ob, mod in targets_of(cutter, context.scene):
        put(mod, "Material", self.material)
        ob.update_tag()
    if self.material is not None:
        context.scene.coco_cutter.material = self.material


class COCOCUTTER_PG_cutter(PropertyGroup):
    """On every object; meaningful only on a cutter."""

    keep: EnumProperty(name="Keep", items=_KEEP_ITEMS, get=_int_enum("Keep")[0],
                       set=_int_enum("Keep")[1])
    solver: EnumProperty(name="Solver", items=_SOLVER_ITEMS, get=_int_enum("Solver")[0],
                         set=_int_enum("Solver")[1])
    material: PointerProperty(name="Cut Material", type=bpy.types.Material,
                              description="Material of the faces the cut creates",
                              update=_material_updated)


class COCOCUTTER_PG_scene(PropertyGroup):
    delete_cutter: BoolProperty(name="Delete Cutter after Cut", default=True,
                                description="Remove the cutter once its cut is applied")
    material: PointerProperty(type=bpy.types.Material,
                              description="Cut material given to the next cutter")

    # The last cutter's settings that do not depend on the size of what it
    # cut, given to the next cutter (see remember / recall). The rest
    # (Strength, Scale, Length, Gap, Image Strength and Size) are worked out
    # from each new cutter's targets, and Cyclic from its stroke.
    remembered: BoolProperty(default=False)
    resolution: IntProperty()
    detail: FloatProperty()
    roughness: FloatProperty()
    distortion: FloatProperty()
    seed: IntProperty()
    keep: IntProperty()
    solver: IntProperty()
    image: PointerProperty(type=bpy.types.Image)
    image_rotation: FloatProperty()
    fill: BoolProperty(default=True)
    vertex_group: BoolProperty(default=False)


# Sheet input name -> attribute on COCOCUTTER_PG_scene.
_CARRIED = {
    "Resolution": "resolution", "Detail": "detail", "Roughness": "roughness",
    "Distortion": "distortion", "Seed": "seed", "Keep": "keep", "Solver": "solver",
    "Image": "image", "Image Rotation": "image_rotation", "Fill Cut": "fill",
    "Vertex Group": "vertex_group",
}


def has_input(mod, name):
    """False for an input added after the group version this cutter uses."""
    return nodes.socket_id(mod.node_group, name) is not None


def remember(scene, cutter):
    """Keep this cutter's size-independent settings for the next one."""
    mod = sheet_modifier(cutter)
    if mod is None:
        return
    memory = scene.coco_cutter
    for name, attr in _CARRIED.items():
        if has_input(mod, name):
            setattr(memory, attr, get(mod, name))
    memory.remembered = True


def recall(scene, mod):
    """Give a new cutter's Sheet modifier the remembered settings."""
    memory = scene.coco_cutter
    if not memory.remembered:
        return
    for name, attr in _CARRIED.items():
        put(mod, name, getattr(memory, attr))


_classes = (COCOCUTTER_PG_cutter, COCOCUTTER_PG_scene)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.coco_cutter = PointerProperty(type=COCOCUTTER_PG_cutter)
    bpy.types.Scene.coco_cutter = PointerProperty(type=COCOCUTTER_PG_scene)


def unregister():
    del bpy.types.Scene.coco_cutter
    del bpy.types.Object.coco_cutter
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
