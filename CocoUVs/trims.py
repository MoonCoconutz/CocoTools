"""Trims: rectangular areas of the UV space where a trim sheet's strips are,
stored per material, and buttons that move the selected islands into one.

Areas live on the material (Material.cocouvs_trims), so switching the active
material slot switches the list. Each area is a UV rectangle (u0, v0, u1, v1)
with a tiling direction. Draw mode (COCOUVS_OT_trim_draw) is a modal operator
in the UV Editor: drag on empty space for a new area, drag an area's edges or
corners to resize it and its inside to move it; Ctrl snaps to texture pixels
(the Texel Density texture size) and to UV vertices.
"""

import colorsys
import json
import math
import os
import random

import bmesh
import blf
import bpy
import gpu
import numpy as np
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty,
                       IntProperty, StringProperty)
from bpy.types import Operator, PropertyGroup, UIList
from gpu_extras.batch import batch_for_shader

from . import common

TILING_ITEMS = [
    ('HORIZONTAL', "Horizontal", "The trim repeats left to right: islands are fitted to its height", 'ARROW_LEFTRIGHT', 0),
    ('VERTICAL', "Vertical", "The trim repeats bottom to top: islands are fitted to its width", 'SORT_DESC', 1),
    ('NONE', "None", "The area does not repeat: islands are fitted inside it", 'CANCEL', 2),
]

HANDLE_PX = 7          # how close (in pixels, before UI scale) counts as on an edge
SNAP_PX = 12           # how close a UV vertex must be to snap to it
GRID_MIN_PX = 12       # the snap grid is never finer than this on screen
MIN_NEW_PX = 4         # a smaller drag on empty space is a click, not a new area

STATUS = ("Trim areas: drag empty space = new area  |  drag edge or corner = resize  |  "
          "drag inside = move  |  Ctrl = snap to vertices  |  Shift = snap to grid  |  "
          "X = remove  |  Esc / right-click = done")

# Draw mode state, shared with the overlay and the panel (Python only).
_state = {"running": False, "stop": False, "drag": None, "preview": None, "snap": None}
_handle = None


def _redraw(context=None):
    try:
        common.redraw_all(context)
    except AttributeError:
        pass


def _index_changed(self, context):
    if _state["drag"] is None and not _quiet[0]:
        record_change()
    _redraw(context)


# --- Undo in Edit Mode ----------------------------------------------------------
# Areas are material data, and an Edit Mode undo step stores only the mesh, so
# Ctrl+Z would not bring them back. Each change therefore stores a snapshot of
# every material's areas under a number, and writes that number into a hidden
# integer attribute on the first vertex of the edited mesh, which the undo step
# does store. After an undo or redo, the number found on the mesh says which
# snapshot to put back. Object Mode needs none of this: its undo steps store
# the whole file, materials included.

UNDO_LAYER = ".cocouvs_trims_undo"
_snapshots = {}         # number -> state
_base = {}              # mesh pointer -> number of the state before its first change
_next = [1]
_quiet = [False]        # writes that must not record a change (restoring, building an area)
_last_seen = [None]     # state at the last redraw: "before" for a mesh's first change


def _snapshot():
    return {m.name: ([(a.name, tuple(a.rect), a.tiling, tuple(a.color)) for a in m.cocouvs_trims],
                     m.cocouvs_trim_index)
            for m in bpy.data.materials if len(m.cocouvs_trims)}


def _edit_mesh():
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != 'MESH' or obj.mode != 'EDIT':
        return None
    return obj.data


def record_change():
    """Call after any change to the areas while in Edit Mode."""
    if _quiet[0]:
        return
    me = _edit_mesh()
    if me is None:
        return
    bm = bmesh.from_edit_mesh(me)
    if not len(bm.verts):
        return
    layer = bm.verts.layers.int.get(UNDO_LAYER)
    if layer is None:
        number = _next[0]
        _next[0] += 1
        _snapshots[number] = _last_seen[0] if _last_seen[0] is not None else _snapshot()
        _base[me.as_pointer()] = number
        layer = bm.verts.layers.int.new(UNDO_LAYER)
    number = _next[0]
    _next[0] += 1
    _snapshots[number] = _snapshot()
    bm.verts.ensure_lookup_table()
    bm.verts[0][layer] = number


def _restore(state):
    _quiet[0] = True
    try:
        for mat in bpy.data.materials:
            areas, index = state.get(mat.name, ([], -1))
            if not len(mat.cocouvs_trims) and not areas:
                continue
            mat.cocouvs_trims.clear()
            for name, rect, tiling, color in areas:
                a = mat.cocouvs_trims.add()
                a.name, a.rect, a.tiling, a.color = name, rect, tiling, color
            mat.cocouvs_trim_index = index
    finally:
        _quiet[0] = False
    _last_seen[0] = state
    _redraw()


@bpy.app.handlers.persistent
def _undo_post(*_args):
    me = _edit_mesh()
    if me is None:
        return
    bm = bmesh.from_edit_mesh(me)
    layer = bm.verts.layers.int.get(UNDO_LAYER)
    if layer is None:
        number = _base.get(me.as_pointer())
    elif len(bm.verts):
        bm.verts.ensure_lookup_table()
        number = bm.verts[0][layer]
    else:
        number = None
    state = _snapshots.get(number)
    if state is not None and state != _snapshot():
        _restore(state)


def commit(message):
    """Record a change made outside an operator's own undo step (draw mode)."""
    record_change()
    try:
        bpy.ops.ed.undo_push(message=message)
    except RuntimeError:
        pass


class COCOUVS_TrimArea(PropertyGroup):
    name: StringProperty(name="Name", default="Trim", update=_index_changed)
    rect: FloatVectorProperty(
        name="Area", size=4, default=(0.0, 0.0, 1.0, 0.25), precision=4,
        description="The area's UV rectangle: left, bottom, right, top",
        update=_index_changed,
    )
    tiling: EnumProperty(name="Tiling", items=TILING_ITEMS, default='HORIZONTAL',
                         description="Which way the trim repeats", update=_index_changed)
    color: FloatVectorProperty(name="Colour", subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
                               default=(0.3, 0.7, 1.0), description="Colour the area is drawn in",
                               update=_index_changed)


def material(context=None):
    """The active object's active material: whose areas the list shows."""
    context = context or bpy.context
    obj = context.view_layer.objects.active
    if obj is None or obj.type != 'MESH':
        return None
    return obj.active_material


def picked_area(context=None):
    mat = material(context)
    if mat is None:
        return None
    index = mat.cocouvs_trim_index
    if 0 <= index < len(mat.cocouvs_trims):
        return mat.cocouvs_trims[index]
    return None


def _unique_name(areas, base="Trim"):
    names = {a.name for a in areas}
    n = len(areas) + 1
    while f"{base} {n}" in names:
        n += 1
    return f"{base} {n}"


def add_area(mat, rect, name=None, tiling=None, color=None):
    """Append an area to the material's list and make it the picked one. The
    caller records the change once (record_change), not every field."""
    areas = mat.cocouvs_trims
    u0, v0, u1, v1 = rect
    if tiling is None:
        # A new area tiles along its long side.
        tiling = 'HORIZONTAL' if abs(u1 - u0) >= abs(v1 - v0) else 'VERTICAL'
    if color is None:
        hue = ((len(areas) + 1) * 0.618034) % 1.0
        color = colorsys.hsv_to_rgb(hue, 0.6, 1.0)
    _quiet[0] = True
    try:
        name = name or _unique_name(areas)
        area = areas.add()
        area.name = name
        area.rect = (min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1))
        area.tiling = tiling
        area.color = color
        mat.cocouvs_trim_index = len(areas) - 1
    finally:
        _quiet[0] = False
    return area


# --- Moving islands into an area ---------------------------------------------

def _selected_island_loops(context):
    """[(object, bmesh, uv_layer, [loops])], one entry per selected UV island,
    over every object in Edit Mode. The BMesh is returned too: once its Python
    wrapper is freed, every BMLoop taken from it raises ReferenceError."""
    sync = context.tool_settings.use_uv_select_sync
    result = []
    for obj in common.edit_objects(context):
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            continue
        visible = {f for f in bm.faces if common.uv_face_visible(f, sync)}
        seeds = [f for f in visible if common.uv_face_selected(f, sync, bm)]
        for island in common.islands(seeds, visible, uv_layer):
            result.append((obj, bm, uv_layer, [loop for face in island for loop in face.loops]))
    return result


def _long_axis(area_size, tiling):
    """The axis the islands line up along: 0 = u, 1 = v."""
    if tiling == 'HORIZONTAL':
        return 0
    if tiling == 'VERTICAL':
        return 1
    return 0 if area_size[0] >= area_size[1] else 1


def fit_islands(island_pts, rect, tiling, method, rotate, randomize, seed=0):
    """Place islands (a list of (n, 2) UV arrays) into `rect`, side by side
    along the area's length from its start. Returns the new arrays.

    TILE: scale to the area's cross size (height for a horizontal trim), so the
          island may run past the area's end - it repeats there. A non-tiling
          area falls back to FIT.
    FIT:  scale, keeping proportions, until it fits inside the area.
    FILL: stretch to exactly the area's size.
    MOVE: no scaling.
    """
    u0, v0, u1, v1 = rect
    start = np.array((u0, v0))
    size = np.array((u1 - u0, v1 - v0))
    along = _long_axis(size, tiling)
    cross = 1 - along
    if method == 'TILE' and tiling == 'NONE':
        method = 'FIT'
    rng = random.Random(seed)
    cursor = 0.0
    out = []
    # Line them up in the order they already sit along the area's length.
    order = sorted(range(len(island_pts)),
                   key=lambda i: (island_pts[i][:, along].min() + island_pts[i][:, along].max()))
    placed = [None] * len(island_pts)
    for i in order:
        pts = island_pts[i].astype(np.float64)
        lo = pts.min(axis=0)
        hi = pts.max(axis=0)
        dims = hi - lo
        if rotate and dims[0] != dims[1]:
            island_long = 0 if dims[0] > dims[1] else 1
            if island_long != along:
                centre = (lo + hi) * 0.5
                d = pts - centre
                pts = centre + np.column_stack((-d[:, 1], d[:, 0]))   # 90 degrees
                lo = pts.min(axis=0)
                hi = pts.max(axis=0)
                dims = hi - lo

        if method == 'TILE':
            s = size[cross] / dims[cross] if dims[cross] > 0 else 1.0
            scale = np.array((s, s))
        elif method == 'FIT':
            ratios = [size[k] / dims[k] for k in (0, 1) if dims[k] > 0]
            s = min(ratios) if ratios else 1.0
            scale = np.array((s, s))
        elif method == 'FILL':
            scale = np.array([size[k] / dims[k] if dims[k] > 0 else 1.0 for k in (0, 1)])
        else:
            scale = np.array((1.0, 1.0))

        pts = (pts - lo) * scale
        new_dims = dims * scale
        offset = np.zeros(2)
        offset[along] = start[along] + cursor
        if randomize and tiling != 'NONE' and size[along] > 0:
            # Any shift along a repeating trim shows a different part of it.
            offset[along] += rng.uniform(0.0, size[along])
        # Centred across the area (exact for TILE and FILL, which fill it).
        offset[cross] = start[cross] + (size[cross] - new_dims[cross]) * 0.5
        placed[i] = pts + offset
        cursor += new_dims[along]
    out.extend(placed)
    return out


# --- Operators: the list ------------------------------------------------------

class _TrimOperator(Operator):
    @classmethod
    def poll(cls, context):
        return material(context) is not None


class COCOUVS_OT_trim_add_selection(_TrimOperator):
    bl_idname = "cocouvs.trim_add_selection"
    bl_label = "Areas from Selection"
    bl_description = ("Add one trim area per selected UV face, around its UVs. "
                      "Faces giving the same area as another, or as an existing one, add it once")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and material(context) is not None

    def execute(self, context):
        sync = context.tool_settings.use_uv_select_sync
        mat = material(context)

        def key(rect):
            return tuple(round(x, 5) for x in rect)

        seen = {key(a.rect) for a in mat.cocouvs_trims}
        rects = []
        for obj in common.edit_objects(context):
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                continue
            for face in bm.faces:
                if not common.uv_face_selected(face, sync, bm):
                    continue
                us = [loop[uv_layer].uv.x for loop in face.loops]
                vs = [loop[uv_layer].uv.y for loop in face.loops]
                rect = (min(us), min(vs), max(us), max(vs))
                if rect[2] - rect[0] <= 0.0 or rect[3] - rect[1] <= 0.0 or key(rect) in seen:
                    continue
                seen.add(key(rect))
                rects.append(rect)
        if not rects:
            self.report({'WARNING'}, "Select some UV faces (not already areas) first")
            return {'CANCELLED'}
        # Top to bottom, then left to right, like reading the sheet.
        rects.sort(key=lambda r: (-r[3], r[0]))
        for rect in rects:
            add_area(mat, rect)
        record_change()
        _redraw(context)
        self.report({'INFO'}, f"Added {len(rects)} trim area{'s' if len(rects) != 1 else ''}")
        return {'FINISHED'}


class COCOUVS_OT_trim_remove(_TrimOperator):
    bl_idname = "cocouvs.trim_remove"
    bl_label = "Remove Trim Area"
    bl_description = "Remove the picked trim area"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mat = material(context)
        index = mat.cocouvs_trim_index
        if not 0 <= index < len(mat.cocouvs_trims):
            return {'CANCELLED'}
        mat.cocouvs_trims.remove(index)
        mat.cocouvs_trim_index = min(index, len(mat.cocouvs_trims) - 1)
        record_change()
        _redraw(context)
        return {'FINISHED'}


class COCOUVS_OT_trim_clear(_TrimOperator):
    bl_idname = "cocouvs.trim_clear"
    bl_label = "Delete All Trim Areas"
    bl_description = "Delete every trim area of the active material"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        mat = material(context)
        return mat is not None and len(mat.cocouvs_trims) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, message=f"Delete all {len(material(context).cocouvs_trims)} trim areas?",
            confirm_text="Delete All", icon='WARNING')

    def execute(self, context):
        mat = material(context)
        n = len(mat.cocouvs_trims)
        mat.cocouvs_trims.clear()
        mat.cocouvs_trim_index = -1
        record_change()
        _redraw(context)
        self.report({'INFO'}, f"Deleted {n} trim area{'s' if n != 1 else ''}")
        return {'FINISHED'}


class _TrimMove:
    """The list's up/down arrows. One operator per direction, like every
    button here that used to differ only by a setting: a button added to a
    pie keeps only the operator's name (see debug._DebugSelect)."""
    bl_options = {'REGISTER', 'UNDO'}
    step = -1

    def execute(self, context):
        mat = material(context)
        index = mat.cocouvs_trim_index
        other = index + self.step
        if not (0 <= index < len(mat.cocouvs_trims) and 0 <= other < len(mat.cocouvs_trims)):
            return {'CANCELLED'}
        mat.cocouvs_trims.move(index, other)
        mat.cocouvs_trim_index = other
        record_change()
        return {'FINISHED'}


class COCOUVS_OT_trim_move_up(_TrimMove, _TrimOperator):
    bl_idname = "cocouvs.trim_move_up"
    bl_label = "Move Trim Area Up"
    bl_description = "Move the picked trim area up the list"
    step = -1


class COCOUVS_OT_trim_move_down(_TrimMove, _TrimOperator):
    bl_idname = "cocouvs.trim_move_down"
    bl_label = "Move Trim Area Down"
    bl_description = "Move the picked trim area down the list"
    step = 1


FIT_METHODS = [
    ('TILE', "Fit + Tile", "Scale each island to the area's height (width for a vertical trim), "
                           "keeping proportions; it may run past the area's end, where the trim repeats"),
    ('FIT', "Fit Inside", "Scale each island, keeping proportions, until it fits inside the area"),
    ('FILL', "Fill", "Stretch each island to exactly cover the area"),
    ('MOVE', "Move", "Move each island into the area without scaling it"),
]


def _fit_description(method):
    return next(desc for key, _name, desc in FIT_METHODS if key == method) + (
        ". Several islands are lined up side by side")


class _TrimFit:
    """Fit + Tile, Fit Inside, Fill, Move: one operator per method (see
    _TrimMove). Auto-rotate, Randomize and Seed stay settings, in the redo
    panel."""
    bl_options = {'REGISTER', 'UNDO'}
    method = 'TILE'

    rotate: BoolProperty(name="Auto-rotate",
                         description="Turn islands 90 degrees when needed so their long side runs along the trim")
    randomize: BoolProperty(name="Randomize",
                            description="Shift each island a random amount along a repeating trim, "
                                        "so repeated pieces show different parts of it")
    seed: IntProperty(name="Seed", description="Change it for a different random layout", default=0, min=0)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and picked_area(context) is not None

    def invoke(self, context, event):
        settings = context.scene.cocouvs
        self.rotate = settings.trim_rotate
        self.randomize = settings.trim_randomize
        self.seed = random.randrange(10000) if self.randomize else 0
        return self.execute(context)

    def execute(self, context):
        area = picked_area(context)
        islands = _selected_island_loops(context)
        if not islands:
            self.report({'WARNING'}, "Select at least one UV island")
            return {'CANCELLED'}
        pts = [np.array([loop[uv].uv[:] for loop in loops]) for _o, _bm, uv, loops in islands]
        placed = fit_islands(pts, tuple(area.rect), area.tiling, self.method,
                             self.rotate, self.randomize, self.seed)
        touched = {}
        for (obj, _bm, uv, loops), new in zip(islands, placed):
            for loop, p in zip(loops, new):
                loop[uv].uv = p
            touched[obj.data.as_pointer()] = obj.data
        for me in touched.values():
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        n = len(islands)
        self.report({'INFO'}, f"Moved {n} island{'s' if n != 1 else ''} to {area.name}")
        return {'FINISHED'}


class COCOUVS_OT_trim_fit_tile(_TrimFit, Operator):
    bl_idname = "cocouvs.trim_fit_tile"
    bl_label = "Fit + Tile to Trim"
    bl_description = _fit_description('TILE')
    method = 'TILE'


class COCOUVS_OT_trim_fit_inside(_TrimFit, Operator):
    bl_idname = "cocouvs.trim_fit_inside"
    bl_label = "Fit Inside Trim"
    bl_description = _fit_description('FIT')
    method = 'FIT'


class COCOUVS_OT_trim_fill(_TrimFit, Operator):
    bl_idname = "cocouvs.trim_fill"
    bl_label = "Fill Trim"
    bl_description = _fit_description('FILL')
    method = 'FILL'


class COCOUVS_OT_trim_move_islands(_TrimFit, Operator):
    bl_idname = "cocouvs.trim_move_islands"
    bl_label = "Move to Trim"
    bl_description = _fit_description('MOVE')
    method = 'MOVE'


class COCOUVS_OT_trim_export(_TrimOperator):
    bl_idname = "cocouvs.trim_export"
    bl_label = "Export Trim Areas"
    bl_description = "Save the active material's trim areas to a file, to load them in another .blend"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        mat = material(context)
        return mat is not None and len(mat.cocouvs_trims) > 0

    def invoke(self, context, event):
        self.filepath = bpy.path.clean_name(material(context).name) + "_trims.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = bpy.path.ensure_ext(self.filepath, ".json")
        data = {"cocouvs_trims": 1, "areas": [
            {"name": a.name, "rect": list(a.rect), "tiling": a.tiling, "color": list(a.color)}
            for a in material(context).cocouvs_trims]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.report({'INFO'}, f"Saved {len(data['areas'])} trim areas to {os.path.basename(path)}")
        return {'FINISHED'}


class COCOUVS_OT_trim_import(_TrimOperator):
    bl_idname = "cocouvs.trim_import"
    bl_label = "Import Trim Areas"
    bl_description = "Load trim areas from a file into the active material"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    replace: BoolProperty(name="Replace Existing",
                          description="Remove the material's current areas first; off, the loaded ones are added")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            with open(self.filepath, encoding="utf-8") as f:
                data = json.load(f)
            areas = data["areas"]
        except (OSError, ValueError, KeyError, TypeError):
            self.report({'WARNING'}, "Not a CocoUVs trim areas file")
            return {'CANCELLED'}
        mat = material(context)
        if self.replace:
            mat.cocouvs_trims.clear()
        tilings = {item[0] for item in TILING_ITEMS}
        for a in areas:
            tiling = a.get("tiling") if a.get("tiling") in tilings else None
            add_area(mat, a["rect"], name=a.get("name"), tiling=tiling, color=a.get("color"))
        record_change()
        _redraw(context)
        self.report({'INFO'}, f"Loaded {len(areas)} trim areas into {mat.name}")
        return {'FINISHED'}


class COCOUVS_UL_trims(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        swatch = row.row()
        swatch.ui_units_x = 1.0
        swatch.prop(item, "color", text="")
        row.prop(item, "name", text="", emboss=False)
        tiling_icon = next(i[3] for i in TILING_ITEMS if i[0] == item.tiling)
        row.label(text="", icon=tiling_icon)


# --- Draw mode ----------------------------------------------------------------

def _uv_to_px(region, u, v):
    x, y = region.view2d.view_to_region(u, v, clip=False)
    return x, y


def _px_rect(region, rect):
    x0, y0 = _uv_to_px(region, rect[0], rect[1])
    x1, y1 = _uv_to_px(region, rect[2], rect[3])
    return x0, y0, x1, y1


def _uv_vertices(context):
    """UVs of every corner the UV Editor shows, for vertex snapping."""
    sync = context.tool_settings.use_uv_select_sync
    chunks = []
    for obj in common.edit_objects(context):
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            continue
        chunks.append(np.array([loop[uv_layer].uv[:] for face in bm.faces
                                if common.uv_face_visible(face, sync) for loop in face.loops],
                               dtype=np.float64).reshape(-1, 2))
    return np.concatenate(chunks) if chunks else np.zeros((0, 2))


class COCOUVS_OT_trim_draw(Operator):
    bl_idname = "cocouvs.trim_draw"
    bl_label = "Draw Trim Areas"
    bl_description = ("Draw and edit trim areas in the UV Editor: drag on empty space for a new area, "
                      "drag an area's edges or corners to resize it, drag its inside to move it. "
                      "Ctrl snaps to texture pixels and UV vertices, X removes the picked area, "
                      "Esc or right-click finishes")

    toggle: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'},
                         description="Pressing it again while drawing finishes draw mode")

    @classmethod
    def poll(cls, context):
        return (context.area is not None and context.area.type == 'IMAGE_EDITOR'
                and material(context) is not None)

    def invoke(self, context, event):
        if _state["running"]:
            if self.toggle:
                _state["stop"] = True
                _redraw(context)
            return {'FINISHED'}
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return {'CANCELLED'}
        self._area = context.area
        self._region = region
        self._verts = np.zeros((0, 2))
        _state.update(running=True, stop=False, drag=None, preview=None)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(STATUS)
        _redraw(context)
        return {'RUNNING_MODAL'}

    # -- helpers

    def _alive(self, context):
        return any(a == self._area for a in context.window.screen.areas)

    def _in_canvas(self, event):
        """Mouse over the UV canvas itself. With region overlap the sidebar,
        toolbar and headers lie on top of the WINDOW region, so a point inside
        WINDOW can still be on a panel button - those must get their clicks."""
        x, y = event.mouse_x, event.mouse_y
        region = self._region
        if not (region.x <= x < region.x + region.width and region.y <= y < region.y + region.height):
            return False
        for other in self._area.regions:
            if other == region or other.width <= 1 or other.height <= 1:
                continue
            if other.x <= x < other.x + other.width and other.y <= y < other.y + other.height:
                return False
        return True

    def _finish(self, context):
        _state.update(running=False, stop=False, drag=None, preview=None, snap=None)
        context.workspace.status_text_set(None)
        context.window.cursor_set('DEFAULT')
        _redraw(context)
        return {'FINISHED'}

    def _thr(self, context, px):
        return px * context.preferences.system.ui_scale

    def _hit(self, context, mx, my):
        """What is under the mouse: ('RESIZE', index, sides), ('MOVE', index,
        None) or ('NEW', None, None). The picked area's handles win."""
        mat = material(context)
        areas = mat.cocouvs_trims
        thr = self._thr(context, HANDLE_PX)
        order = list(range(len(areas)))
        picked = mat.cocouvs_trim_index
        if 0 <= picked < len(areas):
            order.remove(picked)
            order.insert(0, picked)
        for i in order:
            x0, y0, x1, y1 = _px_rect(self._region, areas[i].rect)
            sides = set()
            if y0 - thr <= my <= y1 + thr:
                if abs(mx - x0) <= thr:
                    sides.add('L')
                elif abs(mx - x1) <= thr:
                    sides.add('R')
            if x0 - thr <= mx <= x1 + thr:
                if abs(my - y0) <= thr:
                    sides.add('B')
                elif abs(my - y1) <= thr:
                    sides.add('T')
            if sides:
                return 'RESIZE', i, sides
        best = None
        for i, area in enumerate(areas):
            x0, y0, x1, y1 = _px_rect(self._region, area.rect)
            if x0 <= mx <= x1 and y0 <= my <= y1:
                size = (x1 - x0) * (y1 - y0)
                if best is None or size < best[0]:
                    best = (size, i)
        if best is not None:
            return 'MOVE', best[1], None
        return 'NEW', None, None

    def _verts_px(self):
        region = self._region
        x0, y0 = _uv_to_px(region, 0.0, 0.0)
        x1, y1 = _uv_to_px(region, 1.0, 1.0)
        return np.array((x0, y0)) + self._verts * np.array((x1 - x0, y1 - y0))

    def _grid_step(self, context):
        """Snap step in UV units: whole texture pixels, a power of two of them,
        and at least GRID_MIN_PX apart on screen. Single pixels of a 2048
        texture are ~0.2 screen pixels at normal zoom, so snapping to them
        looked exactly like not snapping."""
        size = int(context.scene.cocouvs.texture_size)
        x0, _y0 = _uv_to_px(self._region, 0.0, 0.0)
        x1, _y1 = _uv_to_px(self._region, 1.0, 0.0)
        pixel_on_screen = abs(x1 - x0) / size
        pixels = 1
        while pixels < size and pixels * pixel_on_screen < self._thr(context, GRID_MIN_PX):
            pixels *= 2
        return pixels / size

    def _align(self, context, px, axis, positions, span):
        """Best vertex to line an edge up with: a vertex whose `axis`
        coordinate is within the snap distance of one of `positions` (the
        edge's screen coordinate(s)) and that lies along the edge (`span` on
        the other axis). Returns (screen delta, vertex index) or None."""
        thr = self._thr(context, SNAP_PX)
        other = 1 - axis
        lo, hi = span
        along = (px[:, other] >= lo - thr) & (px[:, other] <= hi + thr)
        best = None
        for pos in positions:
            d = px[:, axis] - pos
            near = along & (np.abs(d) <= thr)
            if near.any():
                idx = np.flatnonzero(near)
                i = idx[np.argmin(np.abs(d[idx]))]
                if best is None or abs(d[i]) < abs(best[0]):
                    best = (float(d[i]), int(i))
        return best

    def _snap_point(self, context, u, v, mx, my, axes, spans, vertex, grid):
        """Snap a dragged point: the corner of a new area or of a resized one,
        or (one axis) a dragged edge. `spans[axis]` is the screen range, on the
        other axis, of the edge that moves along `axis`.

        Ctrl (vertex): a vertex under the mouse sets every dragged axis, even
        when only one edge moves; otherwise each edge lines up with a vertex
        along it. Shift (grid): the remaining axes go to the pixel grid."""
        uv = [u, v]
        done = set()
        marks = []
        if vertex and len(self._verts):
            px = self._verts_px()
            d = np.hypot(px[:, 0] - mx, px[:, 1] - my)
            i = int(np.argmin(d))
            if d[i] <= self._thr(context, SNAP_PX):
                for k in axes:
                    uv[k] = float(self._verts[i, k])
                done = set(axes)
                marks.append(tuple(self._verts[i]))
            else:
                for k in axes:
                    hit = self._align(context, px, k, [(mx, my)[k]], spans[k])
                    if hit is not None:
                        uv[k] = float(self._verts[hit[1], k])
                        done.add(k)
                        marks.append(tuple(self._verts[hit[1]]))
        step = None
        if grid:
            step = self._grid_step(context)
            for k in axes:
                if k not in done:
                    uv[k] = round(uv[k] / step) * step
        _state["snap"] = {"marks": marks, "step": step,
                          "cross": tuple(uv) if step is not None else None}
        return tuple(uv)

    def _snap_move(self, context, rect, vertex, grid):
        """Snap a moved area: Ctrl lines its edges up with vertices along
        them; Shift puts its lower-left corner on the pixel grid (for the
        axes the vertices did not decide)."""
        r = list(rect)
        done = set()
        marks = []
        if vertex and len(self._verts):
            px = self._verts_px()
            x0, y0, x1, y1 = _px_rect(self._region, r)
            for k, positions, span in ((0, [x0, x1], (y0, y1)), (1, [y0, y1], (x0, x1))):
                hit = self._align(context, px, k, positions, span)
                if hit is None:
                    continue
                vpos = px[hit[1], k]
                first = abs(positions[0] - vpos) <= abs(positions[1] - vpos)
                current = r[k] if first else r[k + 2]
                delta = float(self._verts[hit[1], k]) - current
                r[k] += delta
                r[k + 2] += delta
                done.add(k)
                marks.append(tuple(self._verts[hit[1]]))
        step = None
        if grid:
            step = self._grid_step(context)
            for k in (0, 1):
                if k not in done:
                    delta = round(r[k] / step) * step - r[k]
                    r[k] += delta
                    r[k + 2] += delta
        _state["snap"] = {"marks": marks, "step": step,
                          "cross": (r[0], r[1]) if step is not None else None}
        return tuple(r)

    def _cursor(self, context, mx, my):
        kind, _i, sides = self._hit(context, mx, my)
        if kind == 'RESIZE':
            if len(sides) == 2:
                cursor = 'SCROLL_XY'
            else:
                cursor = 'MOVE_X' if sides & {'L', 'R'} else 'MOVE_Y'
        elif kind == 'MOVE':
            cursor = 'HAND'
        else:
            cursor = 'CROSSHAIR'
        context.window.cursor_set(cursor)

    # -- drag

    def _press(self, context, mx, my, vertex, grid):
        mat = material(context)
        self._verts = _uv_vertices(context) if context.mode == 'EDIT_MESH' else np.zeros((0, 2))
        kind, index, sides = self._hit(context, mx, my)
        u, v = self._region.view2d.region_to_view(mx, my)
        _state["snap"] = None
        if kind == 'NEW':
            if vertex or grid:
                u, v = self._snap_point(context, u, v, mx, my, (0, 1),
                                        {0: (my, my), 1: (mx, mx)}, vertex, grid)
            _state["drag"] = {"kind": 'NEW', "start": (u, v)}
            _state["preview"] = (u, v, u, v)
            return
        _state["drag"] = {"kind": kind, "index": index, "sides": sides,
                          "orig": tuple(mat.cocouvs_trims[index].rect), "start": (u, v)}
        mat.cocouvs_trim_index = index

    def _update(self, context, mx, my, vertex, grid):
        drag = _state["drag"]
        _state["snap"] = None
        u, v = self._region.view2d.region_to_view(mx, my)
        if drag["kind"] == 'NEW':
            if vertex or grid:
                sx, sy = _uv_to_px(self._region, *drag["start"])
                spans = {0: (min(sy, my), max(sy, my)), 1: (min(sx, mx), max(sx, mx))}
                u, v = self._snap_point(context, u, v, mx, my, (0, 1), spans, vertex, grid)
            su, sv = drag["start"]
            _state["preview"] = (su, sv, u, v)
            _redraw(context)
            return
        area = material(context).cocouvs_trims[drag["index"]]
        r = list(drag["orig"])
        if drag["kind"] == 'MOVE':
            du, dv = u - drag["start"][0], v - drag["start"][1]
            r = [r[0] + du, r[1] + dv, r[2] + du, r[3] + dv]
            if vertex or grid:
                r = list(self._snap_move(context, r, vertex, grid))
        else:
            sides = drag["sides"]
            if vertex or grid:
                axes = tuple(k for k, pair in ((0, {'L', 'R'}), (1, {'B', 'T'})) if sides & pair)
                x0, y0, x1, y1 = _px_rect(self._region, drag["orig"])
                spans = {0: (min(y0, my), max(y1, my)), 1: (min(x0, mx), max(x1, mx))}
                u, v = self._snap_point(context, u, v, mx, my, axes, spans, vertex, grid)
            if 'L' in sides:
                r[0] = u
            if 'R' in sides:
                r[2] = u
            if 'B' in sides:
                r[1] = v
            if 'T' in sides:
                r[3] = v
            r = [min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])]
        area.rect = r
        _redraw(context)

    def _release(self, context):
        drag = _state["drag"]
        _state["drag"] = None
        _state["snap"] = None
        if drag["kind"] == 'NEW':
            preview = _state["preview"]
            _state["preview"] = None
            if preview is not None:
                x0, y0, x1, y1 = _px_rect(self._region, preview)
                small = self._thr(context, MIN_NEW_PX)
                if abs(x1 - x0) >= small and abs(y1 - y0) >= small:
                    add_area(material(context), preview)
                    commit("Add Trim Area")
        elif tuple(material(context).cocouvs_trims[drag["index"]].rect) != drag["orig"]:
            commit("Move Trim Area" if drag["kind"] == 'MOVE' else "Resize Trim Area")
        else:
            commit("Pick Trim Area")
        _redraw(context)

    def _cancel_drag(self, context):
        drag = _state["drag"]
        _state["drag"] = None
        _state["snap"] = None
        _state["preview"] = None
        if drag["kind"] != 'NEW':
            material(context).cocouvs_trims[drag["index"]].rect = drag["orig"]
        _redraw(context)

    def modal(self, context, event):
        if _state["stop"] or not self._alive(context) or material(context) is None:
            return self._finish(context)
        region = self._region
        mx = event.mouse_x - region.x
        my = event.mouse_y - region.y
        inside = self._in_canvas(event)
        drag = _state["drag"]

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFT_CTRL', 'RIGHT_CTRL',
                          'LEFT_SHIFT', 'RIGHT_SHIFT'}:
            if drag is not None:
                self._update(context, mx, my, event.ctrl, event.shift)
                return {'RUNNING_MODAL'}
            if inside:
                self._cursor(context, mx, my)
            else:
                context.window.cursor_set('DEFAULT')
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE':
            if event.value in {'PRESS', 'DOUBLE_CLICK'} and inside and drag is None:
                self._press(context, mx, my, event.ctrl, event.shift)
                _redraw(context)
                return {'RUNNING_MODAL'}
            if event.value == 'RELEASE' and drag is not None:
                self._release(context)
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'} if inside or drag is not None else {'PASS_THROUGH'}

        if not inside and drag is None:
            return {'PASS_THROUGH'}

        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            if drag is not None:
                self._cancel_drag(context)
                return {'RUNNING_MODAL'}
            return self._finish(context)

        if event.type in {'X', 'DEL'} and event.value == 'PRESS' and drag is None:
            mat = material(context)
            index = mat.cocouvs_trim_index
            if 0 <= index < len(mat.cocouvs_trims):
                mat.cocouvs_trims.remove(index)
                mat.cocouvs_trim_index = min(index, len(mat.cocouvs_trims) - 1)
                commit("Remove Trim Area")
                _redraw(context)
            return {'RUNNING_MODAL'}

        # Anything else (navigation, zoom) goes to the UV Editor as usual.
        return {'PASS_THROUGH'}


def is_drawing():
    return _state["running"]


# --- Overlay ------------------------------------------------------------------

def _rect_tris(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [(0, 1, 2), (0, 2, 3)]


def _rect_lines(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)]


def _draw_overlay():
    context = bpy.context
    if _state["drag"] is None and not _quiet[0]:
        # The "before" state for the edit mesh's first change (record_change);
        # only needed in Edit Mode, before the mesh carries the undo attribute.
        me = _edit_mesh()
        if me is not None and me.attributes.get(UNDO_LAYER) is None:
            _last_seen[0] = _snapshot()
    if not (context.window_manager.cocouvs_trims_show or _state["running"]):
        return
    space = context.space_data
    if space is None or space.mode != 'UV':
        return
    mat = material(context)
    if mat is None:
        return
    region = context.region
    areas = mat.cocouvs_trims
    picked = mat.cocouvs_trim_index
    scale = context.preferences.system.ui_scale
    fill = gpu.shader.from_builtin('UNIFORM_COLOR')
    line = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    line.uniform_float("viewportSize", (region.width, region.height))
    gpu.state.blend_set('ALPHA')

    def outline(coords, color, width):
        line.uniform_float("lineWidth", width * scale)
        line.uniform_float("color", color)
        batch_for_shader(line, 'LINES', {"pos": coords}).draw(line)

    labels = []
    for i, area in enumerate(areas):
        x0, y0, x1, y1 = _px_rect(region, area.rect)
        r, g, b = area.color
        is_picked = i == picked
        coords, indices = _rect_tris(x0, y0, x1, y1)
        fill.uniform_float("color", (r, g, b, 0.22 if is_picked else 0.10))
        batch_for_shader(fill, 'TRIS', {"pos": coords}, indices=indices).draw(fill)
        outline(_rect_lines(x0, y0, x1, y1), (r, g, b, 1.0), 2.5 if is_picked else 1.2)
        labels.append((x0, y1, area.name, (r, g, b)))

    if _state["running"] and 0 <= picked < len(areas):
        x0, y0, x1, y1 = _px_rect(region, areas[picked].rect)
        h = 4 * scale
        fill.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
        for hx, hy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1),
                       ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)):
            coords, indices = _rect_tris(hx - h, hy - h, hx + h, hy + h)
            batch_for_shader(fill, 'TRIS', {"pos": coords}, indices=indices).draw(fill)

    snap = _state["snap"]
    if snap is not None:
        step = snap["step"]
        if step is not None:
            # The grid being snapped to (Shift), kept faint.
            u_lo, v_lo = region.view2d.region_to_view(0, 0)
            u_hi, v_hi = region.view2d.region_to_view(region.width, region.height)
            coords = []
            k = math.floor(u_lo / step)
            while k * step <= u_hi and len(coords) < 2000:
                x, _y = _uv_to_px(region, k * step, 0.0)
                coords += [(x, 0), (x, region.height)]
                k += 1
            k = math.floor(v_lo / step)
            while k * step <= v_hi and len(coords) < 4000:
                _x, y = _uv_to_px(region, 0.0, k * step)
                coords += [(0, y), (region.width, y)]
                k += 1
            if coords:
                outline(coords, (1.0, 1.0, 1.0, 0.05), 1.0)
        h = 6 * scale
        for point in snap["marks"]:
            sx, sy = _uv_to_px(region, *point)
            outline(_rect_lines(sx - h, sy - h, sx + h, sy + h), (1.0, 0.6, 0.1, 1.0), 2.0)
        if snap["cross"] is not None and not snap["marks"]:
            sx, sy = _uv_to_px(region, *snap["cross"])
            outline([(sx - h, sy), (sx + h, sy), (sx, sy - h), (sx, sy + h)], (1.0, 1.0, 1.0, 0.8), 1.5)

    preview = _state["preview"]
    if preview is not None:
        x0, y0, x1, y1 = _px_rect(region, preview)
        outline(_rect_lines(x0, y0, x1, y1), (1.0, 1.0, 1.0, 0.9), 1.5)

    gpu.state.blend_set('NONE')

    font = 0
    blf.size(font, 11 * scale)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.8)
    blf.shadow_offset(font, 1, -1)
    pad = 4 * scale
    for x, y_top, name, (r, g, b) in labels:
        blf.color(font, r, g, b, 1.0)
        blf.position(font, x + pad, y_top - pad - 11 * scale, 0)
        blf.draw(font, name)
    blf.disable(font, blf.SHADOW)


def _show_changed(self, context):
    _redraw(context)


classes = (
    COCOUVS_TrimArea,
    COCOUVS_OT_trim_add_selection,
    COCOUVS_OT_trim_remove,
    COCOUVS_OT_trim_clear,
    COCOUVS_OT_trim_move_up,
    COCOUVS_OT_trim_move_down,
    COCOUVS_OT_trim_fit_tile,
    COCOUVS_OT_trim_fit_inside,
    COCOUVS_OT_trim_fill,
    COCOUVS_OT_trim_move_islands,
    COCOUVS_OT_trim_export,
    COCOUVS_OT_trim_import,
    COCOUVS_OT_trim_draw,
    COCOUVS_UL_trims,
)


def register():
    global _handle
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Material.cocouvs_trims = CollectionProperty(type=COCOUVS_TrimArea)
    bpy.types.Material.cocouvs_trim_index = IntProperty(name="Picked Trim Area", default=-1,
                                                        update=_index_changed)
    bpy.types.WindowManager.cocouvs_trims_show = BoolProperty(
        name="Show Areas", description="Show the active material's trim areas in the UV Editor",
        default=True, update=_show_changed)
    _handle = bpy.types.SpaceImageEditor.draw_handler_add(_draw_overlay, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.handlers.undo_post.append(_undo_post)
    bpy.app.handlers.redo_post.append(_undo_post)


def unregister():
    global _handle
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _undo_post in handlers:
            handlers.remove(_undo_post)
    if _handle is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _state.update(running=False, stop=True, drag=None, preview=None, snap=None)
    del bpy.types.WindowManager.cocouvs_trims_show
    del bpy.types.Material.cocouvs_trim_index
    del bpy.types.Material.cocouvs_trims
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
