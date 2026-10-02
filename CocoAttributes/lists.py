"""The two lists (Vertex Groups, Attributes): the rows they draw, keeping those rows up to date, and what
a row's own fields do (rename, click, camera).

A UIList can only draw a real collection, so each list's rows live in a
WindowManager collection (never saved into the .blend). The panel draw works
out what the rows should be; Blender forbids writing ID data from a draw call,
so when they differ it schedules a one-shot timer that rewrites them. Every
operator calls sync() itself before reading the rows.

Each row has two separate states:

- **ticked** (`use`, the checkbox): picked for -, Fill Missing, and the Edit
  Mode buttons. Several rows can be ticked; ticks survive a rewrite.
- **highlighted**: the layer that is active on the active object, exactly as
  in Blender's own lists. Clicking a name makes that layer active on every
  selected mesh that has it, and ticks that row alone.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup, UIList

from . import common

COLLECTIONS = {
    'VGROUP': "cocoattrs_vgroups",
    'DATA': "cocoattrs_data",
}
INDEX_PROPS = {list_id: name + "_index" for list_id, name in COLLECTIONS.items()}

# What one rename last did, shown under its list until the next one.
# {list: message}. Kept in Python, never saved.
rename_notes = {}

_syncing = False


def items(list_id, context=None):
    return getattr((context or bpy.context).window_manager, COLLECTIONS[list_id])


def key(item):
    return (item.stored_name, item.domain, item.data_type, item.kind)


def ticked(list_id, context=None):
    """The ticked rows: [(name, domain, data_type, count, locked, kind)]."""
    return [(item.stored_name, item.domain, item.data_type, item.count, item.locked, item.kind)
            for item in items(list_id, context) if item.use]


def _signature(collection):
    return [(item.stored_name, item.domain, item.data_type, item.count, item.locked, item.kind)
            for item in collection]


def sync(list_id, context=None):
    """Rewrite one list's rows to match the selected meshes. Ticks follow
    their row. Must not run from a draw call."""
    global _syncing
    context = context or bpy.context
    rows = common.list_rows(list_id, common.targets(context))
    collection = items(list_id, context)
    if _signature(collection) == rows:
        common.invalidate()
        return
    was_ticked = {key(item) for item in collection if item.use}
    _syncing = True
    try:
        collection.clear()
        for name, domain, data_type, count, locked, kind in rows:
            item = collection.add()
            item.kind = kind
            item.name = name
            item.stored_name = name
            item.domain = domain
            item.data_type = data_type
            item.count = count
            item.locked = locked
            item.use = (name, domain, data_type, kind) in was_ticked and not locked
    finally:
        _syncing = False
    common.invalidate()
    common.redraw(context)


def sync_all(context=None):
    for list_id in common.LISTS:
        sync(list_id, context)


def tick_only(list_id, row_key, context=None):
    """Tick one row and untick the rest. Writes a flag only when it changes.
    `row_key` = (name, domain, data_type, kind)."""
    for item in items(list_id, context):
        want = key(item) == row_key
        if item.use != want:
            item.use = want


def _sync_timer():
    try:
        sync_all()
    except Exception:
        import traceback
        traceback.print_exc()
    return None


def request_sync(list_id, rows, context):
    """Called from the panel draw with what the rows should be: schedule
    sync_all() if this list is stale."""
    if _signature(items(list_id, context)) != rows and not bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.register(_sync_timer, first_interval=0.0)


# --- What a row's fields do --------------------------------------------------

def _set_name_quietly(item, name):
    global _syncing
    _syncing = True
    try:
        item.name = name
    finally:
        _syncing = False


def _name_update(self, context):
    """Renaming a row renames that layer on every selected mesh that has it.
    A mesh that already uses the new name is left alone and counted."""
    if _syncing:
        return
    old, new = self.stored_name, self.name
    if old == new:
        return
    if not new.strip() or self.locked:
        _set_name_quietly(self, old)
        return
    renamed = skipped = 0
    for obj in common.targets(context):
        if common.find(self.kind, obj, old, self.domain, self.data_type) is None:
            continue
        if common.rename(self.kind, obj, old, new, self.domain, self.data_type):
            renamed += 1
        else:
            skipped += 1
    if skipped:
        meshes = "mesh" if skipped == 1 else "meshes"
        rename_notes[common.list_of(self.kind)] = (f"\"{new}\" already exists on {skipped} {meshes}: "
                                   f"\"{old}\" kept its name there")
    else:
        rename_notes.pop(common.list_of(self.kind), None)
    if not renamed:
        _set_name_quietly(self, old)
        return
    # The row now stands for the new name, so its tick stays with it when the
    # list is rewritten.
    self.stored_name = new
    common.undo_push("Rename")


def _render_get(self):
    if self.kind not in {'UV', 'COLOR'}:
        return False
    # Drawn once per row on every redraw: read from the snapshot.
    return common.snapshot().render[self.kind].get(self.stored_name, False)


def _render_set(self, value):
    """The camera: render with this layer on every mesh that has it. Like
    Blender's own camera it can be moved, not switched off."""
    if not value or self.kind not in {'UV', 'COLOR'}:
        return
    for obj in common.targets():
        common.set_render(self.kind, obj, self.stored_name, self.domain, self.data_type)
    common.undo_push("Set Render")


class COCOATTRS_Item(PropertyGroup):
    kind: StringProperty()
    name: StringProperty(name="Name", update=_name_update)
    # The name the layer has on the meshes; `name` is what the field shows.
    stored_name: StringProperty()
    domain: StringProperty()
    data_type: StringProperty()
    count: IntProperty()
    locked: BoolProperty()
    use: BoolProperty(
        name="Ticked",
        description="Pick this row for Remove, Fill Missing and the Edit Mode buttons",
    )
    render: BoolProperty(
        name="Render",
        description="Render with this one on every selected mesh that has it",
        get=_render_get,
        set=_render_set,
    )


# {list: key of the row last clicked}. The Attributes list mixes kinds, and a
# mesh has an active UV map, an active color attribute and an active
# attribute at once, so the highlight follows the last click while that layer
# is still active on the active object. Python-only, never saved.
_clicked = {}


def _index_get(list_id):
    def get(self):
        obj = bpy.context.object
        collection = getattr(self, COLLECTIONS[list_id])
        if obj is None or obj.type != 'MESH':
            return -1
        clicked = _clicked.get(list_id)
        fallback = -1
        for i, item in enumerate(collection):
            if not common.is_active(item.kind, obj, item.stored_name, item.domain, item.data_type):
                continue
            if key(item) == clicked:
                return i
            if fallback == -1:
                fallback = i
        # Nothing clicked yet (or no longer active): the first active row,
        # which in Attributes is the active UV map.
        return fallback
    return get


def _index_set(list_id):
    def set_(self, value):
        """A click on a row's name: that layer becomes active on every selected
        mesh that has it, and the row is the only one ticked."""
        collection = getattr(self, COLLECTIONS[list_id])
        if not 0 <= value < len(collection):
            return
        item = collection[value]
        context = bpy.context
        for obj in common.targets(context):
            common.set_active(item.kind, obj, item.stored_name, item.domain, item.data_type)
        _clicked[list_id] = key(item)
        if not item.locked:
            tick_only(list_id, key(item), context)
        common.undo_push("Set Active")
    return set_


# --- The list ----------------------------------------------------------------

# How many meshes the rows count against. The panel sets it right before
# template_list(), which draws every row during that call.
_total = 0


def set_total(total):
    global _total
    _total = total


class COCOATTRS_UL_items(UIList):
    """One row per layer across the selected meshes: tick box (a lock for one
    Blender will not remove), an icon for UV maps and color attributes, name
    (double-click renames it everywhere), what it is, how many meshes have
    it, and the camera for UV maps and color attributes."""

    ICONS = {'UV': 'GROUP_UVS', 'COLOR': 'GROUP_VCOL'}

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        total = _total
        row = layout.row(align=True)
        if item.locked:
            row.label(text="", icon='LOCKED')
            row.label(text=item.name)
        else:
            row.prop(item, "use", text="")
            kind_icon = self.ICONS.get(item.kind)
            if kind_icon:
                row.prop(item, "name", text="", emboss=False, icon=kind_icon)
            else:
                row.prop(item, "name", text="", emboss=False)

        # Each label gets its own right-aligned row, one level deep: a row
        # nested inside a right-aligned row came out with no width in a wide
        # Properties editor, and its "2/2" vanished (seen on 5.2).
        if item.kind != 'VGROUP':
            info = row.row(align=True)
            info.alignment = 'RIGHT'
            info.active = False
            if item.kind == 'UV':
                info.label(text="UV Map")
            else:
                domain = common.DOMAIN_LABELS.get(item.domain, item.domain)
                info.label(text=f"{domain} · {common.type_label(item.data_type)}")
        if total > 1:
            count = row.row(align=True)
            count.alignment = 'RIGHT'
            if item.count < total:
                # An icon, not `alert`: red on emboss-less text is a faint
                # tint in some themes (see "Add-on overlays and UI testing" in the vault).
                count.label(text=f"{item.count}/{total}", icon='ERROR')
            else:
                count.active = False
                count.label(text=f"{item.count}/{total}")

        if item.kind in {'UV', 'COLOR'}:
            icon = 'RESTRICT_RENDER_OFF' if item.render else 'RESTRICT_RENDER_ON'
            layout.prop(item, "render", text="", icon=icon, emboss=False)
        elif item.kind == 'ATTR':
            # Same width as the camera, so the counts line up down the list.
            layout.label(text="", icon='BLANK1')


@bpy.app.handlers.persistent
def _load_post(*_args):
    rename_notes.clear()
    common.invalidate()


@bpy.app.handlers.persistent
def _undo_post(*_args):
    common.invalidate()


@bpy.app.handlers.persistent
def _depsgraph_post(scene, depsgraph):
    """Rebuild the panel's snapshot on anything but objects moving. A G drag
    sends only transform updates of the moved objects (logged on 5.2), and
    the Properties editor redraws on every step of it; a selection change
    arrives as a bare Scene update, a layer added or renamed as a geometry or
    shading update. Persistent, or Blender drops it at the first File > Open
    (see "Add-on registration and properties" in the vault)."""
    for update in depsgraph.updates:
        if not (update.is_updated_transform and not update.is_updated_geometry
                and not update.is_updated_shading and isinstance(update.id, bpy.types.Object)):
            common.invalidate()
            return
    if depsgraph.updates:
        common.note_moving()


_handlers = (
    (bpy.app.handlers.load_post, _load_post),
    (bpy.app.handlers.undo_post, _undo_post),
    (bpy.app.handlers.redo_post, _undo_post),
    (bpy.app.handlers.depsgraph_update_post, _depsgraph_post),
)

classes = (
    COCOATTRS_Item,
    COCOATTRS_UL_items,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    for kind, name in COLLECTIONS.items():
        setattr(wm, name, CollectionProperty(type=COCOATTRS_Item))
        setattr(wm, INDEX_PROPS[kind], IntProperty(get=_index_get(kind), set=_index_set(kind)))
    for handlers, fn in _handlers:
        handlers.append(fn)


def unregister():
    for handlers, fn in _handlers:
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    wm = bpy.types.WindowManager
    for kind, name in COLLECTIONS.items():
        delattr(wm, INDEX_PROPS[kind])
        delattr(wm, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
