"""Which meshes a command acts on, and how each kind of layer is read and
written. No Blender classes are registered here.

Four kinds of layer, each read and written its own way:

- VGROUP: vertex groups (stored on the mesh, reached through the object);
- UV:     UV maps;
- COLOR:  color attributes (Vertex or Face Corner, Color or Byte Color);
- ATTR:   every other visible attribute (UV maps and color attributes are
          attributes too; they are left out here so none shows twice).

They are shown in two lists (LISTS): Vertex Groups, and Attributes, which
holds UV maps, then color attributes, then the rest, each row remembering its
kind. The user found four lists too fragmented (2026-10-02).

A layer is identified by a key (name, domain, data_type). Vertex groups and
UV maps have no domain or type in the key, so two meshes with a "Group" are
one row; an attribute called "weight" that is a Float on one mesh and an
Integer on another is two rows.
"""

import time

import bpy

KINDS = ('VGROUP', 'UV', 'COLOR', 'ATTR')
# List -> the kinds it shows, in order.
LISTS = {'VGROUP': ('VGROUP',), 'DATA': ('UV', 'COLOR', 'ATTR')}


def list_of(kind):
    return 'VGROUP' if kind == 'VGROUP' else 'DATA'


def list_rows(list_id, objects):
    """[(name, domain, data_type, count, locked, kind)] for one list."""
    return [(*row, kind) for kind in LISTS[list_id] for row in union(kind, objects)]

MAX_UV_MAPS = 8

COLOR_DOMAINS = {'POINT', 'CORNER'}
COLOR_TYPES = {'FLOAT_COLOR', 'BYTE_COLOR'}

# Point, Edge, Face, Corner: the Attributes list is sorted this way, then by name.
DOMAIN_ORDER = {'POINT': 0, 'EDGE': 1, 'FACE': 2, 'CORNER': 3}
DOMAIN_LABELS = {'POINT': "Vertex", 'EDGE': "Edge", 'FACE': "Face", 'CORNER': "Face Corner"}

# Custom normals are an attribute on 5.2 (CORNER / INT16_2D, verified), but a
# raw zero-filled copy of one is not the same as Blender's own "Add Custom
# Normals Data", so filling it goes through Blender's operator.
CUSTOM_NORMAL = "custom_normal"


def type_label(data_type):
    items = bpy.types.Attribute.bl_rna.properties["data_type"].enum_items
    item = items.get(data_type)
    return item.name if item is not None else data_type


# --- Which objects -----------------------------------------------------------

def _editing(view_layer):
    """Mesh objects in Edit Mode. Blender keeps objects in Edit Mode only
    alongside an active one that is, so outside Edit Mode this costs nothing."""
    active = view_layer.objects.active
    if active is None or active.mode != 'EDIT':
        return []
    return [o for o in view_layer.objects if o.type == 'MESH' and o.mode == 'EDIT']


def selected_objects(context=None):
    """The active object plus every selected one, and anything in Edit Mode,
    each once, active first. Mesh objects only."""
    view_layer = (context or bpy.context).view_layer
    candidates = []
    active = view_layer.objects.active
    if active is not None:
        candidates.append(active)
    candidates.extend(view_layer.objects.selected)
    candidates.extend(_editing(view_layer))
    return list(dict.fromkeys(o for o in candidates
                              if o is not None and o.type == 'MESH' and o.data is not None))


def unique_meshes(objects):
    """One object per mesh data block, order kept. Linked duplicates share a
    mesh, and with it its vertex groups and attributes (verified on 5.2), so
    they count once."""
    result = []
    seen = set()
    for obj in objects:
        if obj.data not in seen:
            seen.add(obj.data)
            result.append(obj)
    return result


def targets(context=None):
    """The objects every command works through: one per mesh."""
    return unique_meshes(selected_objects(context))


def edit_targets(context=None):
    """Objects in Edit Mode, one per mesh."""
    return unique_meshes(_editing((context or bpy.context).view_layer))


# --- Reading layers ----------------------------------------------------------

def is_hidden(attr):
    """Blender's own internal layers, and any whose name starts with ".":
    add-ons use that for their private data (CocoUVs' `.cocouvs_trims_undo`
    and `.cocouvs_done.*`). `is_internal` alone is not enough: it is False for
    an add-on's ".name" attribute (checked on 5.2), so Blender's own list
    shows those."""
    return attr.is_internal or attr.name.startswith(".")


def is_color(attr):
    return (not is_hidden(attr) and attr.domain in COLOR_DOMAINS
            and attr.data_type in COLOR_TYPES)


def entries(kind, obj):
    """[(name, domain, data_type, locked)] of this kind on one object's mesh.
    `locked`: Blender will not let it be removed or renamed (`position`)."""
    me = obj.data
    if kind == 'VGROUP':
        return [(g.name, "", "", False) for g in obj.vertex_groups]
    if kind == 'UV':
        return [(layer.name, "", "", False) for layer in me.uv_layers]
    if kind == 'COLOR':
        return [(a.name, a.domain, a.data_type, False) for a in me.attributes if is_color(a)]
    uv_names = {layer.name for layer in me.uv_layers}
    return [(a.name, a.domain, a.data_type, a.is_required) for a in me.attributes
            if not is_hidden(a) and a.name not in uv_names and not is_color(a)]


def union(kind, objects):
    """Every layer of this kind on any of these objects, each once:
    [(name, domain, data_type, count, locked)], `count` = how many of the
    objects have it. In order of first appearance (the active object's own
    order first); attributes sorted by domain, then name."""
    order = []
    counts = {}
    locked = {}
    for obj in objects:
        for name, domain, data_type, is_locked in entries(kind, obj):
            key = (name, domain, data_type)
            if key not in counts:
                order.append(key)
                counts[key] = 0
                locked[key] = False
            counts[key] += 1
            locked[key] = locked[key] or is_locked
    if kind == 'ATTR':
        order.sort(key=lambda k: (DOMAIN_ORDER.get(k[1], 99), k[0].lower()))
    return [(*key, counts[key], locked[key]) for key in order]


def find(kind, obj, name, domain="", data_type=""):
    """The layer behind a row on one object, or None."""
    me = obj.data
    if kind == 'VGROUP':
        return obj.vertex_groups.get(name)
    if kind == 'UV':
        return me.uv_layers.get(name)
    attr = me.attributes.get(name)
    if attr is None or attr.domain != domain or attr.data_type != data_type:
        return None
    return attr


def name_taken(obj, name):
    """Blender warns about a vertex group and an attribute sharing a name (its
    "Name collisions" label), and UV maps are attributes, so one name check
    covers all four lists."""
    return obj.vertex_groups.get(name) is not None or obj.data.attributes.get(name) is not None


def unique_name(objects, base):
    """`base`, or base.001, base.002 ..., free on every one of these objects,
    so a new layer gets the same name everywhere."""
    def free(name):
        return not any(name_taken(obj, name) for obj in objects)

    if free(base):
        return base
    i = 1
    while not free(f"{base}.{i:03d}"):
        i += 1
    return f"{base}.{i:03d}"


# --- Writing layers ----------------------------------------------------------

def create(kind, obj, name, domain="", data_type=""):
    """Add a layer called `name` to one object's mesh. Returns whether it
    landed under exactly that name."""
    me = obj.data
    if name_taken(obj, name):
        return False
    # Blender makes a new vertex group (and some attributes) the active one.
    # Fill Missing should not move anyone's active layer; + sets it itself.
    active = _active_state(kind, obj)
    if kind == 'VGROUP':
        obj.vertex_groups.new(name=name)
    elif kind == 'UV':
        if len(me.uv_layers) >= MAX_UV_MAPS:
            return False
        # Copies the active map's UVs (a default unwrap when there is none).
        # Returns None in Edit Mode though it adds the layer (verified on 5.2),
        # hence the look-up below.
        me.uv_layers.new(name=name, do_init=True)
    elif kind == 'COLOR':
        me.color_attributes.new(name, data_type, domain)
    elif name == CUSTOM_NORMAL and not me.has_custom_normals:
        add_custom_normals(obj)
    else:
        me.attributes.new(name, data_type, domain)
    _restore_active(kind, obj, active)
    return find(kind, obj, name, domain, data_type) is not None


def _active_state(kind, obj):
    me = obj.data
    if kind == 'VGROUP':
        return obj.vertex_groups.active_index
    if kind == 'UV':
        return me.uv_layers.active_index
    if kind == 'COLOR':
        return me.color_attributes.active_color_name
    return me.attributes.active.name if me.attributes.active is not None else None


def _restore_active(kind, obj, state):
    me = obj.data
    if kind == 'VGROUP':
        if state >= 0 and obj.vertex_groups.active_index != state:
            obj.vertex_groups.active_index = state
    elif kind == 'UV':
        if state >= 0 and me.uv_layers.active_index != state:
            me.uv_layers.active_index = state
    elif kind == 'COLOR':
        if state and me.color_attributes.active_color_name != state:
            me.color_attributes.active_color_name = state
    elif state is not None:
        attr = me.attributes.get(state)
        if attr is not None and (me.attributes.active is None or me.attributes.active.name != state):
            me.attributes.active = attr


def remove(kind, obj, name, domain="", data_type=""):
    """Remove one layer from one object's mesh. Returns whether it went."""
    layer = find(kind, obj, name, domain, data_type)
    if layer is None:
        return False
    if kind == 'VGROUP':
        obj.vertex_groups.remove(layer)
    elif kind == 'UV':
        obj.data.uv_layers.remove(layer)
    else:
        if layer.is_required:
            return False
        obj.data.attributes.remove(layer)
    return True


def rename(kind, obj, old, new, domain="", data_type=""):
    """Rename one layer. Refuses (returns False) when the new name is already
    used on that mesh: Blender would quietly make it "name.001" there and the
    meshes would drift apart."""
    layer = find(kind, obj, old, domain, data_type)
    if layer is None or name_taken(obj, new):
        return False
    if kind in {'COLOR', 'ATTR'} and layer.is_required:
        return False
    layer.name = new
    return True


def add_custom_normals(obj):
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.mesh.customdata_custom_splitnormals_add()


# --- Active and render layers ------------------------------------------------

def is_active(kind, obj, name, domain="", data_type=""):
    me = obj.data
    if kind == 'VGROUP':
        group = obj.vertex_groups.active
        return group is not None and group.name == name
    if kind == 'UV':
        layer = me.uv_layers.active
        return layer is not None and layer.name == name
    if kind == 'COLOR':
        return me.color_attributes.active_color_name == name
    attr = me.attributes.active
    return attr is not None and attr.name == name


def set_active(kind, obj, name, domain="", data_type=""):
    layer = find(kind, obj, name, domain, data_type)
    if layer is None:
        return
    me = obj.data
    if kind == 'VGROUP':
        if obj.vertex_groups.active_index != layer.index:
            obj.vertex_groups.active_index = layer.index
    elif kind == 'UV':
        index = me.uv_layers.find(name)
        if me.uv_layers.active_index != index:
            me.uv_layers.active_index = index
    elif kind == 'COLOR':
        if me.color_attributes.active_color_name != name:
            me.color_attributes.active_color_name = name
    elif me.attributes.active is None or me.attributes.active.name != name:
        me.attributes.active = layer


def is_render(kind, obj, name):
    me = obj.data
    if kind == 'UV':
        layer = me.uv_layers.get(name)
        return layer is not None and layer.active_render
    return me.color_attributes.default_color_name == name


def set_render(kind, obj, name, domain="", data_type=""):
    if find(kind, obj, name, domain, data_type) is None:
        return
    me = obj.data
    if kind == 'UV':
        layer = me.uv_layers.get(name)
        if not layer.active_render:
            layer.active_render = True
    elif me.color_attributes.default_color_name != name:
        me.color_attributes.default_color_name = name


# --- What the panel shows, cached ----------------------------------------------

# The Properties editor redraws on every step of a viewport G drag (counted on
# 5.2: 21 draws for 20 mouse moves), and working out the rows costs about
# 34 ms with 1000 meshes selected, so the panel draws from a snapshot.
# It is rebuilt when:
# - something other than an object moving reaches the depsgraph (selection,
#   active object, adding/removing/renaming layers: lists._depsgraph_post);
# - undo, redo, file load, or one of this add-on's own changes (invalidate());
# - it is older than MAX_AGE. Renaming an attribute (in Blender's own
#   Attributes panel too) sends no depsgraph update at all (verified on 5.2),
#   so without this it would not show until something else changed. Not
#   while objects are being moved: that would rebuild it mid-drag.
# Commands never use it: they read the meshes themselves.
MAX_AGE = 0.5
MOVING_HOLD = 0.3

_generation = 0
_snapshot = None
_moving_until = 0.0


def note_moving():
    """Objects are being moved (transform-only depsgraph updates)."""
    global _moving_until
    _moving_until = time.monotonic() + MOVING_HOLD


class Snapshot:
    __slots__ = ("objects", "total", "rows", "render", "custom_normals")


def invalidate():
    global _generation
    _generation += 1


def _render_map(kind, objects):
    """{name: renders with it on every mesh that has it} for UV maps and color
    attributes, worked out in one pass."""
    holders = {}
    renders = {}
    for obj in objects:
        me = obj.data
        if kind == 'UV':
            pairs = [(layer.name, layer.active_render) for layer in me.uv_layers]
        else:
            default = me.color_attributes.default_color_name
            pairs = [(a.name, a.name == default) for a in me.attributes if is_color(a)]
        for name, is_render in pairs:
            holders[name] = holders.get(name, 0) + 1
            renders[name] = renders.get(name, 0) + is_render
    return {name: renders[name] == count for name, count in holders.items()}


def snapshot(context=None):
    """Rows, counts and camera states for every list. Holds no objects, so a
    stale one can show old rows for a moment but never touch freed data."""
    global _snapshot
    now = time.monotonic()
    if (_snapshot is not None and _snapshot[0] == _generation
            and (now - _snapshot[1] < MAX_AGE or now < _moving_until)):
        return _snapshot[2]
    selected = selected_objects(context)
    objects = unique_meshes(selected)
    snap = Snapshot()
    snap.objects = len(selected)
    snap.total = len(objects)
    snap.rows = {list_id: list_rows(list_id, objects) for list_id in LISTS}
    snap.render = {kind: _render_map(kind, objects) for kind in ('UV', 'COLOR')}
    snap.custom_normals = sum(obj.data.has_custom_normals for obj in objects)
    _snapshot = (_generation, now, snap)
    return snap


def redraw(context=None):
    context = context or bpy.context
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'PROPERTIES', 'VIEW_3D'}:
                area.tag_redraw()


def undo_push(message):
    """Changes made from the lists' own fields (rename, row click, camera) are
    writes to WindowManager properties, which Blender never records in undo
    history, so they push their own step. They also changed what the panel
    shows, so the snapshot is rebuilt."""
    invalidate()
    try:
        bpy.ops.ed.undo_push(message=message)
    except RuntimeError:
        pass
