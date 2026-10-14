import bpy
from bpy.types import Panel

from . import look, shapes
from .cloud import cloud_modifier, has_input, heap_seed, inp, is_current, slot_material, type_of
from .operators import cycles_is_dark, eevee_is_cut, eevee_is_flat


class _Sidebar:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "CocoClouds"


def _values(layout, mod, *names):
    col = layout.column(align=True)
    for name in names:
        # A cloud made by an earlier version lacks the inputs added since.
        if has_input(mod, name):
            col.prop(inp(mod, name), "value", text=name)
    return col


# The chooser at the top: the size in icons of the picture it shows closed,
# and of each picture in the grid it opens.
TYPE_PICTURE = 2.5
TYPE_PICTURES = 5.0

# The material's controls as the Material panel lays them out, a gap between
# the groups.
CONTROLS = (("Color", "Dark Base"), ("Glow", "Glow Color"), ("Anisotropy",))


def _controls(layout, mat):
    """The sliders of a material's controls, those it has: they are sockets
    of its nodes (look.py). False for a material without any."""
    found = look.controls(mat)
    if not found:
        return False
    for names in CONTROLS:
        if any(name in found for name in names):
            col = layout.column(align=True)
            for name in names:
                if name in found:
                    col.prop(found[name], "default_value", text=name)
    return True


def _cloud(context):
    """The modifier of the cloud the panel is about: the active object, as
    long as it is selected. Clicking empty space leaves an object active, and
    the panel must then be back to adding a cloud, not still on that one."""
    ob = context.active_object
    if ob is None or not ob.select_get():
        return None
    return cloud_modifier(ob)


class COCOCLOUDS_PT_main(_Sidebar, Panel):
    bl_idname = "COCOCLOUDS_PT_main"
    bl_label = "CocoClouds"

    def draw(self, context):
        layout = self.layout
        mod = _cloud(context)

        # A line that says what a click on the picture under it does, and
        # the genera's pictures to click (previews.py).
        if mod is not None:
            kind = type_of(context.active_object)
            said, chooser = (f"Genus: {kind[1]}" if kind else "Cloud Genus"), "cococlouds_type"
        elif any(o.type == 'MESH' for o in context.selected_objects):
            said, chooser = "Cloud from Selection", "cococlouds_type"
        else:
            said, chooser = "Add Cloud", "cococlouds_add"
        layout.label(text=said, icon='VOLUME_DATA')
        layout.template_icon_view(context.window_manager, chooser, show_labels=True,
                                  scale=TYPE_PICTURE, scale_popup=TYPE_PICTURES)
        if mod is not None:
            col = layout.column(align=True)
            if not is_current(mod):
                col.operator("cococlouds.update", icon='FILE_REFRESH')
            col.operator("cococlouds.remove", icon='X')


class _CloudPanel(_Sidebar):
    bl_parent_id = "COCOCLOUDS_PT_main"

    @classmethod
    def poll(cls, context):
        return _cloud(context) is not None

    def setup(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        return layout, _cloud(context)


class COCOCLOUDS_PT_geometry(_CloudPanel, Panel):
    bl_label = "Geometry"

    def draw(self, context):
        layout, _mod = self.setup(context)
        ob = context.active_object
        if heap_seed(ob) is None:
            # A mesh of the user's own: its shape is theirs to edit.
            layout.label(text="Shaped by your mesh: edit it in Edit Mode", icon='MESH_DATA')
            return
        # The generator's settings draw the heap again, which is not done
        # while the mesh is being edited.
        layout.enabled = ob.mode == 'OBJECT'
        own = ob.cococlouds
        col = layout.column(align=True)
        for name in ("length", "width", "height"):
            col.prop(own, name)
        layout.prop(own, "shape_seed")
        col = layout.column(align=True)
        for name, *_rest in shapes.SETTINGS:
            col.prop(own, name)


class COCOCLOUDS_PT_deform(_CloudPanel, Panel):
    bl_label = "Deform"

    def draw(self, context):
        layout, mod = self.setup(context)
        _values(layout, mod, "Puff Size")
        _values(layout, mod, "Noise Strength", "Noise Scale", "Noise Detail", "Noise Roughness", "Noise Distortion")
        _values(layout, mod, "Seed")
        _values(layout, mod, "Flat Base", "Growth")


class COCOCLOUDS_PT_material(_CloudPanel, Panel):
    bl_label = "Material"

    def draw(self, context):
        layout, mod = self.setup(context)
        _values(layout, mod, "Density")
        # The material is the object's first slot, the same one the Material
        # tab and the Shader Editor show.
        ob = context.active_object
        if ob.material_slots:
            row = layout.row()
            row.use_property_split = False
            row.template_ID(ob.material_slots[0], "material")
        # Its controls belong to the material: every cloud that has it
        # changes with them.
        mat = slot_material(ob)
        if look.is_old(mat):
            layout.operator("cococlouds.update_material", icon='NODETREE')
        elif not _controls(layout, mat):
            layout.operator("cococlouds.cloud_material", icon='MATERIAL')


class COCOCLOUDS_PT_render(_Sidebar, Panel):
    bl_parent_id = "COCOCLOUDS_PT_main"
    bl_label = "Render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        mod = _cloud(context)
        if mod is not None:
            col = layout.column(align=True)
            col.prop(inp(mod, "Viewport Resolution"), "value", text="Viewport")
            col.prop(inp(mod, "Resolution"), "value", text="Render")
        scene = context.scene
        col = layout.column(align=True)
        if cycles_is_dark(scene):
            col.label(text="Cycles: clouds will render dark", icon='ERROR')
        if eevee_is_flat(scene):
            col.label(text="EEVEE: clouds will look flat", icon='ERROR')
        if eevee_is_cut(scene):
            col.label(text=f"EEVEE: no clouds past {scene.eevee.volumetric_end:.0f} m", icon='ERROR')
        layout.operator("cococlouds.setup_render", icon='SCENE')


def _add_menu(self, context):
    self.layout.operator_menu_enum("cococlouds.add", "type", text="Cloud", icon='VOLUME_DATA')


_classes = (
    COCOCLOUDS_PT_main,
    COCOCLOUDS_PT_geometry,
    COCOCLOUDS_PT_deform,
    COCOCLOUDS_PT_material,
    COCOCLOUDS_PT_render,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_volume_add.append(_add_menu)


def unregister():
    bpy.types.VIEW3D_MT_volume_add.remove(_add_menu)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
