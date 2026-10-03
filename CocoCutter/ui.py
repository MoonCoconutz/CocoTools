import bpy
from bpy.types import Panel

from .cutter import cut_modifiers, cutter_of, get, has_input, inp, sheet_modifier, targets_of


class _Sidebar:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "CocoCutter"


def _values(layout, mod, *names):
    col = layout.column(align=True)
    for name in names:
        col.prop(inp(mod, name), "value", text=name)
    return col


class COCOCUTTER_PT_main(_Sidebar, Panel):
    bl_idname = "COCOCUTTER_PT_main"
    bl_label = "CocoCutter"

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        cutter = cutter_of(ob)

        row = layout.row()
        row.scale_y = 1.0 if cutter else 1.6
        row.operator("cococutter.draw", icon='GREASEPENCIL')
        if cutter is None:
            if cut_modifiers(ob):
                layout.operator("cococutter.cancel", text="Remove Leftover Cut", icon='X')
            elif not any(o.type == 'MESH' for o in context.selected_objects):
                layout.label(text="Select the objects to cut", icon='INFO')
            return

        row = layout.row(align=True)
        row.scale_y = 1.6
        row.operator("cococutter.cut", icon='MOD_BOOLEAN')
        row.operator("cococutter.cancel", icon='X')

        names = [t.name for t, _ in targets_of(cutter, context.scene)]
        box = layout.column()
        box.active = False
        if not names:
            box.label(text="Cuts nothing", icon='ERROR')
        elif len(names) <= 2:
            box.label(text="Cuts " + ", ".join(names), icon='OBJECT_DATA')
        else:
            box.label(text=f"Cuts {len(names)} objects", icon='OBJECT_DATA')


class _CutterPanel(_Sidebar):
    bl_parent_id = "COCOCUTTER_PT_main"

    @classmethod
    def poll(cls, context):
        return cutter_of(context.active_object) is not None

    def setup(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        cutter = cutter_of(context.active_object)
        return layout, cutter, sheet_modifier(cutter)


class COCOCUTTER_PT_shape(_CutterPanel, Panel):
    bl_label = "Cutter"

    def draw(self, context):
        layout, cutter, mod = self.setup(context)
        _values(layout, mod, "Resolution")
        _values(layout, mod, "Length", "Offset")
        layout.prop(inp(mod, "Cyclic"), "value", text="Cyclic")


class COCOCUTTER_PT_noise(_CutterPanel, Panel):
    bl_label = "Noise"

    def draw(self, context):
        layout, cutter, mod = self.setup(context)
        _values(layout, mod, "Strength", "Scale")
        _values(layout, mod, "Detail", "Roughness", "Distortion")
        _values(layout, mod, "Seed")


class COCOCUTTER_PT_image(_CutterPanel, Panel):
    bl_label = "Image"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout, cutter, mod = self.setup(context)
        row = layout.row(align=True)
        row.prop(inp(mod, "Image"), "value", text="Image")
        row.operator("cococutter.load_image", text="", icon='FILEBROWSER')
        _values(layout, mod, "Image Strength", "Image Size", "Image Rotation")


class COCOCUTTER_PT_result(_CutterPanel, Panel):
    bl_label = "Result"

    def draw(self, context):
        layout, cutter, mod = self.setup(context)
        layout.row().prop(cutter.coco_cutter, "keep", expand=True)
        layout.prop(inp(mod, "Gap"), "value", text="Preview Gap")
        if has_input(mod, "Fill Cut"):
            layout.prop(inp(mod, "Fill Cut"), "value", text="Fill Cut")
            col = layout.column()
            col.active = get(mod, "Fill Cut")
            col.prop(cutter.coco_cutter, "material")
        else:
            layout.prop(cutter.coco_cutter, "material")
        if has_input(mod, "Vertex Group"):
            layout.prop(inp(mod, "Vertex Group"), "value", text="Vertex Group")
        layout.prop(cutter.coco_cutter, "solver")
        layout.prop(context.scene.coco_cutter, "delete_cutter")


class COCOCUTTER_PT_utils(_Sidebar, Panel):
    bl_parent_id = "COCOCUTTER_PT_main"
    bl_label = "Utilities"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        self.layout.operator("cococutter.split", icon='MOD_EXPLODE')


_classes = (
    COCOCUTTER_PT_main,
    COCOCUTTER_PT_shape,
    COCOCUTTER_PT_noise,
    COCOCUTTER_PT_image,
    COCOCUTTER_PT_result,
    COCOCUTTER_PT_utils,
)


def tab_name():
    """The sidebar tab from the add-on preferences (default "CocoCutter")."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences.tab_name if addon is not None else "CocoCutter"


_registered = []


def update_tab(_self=None, _context=None):
    """Re-register the panels under the current tab name (none if empty)."""
    for cls in reversed(_registered):
        bpy.utils.unregister_class(cls)
    _registered.clear()
    name = tab_name().strip()
    if not name:
        return
    for cls in _classes:
        cls.bl_category = name
        bpy.utils.register_class(cls)
        _registered.append(cls)


def register():
    update_tab()


def unregister():
    for cls in reversed(_registered):
        bpy.utils.unregister_class(cls)
    _registered.clear()
