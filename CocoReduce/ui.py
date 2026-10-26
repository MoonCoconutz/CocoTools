import bmesh
import bpy
import numpy as np
from bpy.types import Panel


class _Sidebar:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "CocoReduce"


def _triangles(ob, context):
    """Triangles of ob as shown (modifiers included)."""
    mesh = ob.evaluated_get(context.evaluated_depsgraph_get()).data
    corners = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", corners)
    return int(corners.sum()) - 2 * len(corners)


_selected_cache = {}


def _selected_triangles(context):
    """Selected triangles of the meshes in Edit Mode. Counted again only
    when a selection count changes: a 250,000-triangle mesh takes a while."""
    total = 0
    for ob in context.objects_in_mode_unique_data:
        if ob.type != 'MESH':
            continue
        me = ob.data
        key = (me.total_face_sel, me.total_vert_sel, me.total_edge_sel)
        hit = _selected_cache.get(me.name_full)
        if hit is None or hit[0] != key:
            bm = bmesh.from_edit_mesh(me)
            hit = (key, sum(len(f.verts) - 2 for f in bm.faces if f.select))
            _selected_cache[me.name_full] = hit
        total += hit[1]
    return total


class COCOREDUCE_PT_main(_Sidebar, Panel):
    bl_idname = "COCOREDUCE_PT_main"
    bl_label = "CocoReduce"

    def draw(self, context):
        layout = self.layout
        s = context.scene.coco_reduce
        layout.row().prop(s, "mode", expand=True)
        layout.prop(s, "percent")
        layout.prop(s, "part_size")
        layout.prop(s, "min_sides")

        row = layout.row()
        row.scale_y = 1.6
        col = layout.column()
        col.active = False
        if context.mode == 'EDIT_MESH':
            row.operator("cocoreduce.reduce_selection", icon='MOD_DECIM')
            tris = _selected_triangles(context)
            if tris:
                col.label(text=f"{tris:,} triangles selected, aiming for {round(tris * s.percent / 100):,}",
                          icon='FACESEL')
            else:
                col.label(text="Select the faces to reduce", icon='INFO')
            return
        row.operator("cocoreduce.make_lod", icon='MOD_DECIM')

        ob = context.active_object
        if ob is None or ob.type != 'MESH' or not ob.select_get():
            col.label(text="Select the meshes to reduce", icon='INFO')
        else:
            tris = _triangles(ob, context)
            col.label(text=f"{tris:,} triangles, aiming for {round(tris * s.percent / 100):,}",
                      icon='MESH_DATA')


class COCOREDUCE_PT_hard(_Sidebar, Panel):
    bl_parent_id = "COCOREDUCE_PT_main"
    bl_label = "Hard Surface"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.coco_reduce
        col = layout.column()
        col.active = s.mode == 'HARD'
        col.prop(s, "sharp_angle")
        col.prop(s, "flat_angle")


_classes = (COCOREDUCE_PT_main, COCOREDUCE_PT_hard)


def tab_name():
    """The sidebar tab from the add-on preferences (default "CocoReduce")."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences.tab_name if addon is not None else "CocoReduce"


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
