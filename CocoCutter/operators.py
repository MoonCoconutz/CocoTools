import bmesh
import bpy
import gpu
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from . import nodes
from .cutter import (MODIFIER_NAME, cut_modifiers, cutter_of, get, is_cutter, put, recall,
                     remember, sheet_modifier, targets_of)

INSIDE_MATERIAL = "CocoCutter Inside"

# Events that move the view: passed through while not drawing a stroke, so
# the view can be orbited, zoomed or snapped to an axis between strokes.
_NAVIGATION = {
    'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
    'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM',
    'NUMPAD_0', 'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4', 'NUMPAD_5',
    'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9', 'NUMPAD_PERIOD',
    'NUMPAD_PLUS', 'NUMPAD_MINUS',
}

_STATUS = ("Drag across the objects to draw the cut   Ctrl: straight line   "
           "Enter / Space / Q: confirm   Esc / Right Mouse: cancel")


def _cuttable(context):
    return [o for o in context.selected_objects if o.type == 'MESH' and not is_cutter(o)]


def _world_bounds(objects):
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    lo = Vector(min(c[i] for c in corners) for i in range(3))
    hi = Vector(max(c[i] for c in corners) for i in range(3))
    return lo, hi


def _simplify(points, tolerance):
    """Ramer-Douglas-Peucker on screen points; returns the indices kept."""
    if len(points) < 3:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        a, b = points[first], points[last]
        ab = b - a
        length = ab.length
        worst, worst_d = None, tolerance
        for i in range(first + 1, last):
            ap = points[i] - a
            d = abs(ab.x * ap.y - ab.y * ap.x) / length if length > 1e-9 else ap.length
            if d > worst_d:
                worst, worst_d = i, d
        if worst is not None:
            keep.add(worst)
            stack += [(first, worst), (worst, last)]
    return sorted(keep)


def _inside_material():
    mat = bpy.data.materials.get(INSIDE_MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(INSIDE_MATERIAL)
        mat.diffuse_color = (0.35, 0.33, 0.3, 1.0)
        bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.35, 0.33, 0.3, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.9
    return mat


class COCOCUTTER_OT_draw(Operator):
    bl_idname = "cococutter.draw"
    bl_label = "Draw Cutter"
    bl_description = ("Draw a cut line across the selected meshes in the viewport. "
                      "The cut goes straight through, along the view direction, so draw "
                      "it in an orthographic view")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.area is not None
                and context.area.type == 'VIEW_3D' and bool(_cuttable(context)))

    def invoke(self, context, event):
        # A cutter still being worked on passes its settings to this one.
        current = cutter_of(context.active_object)
        if current is not None:
            remember(context.scene, current)
        self.area = context.area
        self.region = next((r for r in self.area.regions if r.type == 'WINDOW'), None)
        self.rv3d = self.area.spaces.active.region_3d
        if self.region is None or self.rv3d is None:
            return {'CANCELLED'}
        self.targets = _cuttable(context)
        lo, hi = _world_bounds(self.targets)
        self.centre = (lo + hi) / 2  # the drawing plane passes through it

        self.screen = []      # stroke points in region pixels
        self.world = []       # the same points on the drawing plane
        self.view_rot = None  # view rotation the stroke was drawn in
        self.drawing = False
        self.anchor = None    # Ctrl: the straight line's start

        self.handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw, (), 'WINDOW', 'POST_VIEW')
        context.workspace.status_text_set(_STATUS)
        context.window_manager.modal_handler_add(self)
        self.area.tag_redraw()
        return {'RUNNING_MODAL'}

    # -- events -----------------------------------------------------------

    def _mouse(self, event):
        return Vector((event.mouse_x - self.region.x, event.mouse_y - self.region.y))

    def _over_viewport(self, event):
        """Inside the viewport and not over a sidebar, toolbar or header
        drawn on top of it."""
        x, y = event.mouse_x, event.mouse_y
        r = self.region
        if not (r.x <= x < r.x + r.width and r.y <= y < r.y + r.height):
            return False
        for other in self.area.regions:
            if other.type in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'ASSET_SHELF'} and other.width > 1:
                if other.x <= x < other.x + other.width and other.y <= y < other.y + other.height:
                    return False
        return True

    def _project(self, co):
        return view3d_utils.region_2d_to_location_3d(self.region, self.rv3d, co, self.centre)

    def _add_point(self, co):
        self.screen.append(co)
        self.world.append(self._project(co))

    def modal(self, context, event):
        self.area.tag_redraw()

        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}

        if event.type in {'RET', 'NUMPAD_ENTER', 'SPACE', 'Q'} and event.value == 'PRESS':
            if self.drawing or len(self.world) < 2:
                return {'RUNNING_MODAL'}
            self._finish(context)
            self._make_cutter(context)
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS' and self._over_viewport(event):
                # A new stroke replaces the last one.
                self.drawing = True
                self.screen, self.world = [], []
                self.view_rot = self.rv3d.view_rotation.copy()
                co = self._mouse(event)
                self.anchor = co
                self._add_point(co)
            elif event.value == 'RELEASE' and self.drawing:
                self.drawing = False
                self._stroke_done(event)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE' and self.drawing:
            co = self._mouse(event)
            if event.ctrl:
                self.screen, self.world = [], []
                self._add_point(self.anchor)
                self._add_point(co)
            elif (co - self.screen[-1]).length >= 3.0:
                self._add_point(co)
            return {'RUNNING_MODAL'}

        if event.type in _NAVIGATION and not self.drawing:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def _stroke_done(self, event):
        if len(self.screen) < 2 or (self.screen[-1] - self.screen[0]).length < 6 and len(self.screen) < 4:
            self.screen, self.world = [], []
            return
        kept = _simplify(self.screen, 2.0)
        self.screen = [self.screen[i] for i in kept]
        self.world = [self.world[i] for i in kept]

    def _finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
        context.workspace.status_text_set(None)
        self.area.tag_redraw()

    def _draw(self):
        if len(self.world) < 2:
            return
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": [tuple(p) for p in self.world]})
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        shader.uniform_float("viewportSize", (self.region.width, self.region.height))
        shader.uniform_float("lineWidth", 2.0)
        shader.uniform_float("color", (1.0, 0.75, 0.2, 1.0))
        batch.draw(shader)
        gpu.state.blend_set('NONE')

    # -- result -----------------------------------------------------------

    def _make_cutter(self, context):
        make_cutter(context, self.targets, self.world, self.view_rot)


def _is_loop(points):
    """A stroke whose ends meet: drawn as a closed shape."""
    if len(points) < 4:
        return False
    length = sum((b - a).length for a, b in zip(points, points[1:]))
    return (points[-1] - points[0]).length < 0.1 * length


def _close_loop(points):
    """Cut a drawn loop's tail where it comes nearest the start. A hand-drawn
    loop overshoots its start or lands on it, and closing it as drawn folds
    the tube over itself at the joint, which Exact answers with a wrong
    volume or nothing at all (a test loop ending on its own start point,
    2026-10-02)."""
    n = len(points)
    start = points[0]
    nearest = min(range(max(2, n * 3 // 4), n), key=lambda i: (points[i] - start).length)
    points = points[:nearest + 1]
    step = sum((b - a).length for a, b in zip(points, points[1:])) / (len(points) - 1)
    if len(points) > 3 and (points[-1] - start).length < step * 0.5:
        points = points[:-1]
    return points


def _extend_ends(points, outline, margin):
    """Carry each end that stops inside the targets' bounds straight on,
    along its last segment, until it is `margin` out. A stroke drawn a little
    short of an edge then still cuts right across, rather than turning off
    along the chord where the Cut group's strips carry it on.

    `outline` is the targets' bounding corners flattened onto the stroke's
    plane; the test uses their box in the chord's frame (t along the chord,
    s across it), the frame the strips and the slab are built in."""
    chord = points[-1] - points[0]
    if chord.length < 1e-9:
        return list(points)
    t_axis = chord.normalized()
    s_axis = Vector((-t_axis.y, t_axis.x))

    def to_ts(p):
        return Vector((p.dot(t_axis), p.dot(s_axis)))

    flat = [to_ts(c) for c in outline]
    lo = Vector((min(c.x for c in flat), min(c.y for c in flat)))
    hi = Vector((max(c.x for c in flat), max(c.y for c in flat)))

    def carried_out(end, before):
        q, d = to_ts(end), to_ts(end) - to_ts(before)
        if not (lo.x < q.x < hi.x and lo.y < q.y < hi.y) or d.length < 1e-9:
            return None
        d.normalize()
        k = min(((hi[i] if d[i] > 0 else lo[i]) - q[i]) / d[i]
                for i in range(2) if abs(d[i]) > 1e-9)
        q = q + d * (k + margin)
        return t_axis * q.x + s_axis * q.y

    points = list(points)
    tail = carried_out(points[-1], points[-2])
    head = carried_out(points[0], points[1])
    if tail is not None:
        points.append(tail)
    if head is not None:
        points.insert(0, head)
    return points


def make_cutter(context, targets, points, view_rot):
    """Build a cutter from a stroke drawn in a view with rotation `view_rot`
    (`points` in world space, on a plane facing that view), and give every
    target its Cut modifier. Leaves the cutter active and alone selected."""
    lo, hi = _world_bounds(targets)
    centre = (lo + hi) / 2
    size = max((hi - lo).length, 1e-4)
    rot = view_rot.to_matrix()
    frame = Matrix.Translation(centre) @ rot.to_4x4()
    to_local = frame.inverted()
    local = [(to_local @ p).to_2d() for p in points]
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    outline = [(to_local @ c).to_2d() for c in corners]
    cyclic = _is_loop(local)
    if cyclic:
        local = _close_loop(local)
    else:
        local = _extend_ends(local, outline, size * 0.02)

    curve = bpy.data.curves.new(MODIFIER_NAME, 'CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(local) - 1)
    for bp, co in zip(spline.bezier_points, local):
        bp.co = (co.x, co.y, 0.0)
        bp.handle_left_type = bp.handle_right_type = 'AUTO'

    cutter = bpy.data.objects.new(MODIFIER_NAME, curve)
    cutter.matrix_world = frame
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    collection = targets[0].users_collection[0] if targets[0].users_collection         else context.scene.collection
    collection.objects.link(cutter)

    # Deep enough to pass through every target along the view axis.
    axis = rot.col[2]
    depth = 2 * max(abs((c - centre).dot(axis)) for c in corners)

    sheet = cutter.modifiers.new(MODIFIER_NAME, 'NODES')
    sheet.node_group = nodes.get_group(nodes.SHEET_NAME)
    put(sheet, "Length", depth * 1.45)
    put(sheet, "Strength", size * 0.02)
    put(sheet, "Scale", 4.0 / size)
    put(sheet, "Gap", size * 0.02)
    put(sheet, "Cyclic", cyclic)
    recall(context.scene, sheet)

    material = context.scene.coco_cutter.material or _inside_material()
    cut_group = nodes.get_group(nodes.CUT_NAME)
    for ob in targets:
        mod = ob.modifiers.new(MODIFIER_NAME, 'NODES')
        mod.node_group = cut_group
        put(mod, "Cutter", cutter)
        uv = ob.data.uv_layers.active
        put(mod, "UV Map", uv.name if uv else "UVMap")
    # Through the property, so every target receives it.
    cutter.coco_cutter.material = material

    for ob in context.selected_objects:
        ob.select_set(False)
    cutter.select_set(True)
    context.view_layer.objects.active = cutter
    return cutter


def _apply_through(context, ob, mod):
    """Apply every modifier up to and including `mod`, so the result matches
    what the viewport showed. Other cutters' modifiers stay, as do disabled
    ones and everything after `mod`. Raises RuntimeError when Blender
    refuses (shape keys, for one)."""
    for m in list(ob.modifiers):
        is_ours = m == mod
        if not is_ours and (m in cut_modifiers(ob) or not m.show_viewport):
            continue
        name = m.name
        with context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
            bpy.ops.object.modifier_apply(modifier=name, single_user=True)
        if is_ours:
            return


def _delete_faces(mesh, flags, value):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    doomed = [f for f in bm.faces if flags[f.index] == value]
    bmesh.ops.delete(bm, geom=doomed, context='FACES')
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def _split_sides(ob):
    """Turn a Keep Both result into two objects; returns the new one."""
    mesh = ob.data
    attr = mesh.attributes.get(nodes.A_SIDE)
    if attr is None:
        return None
    flags = [False] * len(mesh.polygons)
    attr.data.foreach_get("value", flags)
    mesh.attributes.remove(attr)
    if all(flags) or not any(flags):
        return None
    other = ob.copy()
    other.data = mesh.copy()
    for collection in ob.users_collection:
        collection.objects.link(other)
    _delete_faces(mesh, flags, True)
    _delete_faces(other.data, flags, False)
    return other


def _remove_cutter(cutter):
    curve = cutter.data
    bpy.data.objects.remove(cutter)
    if curve is not None and curve.users == 0:
        bpy.data.curves.remove(curve)


class COCOCUTTER_OT_cut(Operator):
    bl_idname = "cococutter.cut"
    bl_label = "Cut"
    bl_description = "Apply the cut to every object this cutter cuts"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and cutter_of(context.active_object) is not None

    def execute(self, context):
        cutter = cutter_of(context.active_object)
        sheet = sheet_modifier(cutter)
        pairs = targets_of(cutter, context.scene)
        remember(context.scene, cutter)
        if not pairs:
            self.report({'WARNING'}, "This cutter does not cut anything")
            return {'CANCELLED'}

        # The gap only separates the pieces on screen; the cut keeps them in place.
        put(sheet, "Gap", 0.0)
        cutter.update_tag()
        context.evaluated_depsgraph_get().update()

        results, failed = [], []
        for ob, mod in pairs:
            try:
                _apply_through(context, ob, mod)
            except RuntimeError as err:
                failed.append(f"{ob.name}: {str(err).strip().removeprefix('Error: ')}")
                continue
            results.append(ob)
            other = _split_sides(ob)
            if other is not None:
                results.append(other)

        if failed:
            self.report({'WARNING'}, "Not cut: " + "; ".join(failed))
        if not results:
            return {'CANCELLED'}
        if context.scene.coco_cutter.delete_cutter and not failed:
            _remove_cutter(cutter)
        else:
            cutter.select_set(False)
        for ob in context.selected_objects:
            ob.select_set(False)
        for ob in results:
            ob.select_set(True)
        context.view_layer.objects.active = results[0]
        return {'FINISHED'}


class COCOCUTTER_OT_cancel(Operator):
    bl_idname = "cococutter.cancel"
    bl_label = "Cancel"
    bl_description = "Delete the cutter and remove its cut from every object, leaving them as they were"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return context.mode == 'OBJECT' and (cutter_of(ob) is not None or bool(cut_modifiers(ob)))

    def execute(self, context):
        ob = context.active_object
        cutter = cutter_of(ob)
        if cutter is None:
            # Leftovers of a cutter deleted by hand.
            for mod in cut_modifiers(ob):
                if not is_cutter(get(mod, "Cutter")):
                    ob.modifiers.remove(mod)
            return {'FINISHED'}
        targets = []
        for target, mod in targets_of(cutter, context.scene):
            target.modifiers.remove(mod)
            targets.append(target)
        _remove_cutter(cutter)
        for target in targets:
            target.select_set(True)
        if targets:
            context.view_layer.objects.active = targets[0]
        return {'FINISHED'}


class COCOCUTTER_OT_load_image(Operator):
    bl_idname = "cococutter.load_image"
    bl_label = "Load Image"
    bl_description = "Load an image whose brightness pushes the cut surface in and out"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return cutter_of(context.active_object) is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        cutter = cutter_of(context.active_object)
        put(sheet_modifier(cutter), "Image", image)
        cutter.update_tag()
        return {'FINISHED'}


def _selected_meshes(context):
    return [o for o in context.selected_objects if o.type == 'MESH']


class COCOCUTTER_OT_split(Operator):
    bl_idname = "cococutter.split"
    bl_label = "Split Loose"
    bl_description = "Separate every disconnected piece of the selected meshes into its own object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(_selected_meshes(context))

    def execute(self, context):
        meshes = _selected_meshes(context)
        with context.temp_override(active_object=meshes[0], object=meshes[0],
                                   selected_objects=meshes, selected_editable_objects=meshes):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='LOOSE')
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


_classes = (
    COCOCUTTER_OT_draw,
    COCOCUTTER_OT_cut,
    COCOCUTTER_OT_cancel,
    COCOCUTTER_OT_load_image,
    COCOCUTTER_OT_split,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
