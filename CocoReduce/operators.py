import re

import bmesh
import bpy
from bpy.types import Operator

from .reduce import reduce_mesh, tri_count


def lod_name(name):
    """Name_LOD1 for Name, Name_LOD3 for Name_LOD2; the next free number."""
    m = re.match(r"^(.*)_LOD(\d+)$", name)
    base, n = (m.group(1), int(m.group(2)) + 1) if m else (name, 1)
    while f"{base}_LOD{n}" in bpy.data.objects:
        n += 1
    return f"{base}_LOD{n}"


def _reduce(mesh, settings, progress, info, selected=None):
    return reduce_mesh(
        mesh, settings.percent / 100.0,
        hard_surface=settings.mode == 'HARD',
        sharp_angle=settings.sharp_angle,
        flat_angle=settings.flat_angle,
        part_size=settings.part_size / 100.0,
        progress=progress,
        info=info,
        selected=selected,
        min_sides=settings.min_sides,
    )


def _line(name, before, after, parts, percent):
    """The report for one mesh."""
    line = f"{name}: {before:,} → {after:,} triangles ({after / before:.0%})"
    if parts:
        line += f", {parts:,} small part{'s' if parts != 1 else ''} removed"
    if after > before * percent / 100.0 * 1.05 + 2:
        line += ", stopped there: more would break shapes (lower Min Sides or raise Small Parts to go further)"
    return line


def make_lod(src, settings, depsgraph, progress=None):
    """The LOD object of src beside it, its triangles before and after, and
    how many loose parts went; None if src has no faces."""
    mesh = bpy.data.meshes.new_from_object(
        src.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
    before = tri_count(mesh)
    if before == 0:
        bpy.data.meshes.remove(mesh)
        return None
    info = {}
    try:
        result = _reduce(mesh, settings, progress, info)
    finally:
        bpy.data.meshes.remove(mesh)

    name = lod_name(src.name)
    result.name = name
    ob = bpy.data.objects.new(name, result)
    for col in src.users_collection:
        col.objects.link(ob)
    ob.parent = src.parent
    ob.parent_type = src.parent_type
    ob.parent_bone = src.parent_bone
    ob.matrix_parent_inverse = src.matrix_parent_inverse.copy()
    ob.matrix_basis = src.matrix_basis.copy()
    for g in src.vertex_groups:
        if g.name not in ob.vertex_groups:
            ob.vertex_groups.new(name=g.name)
    return ob, before, tri_count(result), info.get("parts_removed", 0)


class COCOREDUCE_OT_make_lod(Operator):
    bl_idname = "cocoreduce.make_lod"
    bl_label = "Make LOD"
    bl_description = ("Make a reduced copy of each selected mesh, named <name>_LOD1 and so on. "
                      "The original is hidden, not changed")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            cls.poll_message_set("Works in Object Mode")
            return False
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        settings = context.scene.coco_reduce
        sources = [o for o in context.selected_objects if o.type == 'MESH']
        dg = context.evaluated_depsgraph_get()
        wm = context.window_manager
        made, lines = [], []
        wm.progress_begin(0, 1000)
        try:
            for i, src in enumerate(sources):
                def progress(f, i=i):
                    wm.progress_update(int(1000 * (i + f) / len(sources)))
                done = make_lod(src, settings, dg, progress)
                if done is None:
                    self.report({'WARNING'}, f"{src.name} has no faces")
                    continue
                ob, before, after, parts = done
                made.append((src, ob))
                lines.append(_line(ob.name, before, after, parts, settings.percent))
        finally:
            wm.progress_end()

        if not made:
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        for src, ob in made:
            src.hide_set(True)
            ob.select_set(True)
        context.view_layer.objects.active = made[-1][1]
        self.report({'INFO'}, "; ".join(lines))
        return {'FINISHED'}


def reduce_selection(ob, settings, progress=None):
    """Reduce the selected faces of ob (in Edit Mode) in place; the others
    stay as they are. Return the selection's triangles before and after and
    how many loose parts went; None if no face is selected."""
    ob.update_from_editmode()
    mesh = ob.data
    selected = [p.index for p in mesh.polygons if p.select]
    if not selected:
        return None
    before = sum(mesh.polygons[i].loop_total - 2 for i in selected)
    rest = tri_count(mesh) - before
    info = {}
    result = _reduce(mesh, settings, progress, info, selected)
    try:
        after = tri_count(result) - rest
        bm = bmesh.from_edit_mesh(mesh)
        bm.clear()
        bm.from_mesh(result)
        bmesh.update_edit_mesh(mesh)
    finally:
        bpy.data.meshes.remove(result)
    return before, after, info.get("parts_removed", 0)


class COCOREDUCE_OT_reduce_selection(Operator):
    bl_idname = "cocoreduce.reduce_selection"
    bl_label = "Reduce Selection"
    bl_description = ("Reduce the selected faces in place. Faces not selected stay as they are, "
                      "and the selection keeps meeting them")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH':
            cls.poll_message_set("Works in Edit Mode")
            return False
        return True

    def execute(self, context):
        settings = context.scene.coco_reduce
        obs = [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
        wm = context.window_manager
        lines = []
        wm.progress_begin(0, 1000)
        try:
            for i, ob in enumerate(obs):
                def progress(f, i=i):
                    wm.progress_update(int(1000 * (i + f) / len(obs)))
                done = reduce_selection(ob, settings, progress)
                if done is not None:
                    lines.append(_line(ob.name, *done, settings.percent))
        finally:
            wm.progress_end()
        if not lines:
            self.report({'WARNING'}, "Select the faces to reduce")
            return {'CANCELLED'}
        self.report({'INFO'}, "; ".join(lines))
        return {'FINISHED'}


_classes = (COCOREDUCE_OT_make_lod, COCOREDUCE_OT_reduce_selection)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
