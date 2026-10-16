import random

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator
from mathutils import Vector

from . import cloud, look, previews, shapes

# What "Set Up Render" asks of each engine, as I set it (0.21.0). Cycles
# lights a volume once with the factory 0 volume bounces, and a cloud is
# white only because light bounces inside it many times: CYCLES_BOUNCES, the
# volume's and in all. Fast GI on, but only after as many bounces: after
# fewer it puts an estimate in place of the light, which in a cloud is grey
# smoke (a Cumulus in front of the sun at 32 bounces: 0.17 with 4 AO
# bounces, 0.43 without Fast GI, 0.43 with 32). The denoiser is
# OpenImageDenoise on the GPU. Samples and the noise threshold are left as
# they are. EEVEE has no such bounces; its settings are what makes it show
# the cloud's shape instead of a flat silhouette, and its Custom Range is
# switched off (eevee_is_cut).
CYCLES_BOUNCES = 32
CYCLES_SETTINGS = (
    ("use_denoising", True),
    ("denoiser", 'OPENIMAGEDENOISE'),
    ("denoising_use_gpu", True),
    ("use_fast_gi", True),
    ("ao_bounces", CYCLES_BOUNCES),
    ("ao_bounces_render", CYCLES_BOUNCES),
)
EEVEE_SETTINGS = (
    ("volumetric_tile_size", '2'),
    ("volumetric_samples", 128),
    ("use_volumetric_shadows", True),
    ("volumetric_shadow_samples", 32),
)


def _setup(scene, bounces=CYCLES_BOUNCES):
    """What clouds need of a scene to look right, in either engine: in
    Cycles at least `bounces` and CYCLES_SETTINGS. Returns the engines
    something was changed for."""
    changed = []
    cycles = getattr(scene, "cycles", None)
    if cycles is not None:
        for attr in ("volume_bounces", "max_bounces"):
            if getattr(cycles, attr) < bounces:
                setattr(cycles, attr, bounces)
                changed.append("Cycles")
        for attr, value in CYCLES_SETTINGS:
            if getattr(cycles, attr) != value:
                setattr(cycles, attr, value)
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


def fast_gi_greys(scene):
    """Fast GI on and starting before CYCLES_BOUNCES: clouds come out grey."""
    cycles = getattr(scene, "cycles", None)
    return cycles is not None and cycles.use_fast_gi and min(cycles.ao_bounces, cycles.ao_bounces_render) < CYCLES_BOUNCES


def cycles_is_dark(scene):
    """Too few bounces: Cycles will render clouds dark."""
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
    the panel would go on showing the genus and settings from before until
    the mouse moved over it."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class COCOCLOUDS_OT_add(Operator):
    bl_idname = "cococlouds.add"
    bl_label = "Add Cloud"
    bl_description = ("Add a new cloud of this genus at the 3D cursor: a heap of spheres from the generator, "
                      "another one every time, that stays editable as the cloud's rough shape")
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(name="Genus", items=previews.type_items)
    # Not remembered from one use to the next: left at 0, every cloud added
    # is another one. execute() writes the seed it drew back here, so that
    # the redo panel shows it.
    seed: IntProperty(name="Seed", description=("The cloud's heap of spheres and its noise, which then have "
                                                "a seed each in the panel. 0 draws a new one each time"),
                      default=0, min=0, max=SEEDS, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        if self.seed == 0:
            self.seed = random.randint(1, SEEDS)
        ob = cloud.new_heap(self.type)
        context.collection.objects.link(ob)
        ob.location = context.scene.cursor.location
        cloud.quietly(ob, {"shape_seed": self.seed})
        mod = cloud.set_type(ob, self.type)
        cloud.put(mod, "Seed", self.seed)
        for other in context.selected_objects:
            other.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {'FINISHED'}


class COCOCLOUDS_OT_set_type(Operator):
    bl_idname = "cococlouds.set_type"
    bl_label = "Cloud Genus"
    bl_description = ("Give the selected meshes and curves this genus: every Deform setting becomes the genus's, "
                      "and a cloud from the generator is drawn again as one. A mesh or curve of yours keeps its "
                      "shape")
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(name="Genus", items=previews.type_items)

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False
        if not any(o.type in cloud.KINDS for o in context.selected_objects):
            cls.poll_message_set("Select a mesh or a curve")
            return False
        return True

    def execute(self, context):
        for ob in context.selected_objects:
            if ob.type not in cloud.KINDS:
                continue
            new = not cloud.is_cloud(ob)
            mod = cloud.set_type(ob, self.type)
            if new:
                # Two alike meshes made into clouds together should not come
                # out alike.
                cloud.put(mod, "Seed", random.randint(1, SEEDS))
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_draw(Operator):
    bl_idname = "cococlouds.draw"
    bl_label = "Draw Strokes"
    bl_description = ("Draw more strokes on this cloud in Edit Mode, with the Draw tool: each one becomes a "
                      "streak of cloud. The strokes become yours, no longer redrawn by the Geometry settings")
    bl_options = {'REGISTER', 'UNDO'}

    clear: BoolProperty(name="Clear", description="Remove the strokes the cloud has first",
                        options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'CURVE' and cloud.is_cloud(ob) and context.area is not None \
            and context.area.type == 'VIEW_3D'

    def execute(self, context):
        ob = context.active_object
        ob.cococlouds.heap = False
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if self.clear:
            ob.data.splines.clear()
        for other in context.selected_objects:
            if other != ob:
                other.select_set(False)
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.draw")
        except RuntimeError:
            # Seen without a window, where tools have no keymaps.
            self.report({'WARNING'}, "Pick the Draw tool in the toolbar")
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_add_fray(Operator):
    bl_idname = "cococlouds.add_fray"
    bl_label = "Add Fray Box"
    bl_description = ("Add a box over one end of this cloud: inside it the wind pulls the cloud out along the "
                      "box's X axis. Move, rotate, scale or edit the box like any object; it is not rendered")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        mod = cloud.cloud_modifier(ob)
        return mod is not None and cloud.has_input(mod, "Fray Object")

    def execute(self, context):
        ob = context.active_object
        mesh = bpy.data.meshes.new("Fray")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(mesh)
        bm.free()
        box = bpy.data.objects.new("Fray", mesh)
        for collection in ob.users_collection:
            collection.objects.link(box)
        # Over the +X end of the cloud's shape (not of its volume, which
        # reaches well past it), a little past it every way.
        if ob.type == 'CURVE':
            places = [Vector(q.co[:3]) for spline in ob.data.splines for q in spline.points]
        else:
            places = [v.co for v in ob.data.vertices]
        corners = [ob.matrix_world @ q for q in places] or [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        low = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
        high = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
        span = high - low
        box.location = Vector((high.x - span.x * 0.2, (low.y + high.y) / 2, (low.z + high.z) / 2))
        box.scale = (span.x * 0.5, span.y * 1.2, span.z * 1.2)
        box.display_type = 'WIRE'
        box.hide_render = True
        cloud.put(cloud.cloud_modifier(ob), "Fray Object", box)
        for other in context.selected_objects:
            other.select_set(False)
        box.select_set(True)
        context.view_layer.objects.active = box
        _redraw(context)
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


class COCOCLOUDS_OT_update_material(Operator):
    bl_idname = "cococlouds.update_material"
    bl_label = "Update Material"
    bl_description = ("This material is as an earlier version of CocoClouds made it. Lay it out as this "
                      "version's nodes, keeping the values of the controls both have. Anything added to the "
                      "material is removed")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and cloud.is_cloud(ob) and look.is_old(cloud.slot_material(ob))

    def execute(self, context):
        look.rebuild(cloud.slot_material(context.active_object))
        _redraw(context)
        return {'FINISHED'}


class COCOCLOUDS_OT_update(Operator):
    bl_idname = "cococlouds.update"
    bl_label = "Update Cloud"
    bl_description = ("Move the selected clouds, made with an earlier version of CocoClouds, to this one. "
                      "They keep the settings both versions have; their look changes")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(cloud.is_cloud(o) for o in context.selected_objects)

    def execute(self, context):
        for ob in context.selected_objects:
            mod = cloud.cloud_modifier(ob)
            if mod is not None and not cloud.is_current(mod):
                cloud.update_cloud(mod)
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
    bl_description = ("Change this scene's render settings so clouds look right. Cycles: at least "
                      f"{CYCLES_BOUNCES} bounces, volume and total; Fast GI from bounce {CYCLES_BOUNCES} (from "
                      "fewer it turns clouds grey); OpenImageDenoise on the GPU. Samples are left alone. EEVEE: "
                      "finer volumes with shadows, and no Custom Range cutting them off far from the camera")
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
    COCOCLOUDS_OT_draw,
    COCOCLOUDS_OT_add_fray,
    COCOCLOUDS_OT_cloud_material,
    COCOCLOUDS_OT_update_material,
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
