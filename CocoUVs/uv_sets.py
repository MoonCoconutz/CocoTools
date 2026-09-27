"""UV map list across every selected object.

The list shows every UV map name found on any target object (active,
selected, or in Edit Mode), each once - not just the active object's own
maps. Every command acts on the name, on every object that has it:

- clicking a row makes that map active wherever it exists;
- a row whose map is still active on some objects but is not the chosen one
  is drawn red: those objects lack the chosen map and stayed where they were;
- N/total shows how many objects have that map active.

A UIList can only draw a real collection, so the names live in
WindowManager.cocouvs_uv_list (never saved). The panel draw works out the
names; if they differ from the collection it schedules a one-shot timer to
rewrite it, because Blender forbids writing ID data from a draw call.
"""

import types

import bmesh
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import common

MAX_UV_MAPS = 8

# The row the user last clicked (or added). Kept in Python, not saved.
_chosen = None
_syncing = False


# --- Which names, which counts, which row ------------------------------------

def union_names(objects):
    """Every UV map name on these objects, each once, in order of first
    appearance (so the active object's own order comes first)."""
    names = []
    seen = set()
    for obj in objects:
        for layer in obj.data.uv_layers:
            if layer.name not in seen:
                seen.add(layer.name)
                names.append(layer.name)
    return names


def active_map_counts(objects):
    """{UV map name: how many of these objects have it active}. Counted per
    object, not per mesh: instances sharing a mesh each count."""
    counts = {}
    for obj in objects:
        layer = obj.data.uv_layers.active
        if layer is not None:
            counts[layer.name] = counts.get(layer.name, 0) + 1
    return counts


def chosen_name(counts, objects):
    """The row shown as selected: the one last clicked while any object still
    has it active, otherwise the map active on the most objects (the active
    object's map wins a tie)."""
    if _chosen is not None and counts.get(_chosen):
        return _chosen
    if not counts:
        return None
    first = objects[0].data.uv_layers.active if objects else None
    first = first.name if first is not None else None
    return max(counts, key=lambda name: (counts[name], name == first))


def current_name(context=None):
    objects = common.target_objects(context)
    return chosen_name(active_map_counts(objects), objects)


def set_chosen(name):
    global _chosen
    _chosen = name


def make_active(name, context=None):
    """Make `name` the active UV map on every target mesh that has it."""
    set_chosen(name)
    for me in common.target_meshes(context):
        index = me.uv_layers.find(name)
        if index != -1 and me.uv_layers.active_index != index:
            me.uv_layers.active_index = index
    context = context or bpy.context
    if context.scene.cocouvs.update_seams:
        done = set()
        for obj in common.target_objects(context):
            if obj.data.as_pointer() not in done and obj.data.uv_layers.get(name) is not None:
                done.add(obj.data.as_pointer())
                common.seams_from_uv_map(obj, name)


# --- The collection the list draws ----------------------------------------

def _window_context():
    wm = bpy.context.window_manager
    window = bpy.context.window or next(iter(wm.windows), None)
    return types.SimpleNamespace(view_layer=window.view_layer) if window else None


def sync_list(context=None):
    """Rewrite WindowManager.cocouvs_uv_list to the current names. Must not
    run from a draw call."""
    global _syncing
    context = context or _window_context()
    if context is None:
        return
    names = union_names(common.target_objects(context))
    items = bpy.context.window_manager.cocouvs_uv_list
    if [item.name for item in items] == names:
        return
    _syncing = True
    try:
        items.clear()
        for name in names:
            item = items.add()
            item.name = name
            item.stored_name = name
    finally:
        _syncing = False
    common.redraw_all()


def _sync_timer():
    try:
        sync_list()
    except Exception:
        import traceback
        traceback.print_exc()
    return None


def request_sync(names):
    """Called from the panel draw: schedule sync_list() if the list is stale."""
    items = bpy.context.window_manager.cocouvs_uv_list
    if [item.name for item in items] != names and not bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.register(_sync_timer, first_interval=0.0)


def _name_update(self, context):
    """Renaming a row renames that UV map on every target mesh that has it."""
    if _syncing:
        return
    old, new = self.stored_name, self.name
    if not old or not new or old == new:
        return
    for me in common.target_meshes(context):
        if me.uv_layers.get(old) is not None and me.uv_layers.get(new) is None:
            common.rename_uv_map(me, old, new)
    if _chosen == old:
        set_chosen(new)
    self.stored_name = new


def _render_get(self):
    layers = [me.uv_layers.get(self.name) for me in common.target_meshes()]
    layers = [layer for layer in layers if layer is not None]
    return bool(layers) and all(layer.active_render for layer in layers)


def _render_set(self, value):
    """The camera sets the render map on every mesh that has this name. It
    never touches the active (edited) map. Material Preview and Rendered show
    the render map; Solid mode always shows the active one (verified on 5.2).
    Like Blender's own camera it cannot be switched off, only moved."""
    if not value:
        return
    for me in common.target_meshes():
        layer = me.uv_layers.get(self.name)
        if layer is not None and not layer.active_render:
            layer.active_render = True


class COCOUVS_UVMapItem(PropertyGroup):
    name: StringProperty(name="Name", update=_name_update)
    stored_name: StringProperty()
    render: BoolProperty(
        name="Render",
        description="Use this UV map for rendering (and in Material Preview) on every selected "
        "object that has it. It does not change the UV map you are editing",
        get=_render_get,
        set=_render_set,
    )


def _uv_index_get(self):
    items = bpy.context.window_manager.cocouvs_uv_list
    return items.find(current_name()) if len(items) else -1


def _uv_index_set(self, value):
    items = bpy.context.window_manager.cocouvs_uv_list
    if 0 <= value < len(items):
        make_active(items[value].name)


# --- Operators ---------------------------------------------------------------

def _unique_name(meshes, base="UVMap"):
    taken = {layer.name for me in meshes for layer in me.uv_layers}
    if base not in taken:
        return base
    i = 1
    while f"{base}.{i:03d}" in taken:
        i += 1
    return f"{base}.{i:03d}"


def _mesh_object(me, context):
    for obj in context.view_layer.objects:
        if obj.data == me:
            return obj
    return None


def _swap_uv_maps(me, in_edit, i, j):
    """Swap two UV maps' positions: their data and names change places, so
    everything that refers to a UV map by name keeps pointing at the same UVs.
    Blender has no API to reorder UV maps, and this avoids deleting any."""
    layers = me.uv_layers
    name_i, name_j = layers[i].name, layers[j].name
    active_name = layers.active.name if layers.active else None
    render_name = next((l.name for l in layers if l.active_render), None)

    if in_edit:
        bm = bmesh.from_edit_mesh(me)
    else:
        bm = bmesh.new()
        bm.from_mesh(me)
    uv_a = bm.loops.layers.uv[name_i]
    uv_b = bm.loops.layers.uv[name_j]
    for face in bm.faces:
        for loop in face.loops:
            a = loop[uv_a]
            b = loop[uv_b]
            a_uv, b_uv = a.uv.copy(), b.uv.copy()
            a.uv, b.uv = b_uv, a_uv
            a_pin, b_pin = a.pin_uv, b.pin_uv
            if a_pin != b_pin:
                a.pin_uv, b.pin_uv = b_pin, a_pin
    if in_edit:
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    else:
        bm.to_mesh(me)
        bm.free()

    # The names swap with the data. Done marks are keyed by name, so they
    # follow on their own.
    temp = _unique_name([me], "__cocouvs_swap")
    layers[i].name = temp
    layers[j].name = name_i
    layers[i].name = name_j

    if active_name is not None:
        layers.active_index = layers.find(active_name)
    if render_name is not None:
        layers[layers.find(render_name)].active_render = True


class COCOUVS_OT_uv_add(Operator):
    bl_idname = "cocouvs.uv_add"
    bl_label = "Add UV Map"
    bl_description = "Add a UV map to every selected mesh, copied from its active one"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(common.target_meshes(context))

    def execute(self, context):
        meshes = common.target_meshes(context)
        name = _unique_name(meshes)
        added = 0
        for me in meshes:
            if len(me.uv_layers) >= MAX_UV_MAPS:
                continue
            # In Edit Mode new() adds the layer but returns None, so find it
            # by name afterwards.
            me.uv_layers.new(name=name)
            index = me.uv_layers.find(name)
            if index != -1:
                me.uv_layers.active_index = index
                added += 1
        if not added:
            self.report({'WARNING'}, f"Every selected mesh already has {MAX_UV_MAPS} UV maps")
            return {'CANCELLED'}
        set_chosen(name)
        sync_list(context)
        return {'FINISHED'}


class COCOUVS_OT_uv_remove(Operator):
    bl_idname = "cocouvs.uv_remove"
    bl_label = "Remove UV Map"
    bl_description = "Remove the selected UV map from every selected mesh that has it"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return current_name(context) is not None

    def execute(self, context):
        name = current_name(context)
        for me in common.target_meshes(context):
            layer = me.uv_layers.get(name)
            if layer is not None:
                me.uv_layers.remove(layer)
                common.remove_done_marks(me, name)
        set_chosen(None)
        sync_list(context)
        return {'FINISHED'}


class COCOUVS_OT_uv_move(Operator):
    bl_idname = "cocouvs.uv_move"
    bl_label = "Move UV Map"
    bl_description = "Move the selected UV map up or down on every selected mesh that has it"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    @classmethod
    def poll(cls, context):
        return current_name(context) is not None

    def execute(self, context):
        name = current_name(context)
        step = -1 if self.direction == 'UP' else 1
        moved = 0
        for me in common.target_meshes(context):
            i = me.uv_layers.find(name)
            j = i + step
            if i == -1 or not (0 <= j < len(me.uv_layers)):
                continue
            obj = _mesh_object(me, context)
            _swap_uv_maps(me, obj is not None and obj.mode == 'EDIT', i, j)
            moved += 1
        if not moved:
            return {'CANCELLED'}
        sync_list(context)
        return {'FINISHED'}


RENAME_BASE = "map"   # By Index with an empty box: map1, map2, ...


def _find_replace(name, find, replace, case_sensitive):
    """Blender's batch-rename Find/Replace (Ctrl+F2) semantics on one name,
    plain text only."""
    import re

    if not find:
        return name
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.sub(re.escape(find), replace.replace("\\", "\\\\"), name, flags=flags)


class COCOUVS_RenameSettings(PropertyGroup):
    """The rename popover's fields (WindowManager.cocouvs_rename, never saved)."""
    mode: EnumProperty(name="Mode", items=[
        ('INDEX', "By Index", "Name maps by their position: the typed name plus 1, 2, 3 (empty: map1, map2, ...)"),
        ('FIND', "Find/Replace", "Replace text in the names, like Blender's batch rename"),
    ], default='INDEX')
    scope: EnumProperty(name="Maps", items=[
        ('SELECTED', "Selected", "Only the highlighted UV map"),
        ('ALL', "All", "Every UV map"),
    ], default='ALL')
    find: StringProperty(name="Find")
    replace: StringProperty(name="Replace")
    case_sensitive: BoolProperty(
        name="Case Sensitive",
        description="Match upper and lower case exactly; off, \"uv\" also finds \"UV\"",
        default=True,
    )


class COCOUVS_PT_rename(Panel):
    """Opened as a popover under the pen button, like CocoBackup's menu."""
    bl_idname = "COCOUVS_PT_rename"
    bl_label = "Rename UV Maps"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    def draw(self, context):
        settings = context.window_manager.cocouvs_rename
        layout = self.layout
        layout.label(text="Rename UV Maps", icon='GREASEPENCIL')
        layout.row().prop(settings, "scope", expand=True)
        layout.row().prop(settings, "mode", expand=True)
        col = layout.column()
        # By Index keeps the box: what is typed there is the base name
        # (empty = "map"). Replace does not apply, so it is greyed out.
        col.prop(settings, "find", text="Name" if settings.mode == 'INDEX' else "Find")
        sub = col.column()
        sub.enabled = settings.mode == 'FIND'
        sub.prop(settings, "replace")
        sub.prop(settings, "case_sensitive")
        row = layout.row()
        row.scale_y = 1.3
        row.operator("cocouvs.uv_rename", text="Rename", icon='CHECKMARK')


class COCOUVS_OT_uv_rename(Operator):
    bl_idname = "cocouvs.uv_rename"
    bl_label = "Rename UV Maps"
    bl_description = ("Rename UV maps on every selected object: by position (map1, map2, ...) "
                      "or with Find/Replace")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(len(me.uv_layers) for me in common.target_meshes(context))

    @staticmethod
    def _new_name(settings, index, name):
        if settings.mode == 'INDEX':
            return f"{settings.find.strip() or RENAME_BASE}{index + 1}"
        return _find_replace(name, settings.find, settings.replace, settings.case_sensitive)

    def execute(self, context):
        settings = context.window_manager.cocouvs_rename
        meshes = common.target_meshes(context)
        chosen = current_name(context)
        new_chosen = None
        renamed = 0
        for me in meshes:
            old = [layer.name for layer in me.uv_layers]
            new = [self._new_name(settings, i, n) if (settings.scope == 'ALL' or n == chosen) else n
                   for i, n in enumerate(old)]
            new = [n or o for n, o in zip(new, old)]      # never an empty name
            if chosen in old and new_chosen is None:
                new_chosen = new[old.index(chosen)]
            if old == new:
                continue
            # Two passes through temporary names, so "map2" -> "map1" cannot
            # collide with a map still called "map1".
            temps = []
            for name in old:
                temp = _unique_name([me], "__cocouvs_rename")
                common.rename_uv_map(me, name, temp)
                temps.append(temp)
            for temp, name in zip(temps, new):
                common.rename_uv_map(me, temp, name)
            renamed += 1
        if new_chosen is not None:
            set_chosen(new_chosen)
        sync_list(context)
        objects = "mesh" if renamed == 1 else "meshes"
        self.report({'INFO'}, f"Renamed UV maps on {renamed} {objects}")
        return {'FINISHED'}


class COCOUVS_OT_uv_map_mismatch(Operator):
    """The red N/total box on a row whose map is still active on some objects.
    It does nothing; it exists to be a red widget and to explain itself."""

    bl_idname = "cocouvs.uv_map_mismatch"
    bl_label = "Objects on another UV map"
    bl_options = {'INTERNAL'}

    name: StringProperty()
    chosen: StringProperty()
    count: bpy.props.IntProperty()
    total: bpy.props.IntProperty()

    @classmethod
    def description(cls, context, properties):
        objects = "object is" if properties.count == 1 else "objects are"
        return (f"{properties.count} of {properties.total} selected {objects} still on "
                f"\"{properties.name}\": they have no UV map called \"{properties.chosen}\"")

    def execute(self, context):
        return {'CANCELLED'}


# --- The list ----------------------------------------------------------------

# Filled by the panel right before template_list(), which draws every row
# during that call, so this is worked out once per redraw, not per row.
_row_state = ({}, 0, None)


def set_row_state(counts, total, chosen):
    global _row_state
    _row_state = (counts, total, chosen)


class COCOUVS_UL_uv_maps(UIList):
    """One row per UV map name across the selected objects: editable name
    (double-click renames it everywhere), N/total objects with it active, and
    the camera toggle. A row still active on some objects that is not the
    chosen one is drawn red."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            counts, total, chosen = _row_state
            active_on = counts.get(item.name, 0)
            stragglers = active_on > 0 and item.name != chosen
            main = layout.row()
            main.alert = stragglers
            main.prop(item, "name", text="", emboss=False, icon='GROUP_UVS')
            if stragglers:
                # A solid red box. `alert` on emboss-less text is only a faint
                # tint in some themes (measured on the user's: (0.89, 0.80,
                # 0.84) against (0.91, 0.93, 0.95)); an embossed widget turns
                # properly red in any theme. The button only explains itself.
                box = main.row(align=True)
                box.alert = True
                box.ui_units_x = 2.2
                info = box.operator("cocouvs.uv_map_mismatch", text=f"{active_on}/{total}")
                info.name = item.name
                info.chosen = chosen or ""
                info.count = active_on
                info.total = total
            elif total > 1 and active_on:
                count = main.row()
                count.alignment = 'RIGHT'
                count.label(text=f"{active_on}/{total}")
            icon = 'RESTRICT_RENDER_OFF' if item.render else 'RESTRICT_RENDER_ON'
            layout.prop(item, "render", text="", icon=icon, emboss=False)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='GROUP_UVS')


@bpy.app.handlers.persistent
def _load_post(*_args):
    set_chosen(None)


classes = (
    COCOUVS_UVMapItem,
    COCOUVS_RenameSettings,
    COCOUVS_PT_rename,
    COCOUVS_OT_uv_add,
    COCOUVS_OT_uv_remove,
    COCOUVS_OT_uv_move,
    COCOUVS_OT_uv_rename,
    COCOUVS_OT_uv_map_mismatch,
    COCOUVS_UL_uv_maps,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.cocouvs_uv_list = CollectionProperty(type=COCOUVS_UVMapItem)
    bpy.types.WindowManager.cocouvs_rename = bpy.props.PointerProperty(type=COCOUVS_RenameSettings)
    bpy.app.handlers.load_post.append(_load_post)


def unregister():
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    del bpy.types.WindowManager.cocouvs_uv_list
    del bpy.types.WindowManager.cocouvs_rename
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
