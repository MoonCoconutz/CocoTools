"""Texel density: measure the selected islands, and scale them to a target."""

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator

from . import common


def selected_islands(context):
    """Every UV island holding at least one selected UV face, over all objects
    in Edit Mode. Yields (object, bmesh, uv_layer, [(faces, uv_area, world_area)])."""
    sync = context.tool_settings.use_uv_select_sync
    for obj in common.edit_objects(context):
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            continue
        visible = {f for f in bm.faces if common.uv_face_visible(f, sync)}
        seeds = [f for f in visible if common.uv_face_selected(f, sync, bm)]
        if not seeds:
            continue
        coords = common.world_coords(bm, obj.matrix_world)
        result = []
        for island in common.islands(seeds, visible, uv_layer):
            uv_area, world_area = common.island_areas(island, uv_layer, coords)
            result.append((island, uv_area, world_area))
        yield obj, bm, uv_layer, result


def _texture_size(context):
    return int(context.scene.cocouvs.texture_size)


def _scale_length(context):
    return context.scene.unit_settings.scale_length or 1.0


class _EditModeOperator(Operator):
    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'


class COCOUVS_OT_calculate(_EditModeOperator):
    bl_idname = "cocouvs.calculate_density"
    bl_label = "Calculate"
    bl_description = "Measure the average texel density of the selected islands and put it in the field"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.cocouvs
        uv_total = world_total = 0.0
        count = 0
        for _obj, _bm, _uv, found in selected_islands(context):
            for _island, uv_area, world_area in found:
                uv_total += uv_area
                world_total += world_area
                count += 1
        ppm = common.density_ppm(uv_total, world_total, _texture_size(context), _scale_length(context))
        if not count or ppm is None:
            self.report({'WARNING'}, "Select at least one UV island with some surface area")
            return {'CANCELLED'}
        settings.density_ppm = ppm
        islands = "island" if count == 1 else "islands"
        self.report({'INFO'}, f"{common.format_density(ppm, settings.unit)} ({count} {islands})")
        return {'FINISHED'}


class _Assign:
    """Apply: Islands / Average. One operator per method, not a method
    setting: a button added to a pie keeps only the operator's name (see
    debug._DebugSelect)."""
    bl_options = {'REGISTER', 'UNDO'}
    method = 'ISLAND'

    def execute(self, context):
        target = context.scene.cocouvs.density_ppm
        size = _texture_size(context)
        scale_length = _scale_length(context)
        if target <= 0.0:
            self.report({'WARNING'}, "Set a texel density above zero first")
            return {'CANCELLED'}

        gathered = list(selected_islands(context))
        if not any(found for *_rest, found in gathered):
            self.report({'WARNING'}, "Select at least one UV island")
            return {'CANCELLED'}

        if self.method == 'AVERAGE':
            # The whole selection is scaled as one block about the centre of
            # its combined bounding box - the same as pressing S on it - so the
            # islands keep their sizes relative to each other *and* their
            # layout. Scaling each island about its own centre by the shared
            # factor kept the ratios but looked identical to Per Island.
            uv_total = sum(uv for *_r, found in gathered for _i, uv, _w in found)
            world_total = sum(w for *_r, found in gathered for _i, _uv, w in found)
            current = common.density_ppm(uv_total, world_total, size, scale_length)
            if not current:
                self.report({'WARNING'}, "The selected islands have no UV or surface area")
                return {'CANCELLED'}
            common.scale_islands_together(
                [(island, uv_layer) for _o, _bm, uv_layer, found in gathered for island, _u, _w in found],
                target / current,
            )
            for obj, *_rest in gathered:
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            return {'FINISHED'}

        skipped = 0
        for obj, _bm, uv_layer, found in gathered:
            for island, uv_area, world_area in found:
                current = common.density_ppm(uv_area, world_area, size, scale_length)
                if not current:
                    skipped += 1
                    continue
                common.scale_island(island, uv_layer, target / current)
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)

        if skipped:
            self.report({'WARNING'}, f"Skipped {skipped} island(s) with no UV or surface area")
        return {'FINISHED'}


class COCOUVS_OT_assign_per_island(_Assign, _EditModeOperator):
    bl_idname = "cocouvs.assign_density_per_island"
    bl_label = "Assign Texel Density per Island"
    bl_description = "Scale each selected island separately so each one matches the texel density in the field"
    method = 'ISLAND'


class COCOUVS_OT_assign_average(_Assign, _EditModeOperator):
    bl_idname = "cocouvs.assign_density_average"
    bl_label = "Assign Average Texel Density"
    bl_description = ("Scale the selected islands together, as one block, so their average texel density "
                      "matches the field; their relative sizes and layout are kept")
    method = 'AVERAGE'


class COCOUVS_OT_select_by_density(_EditModeOperator):
    bl_idname = "cocouvs.select_by_density"
    bl_label = "Select by Texel Density"
    bl_description = ("Select every UV island whose texel density matches the field. "
                      "Shift-click to add to the current selection")
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: FloatProperty(
        name="Tolerance",
        description="How far an island's density may be from the field's value and still match",
        default=1.0, min=0.0, soft_max=25.0, max=100.0, subtype='PERCENTAGE',
    )
    extend: BoolProperty(name="Extend", description="Add to the current selection", default=False)

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        target = context.scene.cocouvs.density_ppm
        if target <= 0.0:
            self.report({'WARNING'}, "Set a texel density above zero first")
            return {'CANCELLED'}
        size = _texture_size(context)
        scale_length = _scale_length(context)
        limit = target * self.tolerance / 100.0
        sync = context.tool_settings.use_uv_select_sync

        found = 0
        for obj in common.edit_objects(context):
            me = obj.data
            bm = bmesh.from_edit_mesh(me)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                continue
            visible = [f for f in bm.faces if common.uv_face_visible(f, sync)]
            coords = common.world_coords(bm, obj.matrix_world)
            matched = []
            for island in common.islands(visible, set(visible), uv_layer):
                ppm = common.density_ppm(*common.island_areas(island, uv_layer, coords), size, scale_length)
                if ppm is not None and abs(ppm - target) <= limit:
                    matched.append(island)
                    found += 1
            matched_faces = [f for island in matched for f in island]

            common.apply_face_selection(bm, visible, matched_faces, sync, self.extend)
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

        unit = context.scene.cocouvs.unit
        islands = "island" if found == 1 else "islands"
        self.report({'INFO'}, f"Selected {found} {islands} at {common.format_density(target, unit)}")
        return {'FINISHED'}


classes = (COCOUVS_OT_calculate, COCOUVS_OT_assign_per_island, COCOUVS_OT_assign_average,
           COCOUVS_OT_select_by_density)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
