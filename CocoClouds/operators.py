import random

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator

from . import cloud, field, look, shapes
from . import previews

# What "Set Up Render" asks of each engine. Cycles lights a volume once with
# the factory 0 volume bounces, and a cloud is white only because light
# bounces inside it many times. EEVEE has no such bounces; these settings are
# what makes it show the cloud's shape instead of a flat silhouette. Its
# Custom Range is switched off as well (see eevee_is_cut).
CYCLES_BOUNCES = 12
EEVEE_SETTINGS = (
    ("volumetric_tile_size", '2'),
    ("volumetric_samples", 128),
    ("use_volumetric_shadows", True),
    ("volumetric_shadow_samples", 32),
)


def _setup(scene, bounces=CYCLES_BOUNCES):
    """What clouds need of a scene to look right at all, in either engine,
    with at least `bounces` in Cycles. Returns the engines something was
    changed for."""
    changed = []
    cycles = getattr(scene, "cycles", None)
    if cycles is not None:
        for attr in ("volume_bounces", "max_bounces"):
            if getattr(cycles, attr) < bounces:
                setattr(cycles, attr, bounces)
                changed.append("Cycles")
    eevee = scene.eevee
    if int(eevee.volumetric_tile_size) > int(EEVEE_SETTINGS[0][1]):
        eevee.volumetric_tile_size = EEVEE_SETTINGS[0][1]
        changed.append("EEVEE")
    for attr, value in EEVEE_SETTINGS[1:]:
        if getattr(eevee, attr) < value:
            setattr(eevee, attr, value)
            changed.append("EEVEE")
    if eevee.use_volume_custom_range:
        eevee.use_volume_custom_range = False
        changed.append("EEVEE")
    return list(dict.fromkeys(changed))


def cycles_is_dark(scene):
    cycles = getattr(scene, "cycles", None)
    return cycles is not None and min(cycles.volume_bounces, cycles.max_bounces) < CYCLES_BOUNCES


def eevee_is_flat(scene):
    eevee = scene.eevee
    return (not eevee.use_volumetric_shadows
            or int(eevee.volumetric_tile_size) > int(EEVEE_SETTINGS[0][1]))


def eevee_is_cut(scene):
    """EEVEE's Volumes > Custom Range is on: no volume is drawn farther from
    the camera than its End, so a cloud beyond it is simply not there."""
    return scene.eevee.use_volume_custom_range


SEEDS = cloud.SEEDS


def _redraw(context):
    """Have every 3D viewport draw again, sidebar included. An object's
    custom property and a modifier's input changing do not ask for it, and
    the panel would go on showing the type and settings from before until
    the mouse moved over it."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class COCOCLOUDS_OT_add(Operator):
    bl_idname = "cococlouds.add"
    bl_label = "Add Cloud"
    bl_description = ("Add a new cloud of this type at the 3D cursor: a heap of spheres, another "
                      "one every time, that stays editable as the cloud's rough shape")
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(name="Type", items=previews.type_items)
    size: FloatProperty(name="Size", description="Width of the cloud", default=6.0,
                        min=0.01, soft_max=1000.0, subtype='DISTANCE')
    # Not remembered from one use to the next: left at 0, every cloud added
    # is another one. execute() writes the seed it drew back here, so that
    # the redo panel shows it and changing Size there keeps the same cloud.
    seed: IntProperty(name="Seed", description=("The cloud's heap of spheres and its noise, which then have "
                                                "a seed each in the panel. 0 draws a new one each time"),
                      default=0, min=0, max=SEEDS, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        if self.seed == 0:
            self.seed = random.randint(1, SEEDS)
        ob = bpy.data.objects.new("Cloud", shapes.blockout_mesh(self.type, self.seed, self.size))
        context.collection.objects.link(ob)
        ob.location = context.scene.cursor.location
        cloud.put(cloud.set_type(ob, self.type, cloud.HEAP_PUFFS), "Seed", self.seed)
        cloud.set_heap_seed(ob, self.seed)
        for other in context.selected_objects:
            other.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {'FINISHED'}


class COCOCLOUDS_OT_set_type(Operator):
    bl_idname = "cococlouds.set_type"
    bl_label = "Cloud Type"
    bl_description = ("Give the selected meshes this type: every Shape setting but Puffs and Seed "
                      "becomes the type's, and a cloud still on the heap of spheres it was added as gets "
                      "the type's heap. A mesh of yours, or a heap you edited, keeps its shape")
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(name="Type", items=previews.type_items)

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False
        if not any(o.type == 'MESH' and not field.is_field(o) for o in context.selected_objects):
            cls.poll_message_set("Select a mesh")
            return False
        return True

    def execute(self, context):
        for ob in context.selected_objects:
            # A field's plane is not a shape to make a cloud of.
            if ob.type != 'MESH' or field.is_field(ob):
                continue
            new = not cloud.is_cloud(ob)
            mod = cloud.set_type(ob, self.type)
            if new:
                # Two alike meshes made into clouds together should not come
                # out alike.
                cloud.put(mod, "Seed", random.randint(1, SEEDS))
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_add_field(Operator):
    bl_idname = "cococlouds.add_field"
    bl_label = "Add Cloud Field"
    bl_description = ("Fill a sky for the price of a few clouds: a plane above the 3D cursor that repeats "
                      "a handful of clouds over its surface, each turned and scaled. A few of every kind "
                      "that comes many at a time: Cumulus, Puff, Sheet, Flock and Shreds")
    bl_options = {'REGISTER', 'UNDO'}

    area: FloatProperty(name="Area", description="Width of the plane the clouds are scattered over",
                        default=8000.0, min=1.0, soft_max=100000.0, subtype='DISTANCE')
    height: FloatProperty(name="Height", description="How far above the 3D cursor the plane, the clouds' base, is",
                          default=1000.0, soft_min=0.0, soft_max=20000.0, subtype='DISTANCE')
    size: FloatProperty(name="Cloud Size", description=("Width of a Cumulus. The other kinds are made to "
                                                         "go with it: a Puff smaller, a Sheet twice as wide"),
                        default=400.0, min=0.01, soft_max=10000.0, subtype='DISTANCE')
    spacing: FloatProperty(name="Spacing", description="Least distance between two clouds", default=700.0,
                           min=0.01, soft_max=100000.0, subtype='DISTANCE')
    count: IntProperty(name="Clouds of Each Kind", description="How many clouds of each kind are made, to be repeated",
                       default=3, min=1, soft_max=8)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        cursor = context.scene.cursor.location
        ob = field.make_field(context, self.area, self.size, self.spacing, self.count,
                              (cursor.x, cursor.y, cursor.z + self.height))
        for other in context.selected_objects:
            other.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {'FINISHED'}


class COCOCLOUDS_OT_paint_field(Operator):
    bl_idname = "cococlouds.paint_field"
    bl_label = "Paint Clouds"
    bl_description = ("Paint on the plane where the field's clouds may stand: weight 0 takes them away, 1 "
                      "leaves them to Coverage. The plane gets the vertices and the vertex group this takes, "
                      "and the brush weight 0 to begin with")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return context.mode == 'OBJECT' and ob is not None and ob.select_get() and field.is_field(ob)

    def execute(self, context):
        field.prepare_paint(context.active_object)
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        # The group starts full, and a brush of weight 1 would paint nothing
        # into it. The weight is the one all brushes share unless the user
        # gave each its own.
        paint = context.tool_settings.weight_paint
        shared = paint.unified_paint_settings
        if shared.use_unified_weight:
            shared.weight = 0.0
        elif paint.brush is not None:
            paint.brush.weight = 0.0
        return {'FINISHED'}


class COCOCLOUDS_OT_cloud_material(Operator):
    bl_idname = "cococlouds.cloud_material"
    bl_label = "Use Cloud Material"
    bl_description = ("Give the selected clouds the CocoClouds material, the one with the controls. "
                      "The material they have stays in the file")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(cloud.is_cloud(o) for o in context.selected_objects)

    def execute(self, context):
        for ob in context.selected_objects:
            if cloud.is_cloud(ob):
                cloud.set_material(ob, look.material())
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_split_material(Operator):
    bl_idname = "cococlouds.split_material"
    bl_label = "Update Material"
    bl_description = ("This material is as an earlier version of CocoClouds made it. Lay it out as this "
                      "version's nodes, with the values it has: in Cycles it renders the same, in EEVEE it "
                      "gets the preview that looks like Cycles. Anything added to the material is removed")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return cls._material(context) is not None

    @staticmethod
    def _material(context):
        """The material the panel is showing: the active cloud's, or the
        active field's clouds'."""
        ob = context.active_object
        if ob is None:
            return None
        mat = cloud.slot_material(ob) if cloud.is_cloud(ob) else None
        mod = field.field_modifier(ob)
        if mod is not None:
            mat = field.look_material(mod)
        return mat if look.is_old(mat) else None

    def execute(self, context):
        look.split(self._material(context))
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_update(Operator):
    bl_idname = "cococlouds.update"
    bl_label = "Update Cloud"
    bl_description = ("Move the selected clouds and fields, made with an earlier version of CocoClouds, to "
                      "this one, a field with the clouds it repeats. They keep their settings and gain the new "
                      "ones; a cloud's look can change")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(cloud.is_cloud(o) or field.is_field(o) for o in context.selected_objects)

    def execute(self, context):
        for ob in context.selected_objects:
            mod = cloud.cloud_modifier(ob)
            if mod is not None and not cloud.is_current(mod):
                cloud.update_cloud(mod)
            mod = field.field_modifier(ob)
            if mod is not None and not field.is_current(mod):
                field.update_field(mod)
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_remove(Operator):
    bl_idname = "cococlouds.remove"
    bl_label = "Back to Mesh"
    bl_description = "Remove the cloud from the selected objects, leaving their meshes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(cloud.is_cloud(o) for o in context.selected_objects)

    def execute(self, context):
        for ob in context.selected_objects:
            cloud.remove_cloud(ob)
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_setup_render(Operator):
    bl_idname = "cococlouds.setup_render"
    bl_label = "Set Up Render"
    bl_description = ("Change this scene's render settings so clouds look right: Cycles gets "
                      f"{CYCLES_BOUNCES} volume bounces; EEVEE finer volumes with shadows, and no Custom "
                      "Range cutting them off far from the camera. Settings that are already "
                      "higher are left alone")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        changed = _setup(context.scene)
        if changed:
            self.report({'INFO'}, "Changed: " + ", ".join(changed))
        else:
            self.report({'INFO'}, "Nothing to change")
        return {'FINISHED'}


_classes = (
    COCOCLOUDS_OT_add,
    COCOCLOUDS_OT_set_type,
    COCOCLOUDS_OT_add_field,
    COCOCLOUDS_OT_paint_field,
    COCOCLOUDS_OT_cloud_material,
    COCOCLOUDS_OT_split_material,
    COCOCLOUDS_OT_update,
    COCOCLOUDS_OT_remove,
    COCOCLOUDS_OT_setup_render,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
