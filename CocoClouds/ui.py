import bpy
from bpy.types import Panel

from . import look, previews
from .cloud import cloud_modifier, has_input, heap_seed, inp, is_current, slot_material, type_of
from .field import clouds_of, field_modifier, kinds, look_material
from .field import is_current as field_is_current
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


# Add Cloud's chooser: the size in icons of the picture it shows closed, and
# of each picture in the grid it opens.
TYPE_PICTURE = 2.5
TYPE_PICTURES = 5.0

# The material's controls as the Look panel lays them out, a gap between
# the groups.
CONTROLS = (("Color", "Brightness"), ("Dark Base", "Wispy Edges", "Anisotropy"), ("Glow", "Glow Color"))


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


def _field(context):
    """The modifier of the field the panel is about, as _cloud()."""
    ob = context.active_object
    if ob is None or not ob.select_get():
        return None
    return field_modifier(ob)


class COCOCLOUDS_PT_main(_Sidebar, Panel):
    bl_idname = "COCOCLOUDS_PT_main"
    bl_label = "CocoClouds"

    def draw(self, context):
        layout = self.layout
        mod = _cloud(context)

        # A line that says what a click on the picture under it does, and
        # the types' pictures to click (previews.py).
        if mod is not None:
            kind = type_of(context.active_object)
            said, chooser = (f"Type: {kind[1]}" if kind else "Cloud Type"), "cococlouds_type"
        elif any(o.type == 'MESH' and field_modifier(o) is None for o in context.selected_objects):
            said, chooser = "Cloud from Selection", "cococlouds_type"
        else:
            said, chooser = "Add Cloud", "cococlouds_add"
        layout.label(text=said, icon='VOLUME_DATA')
        layout.template_icon_view(context.window_manager, chooser, show_labels=True,
                                  scale=TYPE_PICTURE, scale_popup=TYPE_PICTURES)
        if chooser == "cococlouds_add":
            layout.operator("cococlouds.add_field", icon='OUTLINER_OB_POINTCLOUD')
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


class COCOCLOUDS_PT_shape(_CloudPanel, Panel):
    bl_label = "Shape"

    def draw(self, context):
        layout, mod = self.setup(context)
        _values(layout, mod, "Growth")
        _values(layout, mod, "Puffs", "Puff Scale")
        _values(layout, mod, "Billows", "Billow Scale")
        _values(layout, mod, "Erosion", "Erosion Scale")
        _values(layout, mod, "Softness", "Flat Base")
        col = _values(layout, mod, "Seed")
        # Only a heap CocoClouds made can be drawn again, and a mesh is not
        # written to while it is being edited.
        ob = context.active_object
        if heap_seed(ob) is not None:
            row = col.row(align=True)
            row.enabled = ob.mode == 'OBJECT'
            row.prop(ob.cococlouds, "shape_seed")


class COCOCLOUDS_PT_look(_CloudPanel, Panel):
    bl_label = "Look"

    def draw(self, context):
        layout, mod = self.setup(context)
        _values(layout, mod, "Density")
        # The material is the object's first slot, the same one the Material
        # tab and the Shader Editor show. A cloud from before that has none
        # yet and shows the modifier's own.
        ob = context.active_object
        if ob.material_slots:
            row = layout.row()
            row.use_property_split = False
            row.template_ID(ob.material_slots[0], "material")
        else:
            layout.prop(inp(mod, "Material"), "value", text="Material")
        # Its controls belong to the material: every cloud that has it
        # changes with them.
        mat = slot_material(ob) if ob.material_slots else inp(mod, "Material").value
        if not _controls(layout, mat):
            layout.operator("cococlouds.cloud_material", icon='MATERIAL')
        elif look.is_old(mat):
            layout.operator("cococlouds.split_material", icon='NODETREE')


class COCOCLOUDS_PT_quality(_CloudPanel, Panel):
    bl_label = "Quality"

    def draw(self, context):
        layout, mod = self.setup(context)
        col = layout.column(align=True)
        col.prop(inp(mod, "Viewport Resolution"), "value", text="Viewport")
        col.prop(inp(mod, "Resolution"), "value", text="Render")


class COCOCLOUDS_PT_field(_Sidebar, Panel):
    bl_parent_id = "COCOCLOUDS_PT_main"
    bl_label = "Field"

    @classmethod
    def poll(cls, context):
        return _field(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        mod = _field(context)
        ob = context.active_object
        if not field_is_current(mod):
            layout.operator("cococlouds.update", text="Update Field", icon='FILE_REFRESH')
        # How much of each kind, for a field that has kinds: one made before
        # 0.10.0 and not updated has none.
        labels = [label for _identifier, label in kinds()]
        if has_input(mod, labels[0]):
            _values(layout, mod, *labels)
            _values(layout, mod, "Sorting")
        _values(layout, mod, "Coverage", "Patch Size")
        _values(layout, mod, "Spacing")
        _values(layout, mod, "Smallest", "Largest")
        _values(layout, mod, "Seed", "Scatter Seed", "Patch Seed", "Mix Seed")
        if has_input(mod, "Paint"):
            col = layout.column(align=True)
            col.prop_search(inp(mod, "Paint"), "value", ob, "vertex_groups", text="Paint")
            if ob.mode == 'WEIGHT_PAINT':
                # What the brush paints: 0 takes clouds away, 1 brings them
                # back. The weight all brushes share, or the brush's own.
                paint = context.tool_settings.weight_paint
                shared = paint.unified_paint_settings
                if shared.use_unified_weight:
                    col.prop(shared, "weight", text="Brush Weight", slider=True)
                elif paint.brush is not None:
                    col.prop(paint.brush, "weight", text="Brush Weight", slider=True)
                col.operator("object.mode_set", text="Done Painting", icon='CHECKMARK').mode = 'OBJECT'
            else:
                col.operator("cococlouds.paint_field", icon='BRUSH_DATA')
        clouds = clouds_of(mod)
        if clouds is not None:
            # The clouds it repeats are ordinary clouds, out of sight until
            # they are to be edited.
            layout.prop(clouds, "hide_viewport", text="Hide Its Clouds")


class COCOCLOUDS_PT_field_clouds(_Sidebar, Panel):
    bl_parent_id = "COCOCLOUDS_PT_field"
    bl_label = "Collections"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _field(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        mod = _field(context)
        # The collection each kind is taken from. A field from before 0.10.0
        # and not updated has the one.
        col = layout.column(align=True)
        named = [label for _identifier, label in kinds() if has_input(mod, f"{label} Clouds")]
        for label in named:
            col.prop(inp(mod, f"{label} Clouds"), "value", text=label)
        if not named:
            col.prop(inp(mod, "Clouds"), "value", text="Clouds")


class COCOCLOUDS_PT_field_look(_Sidebar, Panel):
    bl_parent_id = "COCOCLOUDS_PT_main"
    bl_label = "Look"

    @classmethod
    def poll(cls, context):
        mod = _field(context)
        return mod is not None and bool(look.controls(look_material(mod)))

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        # The material the field's clouds have, which other clouds may have
        # too. To give it another, select one of its clouds.
        mat = look_material(_field(context))
        layout.label(text=mat.name, icon='MATERIAL')
        _controls(layout, mat)
        if look.is_old(mat):
            layout.operator("cococlouds.split_material", icon='NODETREE')


class COCOCLOUDS_PT_render(_Sidebar, Panel):
    bl_parent_id = "COCOCLOUDS_PT_main"
    bl_label = "Render"

    def draw(self, context):
        layout = self.layout
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
    self.layout.operator("cococlouds.add_field", text="Cloud Field", icon='OUTLINER_OB_POINTCLOUD')


_classes = (
    COCOCLOUDS_PT_main,
    COCOCLOUDS_PT_shape,
    COCOCLOUDS_PT_look,
    COCOCLOUDS_PT_quality,
    COCOCLOUDS_PT_field,
    COCOCLOUDS_PT_field_clouds,
    COCOCLOUDS_PT_field_look,
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
