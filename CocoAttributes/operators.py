"""What the list buttons do. Every command works on every selected mesh.

One operator per button: CocoPies' "Add to CocoPies" keeps only a button's
operator name, not settings passed to it (see "One operator per button" in
"Add-on registration and properties", in the vault). The shared code is a
mixin with the list as a class attribute (`list_id`); each button is a small
subclass of it. A row of the Attributes list can be a UV map, a color
attribute or an attribute, so the commands go row by row, each with its own
kind.
"""

import bmesh
import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from . import common, lists

LABELS = {
    'VGROUP': ("vertex group", "vertex groups"),
    'UV': ("UV map", "UV maps"),
    'COLOR': ("color attribute", "color attributes"),
    'ATTR': ("attribute", "attributes"),
}
LIST_LABELS = {'VGROUP': LABELS['VGROUP'], 'DATA': ("layer", "layers")}


def _plural(labels, n):
    one, many = labels
    return f"{n} {one if n == 1 else many}"


def _meshes(n):
    return f"{n} {'mesh' if n == 1 else 'meshes'}"


def _finish_add(kind, context, name, domain, data_type, added, skipped, report):
    list_id = common.list_of(kind)
    lists.sync(list_id, context)
    lists.tick_only(list_id, (name, domain, data_type, kind), context)
    if not added:
        report({'WARNING'}, f"\"{name}\" could not be added: every selected mesh already uses the name"
               + (f" or has {common.MAX_UV_MAPS} UV maps" if kind == 'UV' else ""))
        return {'CANCELLED'}
    for obj in common.targets(context):
        common.set_active(kind, obj, name, domain, data_type)
    message = f"Added \"{name}\" to {_meshes(added)}"
    if skipped:
        message += f", skipped {skipped} (name already used" + \
            (f" or {common.MAX_UV_MAPS} UV maps" if kind == 'UV' else "") + ")"
    report({'WARNING'} if skipped else {'INFO'}, message)
    return {'FINISHED'}


# --- + -----------------------------------------------------------------------

class COCOATTRS_OT_add_vertex_group(Operator):
    """+ for vertex groups: the same free name on every mesh, so they stay
    one row (a plain "Group" would become "Group.001" on a mesh that already
    has one)."""
    bl_idname = "cocoattrs.add_vertex_group"
    bl_label = "Add Vertex Group"
    bl_description = "Add an empty vertex group, with the same name, to every selected mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.snapshot(context).total > 0

    def execute(self, context):
        objects = common.targets(context)
        name = common.unique_name(objects, "Group")
        added = sum(common.create('VGROUP', obj, name) for obj in objects)
        return _finish_add('VGROUP', context, name, "", "", added, len(objects) - added, self.report)


def _attribute_type_items():
    return [(item.identifier, item.name, item.description)
            for item in bpy.types.Attribute.bl_rna.properties["data_type"].enum_items]


# Kept at module level: Blender needs enum items to stay alive.
ATTRIBUTE_TYPES = _attribute_type_items()
ATTRIBUTE_DOMAINS = [
    ('POINT', "Vertex", "One value per vertex"),
    ('EDGE', "Edge", "One value per edge"),
    ('FACE', "Face", "One value per face"),
    ('CORNER', "Face Corner", "One value per face corner"),
]
COLOR_DOMAINS = [
    ('POINT', "Vertex", "One color per vertex"),
    ('CORNER', "Face Corner", "One color per face corner"),
]
COLOR_TYPES = [
    ('FLOAT_COLOR', "Color", "32-bit floating point values"),
    ('BYTE_COLOR', "Byte Color", "8-bit values, smaller in memory"),
]
ADD_KINDS = [
    ('ATTR', "Attribute", "A value per vertex, edge, face or face corner"),
    ('COLOR', "Color Attribute", "A color per vertex or face corner"),
    ('UV', "UV Map", "Copied from each mesh's active UV map"),
]
BASE_NAMES = {'ATTR': "Attribute", 'COLOR': "Color", 'UV': "UVMap"}


def _add_kind_update(self, context):
    """Switching the type swaps a default name for that type's default, and
    leaves a typed one alone."""
    stripped = self.name.rsplit(".", 1)[0] if self.name[-4:-3] == "." else self.name
    if stripped in BASE_NAMES.values():
        self.name = common.unique_name(common.targets(context), BASE_NAMES[self.kind])


class COCOATTRS_OT_add_attribute(Operator):
    """+ for the Attributes list: asks for name and type (attribute, color
    attribute or UV map), with domain and data type where they apply, then
    adds it to every selected mesh."""
    bl_idname = "cocoattrs.add_attribute"
    bl_label = "Add Attribute"
    bl_description = ("Add an attribute, color attribute or UV map, with the same name, "
                      "to every selected mesh")
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="Attribute")
    kind: EnumProperty(name="Type", items=ADD_KINDS, default='ATTR', update=_add_kind_update)
    # One pair per type: a dynamic enum switching its items under a stored
    # value can leave it pointing past the end of the new list.
    attr_domain: EnumProperty(name="Domain", items=ATTRIBUTE_DOMAINS, default='POINT')
    attr_type: EnumProperty(name="Data Type", items=ATTRIBUTE_TYPES, default=0)
    color_domain: EnumProperty(name="Domain", items=COLOR_DOMAINS, default='POINT')
    color_type: EnumProperty(name="Data Type", items=COLOR_TYPES, default='FLOAT_COLOR')

    @classmethod
    def poll(cls, context):
        return common.snapshot(context).total > 0

    def invoke(self, context, event):
        self.name = common.unique_name(common.targets(context), BASE_NAMES[self.kind])
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "name")
        layout.prop(self, "kind")
        if self.kind == 'ATTR':
            layout.prop(self, "attr_domain")
            layout.prop(self, "attr_type")
        elif self.kind == 'COLOR':
            layout.prop(self, "color_domain")
            layout.prop(self, "color_type")

    def _domain_type(self):
        if self.kind == 'ATTR':
            return self.attr_domain, self.attr_type
        if self.kind == 'COLOR':
            return self.color_domain, self.color_type
        return "", ""

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({'WARNING'}, "Type a name")
            return {'CANCELLED'}
        domain, data_type = self._domain_type()
        objects = common.targets(context)
        added = 0
        for obj in objects:
            try:
                added += common.create(self.kind, obj, name, domain, data_type)
            except RuntimeError as error:
                self.report({'WARNING'}, f"{obj.name}: {error}")
        return _finish_add(self.kind, context, name, domain, data_type,
                           added, len(objects) - added, self.report)


# --- - -----------------------------------------------------------------------

class _Remove:
    bl_options = {'REGISTER', 'UNDO'}
    list_id = 'VGROUP'

    @classmethod
    def poll(cls, context):
        return any(not row[4] for row in lists.ticked(cls.list_id, context))

    def execute(self, context):
        lists.sync(self.list_id, context)
        rows = [row for row in lists.ticked(self.list_id, context) if not row[4]]
        objects = common.targets(context)
        removed = 0
        for name, domain, data_type, _count, _locked, kind in rows:
            for obj in objects:
                try:
                    removed += common.remove(kind, obj, name, domain, data_type)
                except RuntimeError as error:
                    self.report({'WARNING'}, f"{obj.name}: {error}")
        lists.sync(self.list_id, context)
        self.report({'INFO'}, f"Removed {_plural(LIST_LABELS[self.list_id], len(rows))} "
                    f"({removed} in all) from {_meshes(len(objects))}")
        return {'FINISHED'}


class COCOATTRS_OT_remove_vertex_groups(_Remove, Operator):
    bl_idname = "cocoattrs.remove_vertex_groups"
    bl_label = "Remove Vertex Groups"
    bl_description = "Remove the ticked vertex groups from every selected mesh"
    list_id = 'VGROUP'


class COCOATTRS_OT_remove_attributes(_Remove, Operator):
    bl_idname = "cocoattrs.remove_attributes"
    bl_label = "Remove Attributes"
    bl_description = ("Remove the ticked attributes, color attributes and UV maps "
                      "from every selected mesh")
    list_id = 'DATA'


# --- Fill Missing ------------------------------------------------------------

class _FillMissing:
    """For each ticked row that some meshes lack, add it to those meshes:
    same name, and for attributes the same domain and type. What is added is
    empty (a vertex group with no vertices, zero values); a UV map is copied
    from that mesh's active one; custom normals go through Blender's own
    Add Custom Normals Data."""
    bl_options = {'REGISTER', 'UNDO'}
    list_id = 'VGROUP'

    @classmethod
    def poll(cls, context):
        rows = lists.ticked(cls.list_id, context)
        if not rows:
            return False
        total = common.snapshot(context).total
        return any(row[3] < total for row in rows)

    def execute(self, context):
        lists.sync(self.list_id, context)
        objects = common.targets(context)
        added = skipped = 0
        uv_full = False
        for name, domain, data_type, _count, _locked, kind in lists.ticked(self.list_id, context):
            for obj in objects:
                if common.find(kind, obj, name, domain, data_type) is not None:
                    continue
                try:
                    if common.create(kind, obj, name, domain, data_type):
                        added += 1
                    else:
                        skipped += 1
                        uv_full = uv_full or kind == 'UV'
                except RuntimeError as error:
                    skipped += 1
                    self.report({'WARNING'}, f"{obj.name}: {error}")
        lists.sync(self.list_id, context)
        if not added and not skipped:
            self.report({'INFO'}, "Every selected mesh already has them")
            return {'CANCELLED'}
        message = f"Added {added} missing {LIST_LABELS[self.list_id][1 if added != 1 else 0]}"
        if skipped:
            message += (f", skipped {skipped}: the name is already used there by something else"
                        + (f" or the mesh has {common.MAX_UV_MAPS} UV maps" if uv_full else ""))
        self.report({'WARNING'} if skipped else {'INFO'}, message)
        return {'FINISHED'}


class COCOATTRS_OT_fill_missing_vertex_groups(_FillMissing, Operator):
    bl_idname = "cocoattrs.fill_missing_vertex_groups"
    bl_label = "Fill Missing Vertex Groups"
    bl_description = "Add the ticked vertex groups (empty) to the selected meshes that lack them"
    list_id = 'VGROUP'


class COCOATTRS_OT_fill_missing_attributes(_FillMissing, Operator):
    bl_idname = "cocoattrs.fill_missing_attributes"
    bl_label = "Fill Missing Attributes"
    bl_description = ("Add the ticked rows to the selected meshes that lack them: attributes "
                      "with zero values, color attributes black, UV maps copied from the active one")
    list_id = 'DATA'


# --- Tick all / none ---------------------------------------------------------

class _CheckAll:
    """Tick every row, or untick them all when any is ticked."""
    bl_options = {'INTERNAL'}
    list_id = 'VGROUP'

    @classmethod
    def poll(cls, context):
        return len(lists.items(cls.list_id, context)) > 0

    def execute(self, context):
        lists.sync(self.list_id, context)
        collection = lists.items(self.list_id, context)
        want = not any(item.use for item in collection)
        for item in collection:
            value = want and not item.locked
            if item.use != value:
                item.use = value
        return {'FINISHED'}


class COCOATTRS_OT_check_all_vertex_groups(_CheckAll, Operator):
    bl_idname = "cocoattrs.check_all_vertex_groups"
    bl_label = "Tick All Vertex Groups"
    bl_description = "Tick every vertex group, or untick them all if any is ticked"
    list_id = 'VGROUP'


class COCOATTRS_OT_check_all_attributes(_CheckAll, Operator):
    bl_idname = "cocoattrs.check_all_attributes"
    bl_label = "Tick All Attributes"
    bl_description = "Tick every row of the Attributes list, or untick them all if any is ticked"
    list_id = 'DATA'


# --- Edit Mode: Assign / Remove / Select / Deselect ---------------------------

class _EditGroups:
    """Works on the ticked vertex groups, on every mesh in Edit Mode, through
    BMesh: Blender's own buttons only touch the active object, and the old
    N-panel script left and re-entered Edit Mode on every click. Locked
    groups are skipped, as Blender's own Assign does."""
    bl_options = {'REGISTER', 'UNDO'}
    create_missing = False

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and bool(lists.ticked('VGROUP', context))

    def _groups(self, obj, names, need_unlocked):
        """Indices of the ticked groups on this object."""
        indices = []
        for name in names:
            group = obj.vertex_groups.get(name)
            if group is None and self.create_missing and not common.name_taken(obj, name):
                group = obj.vertex_groups.new(name=name)
                self.created += 1
            if group is None:
                continue
            if need_unlocked and group.lock_weight:
                self.locked += 1
                continue
            indices.append(group.index)
        return indices

    def execute(self, context):
        lists.sync('VGROUP', context)
        names = [row[0] for row in lists.ticked('VGROUP', context)]
        self.created = self.locked = 0
        changed = 0
        for obj in common.edit_targets(context):
            me = obj.data
            bm = bmesh.from_edit_mesh(me)
            if self.needs_selection and not any(v.select and not v.hide for v in bm.verts):
                continue
            indices = self._groups(obj, names, self.needs_unlocked)
            if not indices:
                continue
            # Adding a group above can rebuild the edit mesh: fetch it again.
            bm = bmesh.from_edit_mesh(me)
            layer = bm.verts.layers.deform.verify()
            if self.apply(bm, layer, indices, context):
                bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
                changed += 1
        lists.sync('VGROUP', context)
        if self.locked:
            self.report({'WARNING'}, f"Skipped {self.locked} locked vertex group(s)")
        elif self.created:
            self.report({'INFO'}, f"Created {_plural(LABELS['VGROUP'], self.created)} where missing")
        return {'FINISHED'} if changed else {'CANCELLED'}


class COCOATTRS_OT_assign_to_groups(_EditGroups, Operator):
    bl_idname = "cocoattrs.assign_to_groups"
    bl_label = "Assign to Groups"
    bl_description = ("Assign the selected vertices, with the Weight below, to the ticked vertex "
                      "groups on every mesh in Edit Mode. A mesh without the group gets it")
    create_missing = True
    needs_selection = True
    needs_unlocked = True

    def apply(self, bm, layer, indices, context):
        weight = context.scene.tool_settings.vertex_group_weight
        for vert in bm.verts:
            if vert.select and not vert.hide:
                deform = vert[layer]
                for index in indices:
                    deform[index] = weight
        return True


class COCOATTRS_OT_remove_from_groups(_EditGroups, Operator):
    bl_idname = "cocoattrs.remove_from_groups"
    bl_label = "Remove from Groups"
    bl_description = "Remove the selected vertices from the ticked vertex groups on every mesh in Edit Mode"
    needs_selection = True
    needs_unlocked = True

    def apply(self, bm, layer, indices, context):
        for vert in bm.verts:
            if vert.select and not vert.hide:
                deform = vert[layer]
                for index in indices:
                    if index in deform:
                        del deform[index]
        return True


class COCOATTRS_OT_select_group_vertices(_EditGroups, Operator):
    bl_idname = "cocoattrs.select_group_vertices"
    bl_label = "Select Group Vertices"
    bl_description = "Select the vertices in the ticked vertex groups on every mesh in Edit Mode"
    needs_selection = False
    needs_unlocked = False

    def apply(self, bm, layer, indices, context):
        for vert in bm.verts:
            if not vert.hide and any(index in vert[layer] for index in indices):
                vert.select = True
        bm.select_flush(True)
        return True


class COCOATTRS_OT_deselect_group_vertices(_EditGroups, Operator):
    bl_idname = "cocoattrs.deselect_group_vertices"
    bl_label = "Deselect Group Vertices"
    bl_description = "Deselect the vertices in the ticked vertex groups on every mesh in Edit Mode"
    needs_selection = False
    needs_unlocked = False

    def apply(self, bm, layer, indices, context):
        for vert in bm.verts:
            if not vert.hide and any(index in vert[layer] for index in indices):
                vert.select = False
        bm.select_flush(False)
        return True


# --- Custom normals ----------------------------------------------------------

class COCOATTRS_OT_add_custom_normals(Operator):
    bl_idname = "cocoattrs.add_custom_normals"
    bl_label = "Add Custom Normals"
    bl_description = ("Add custom normals data to every selected mesh that has none, "
                      "as Blender's Add Custom Normals Data does for one")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        snap = common.snapshot(context)
        return snap.custom_normals < snap.total

    def execute(self, context):
        added = 0
        for obj in common.targets(context):
            if not obj.data.has_custom_normals:
                common.add_custom_normals(obj)
                added += obj.data.has_custom_normals
        lists.sync('DATA', context)
        self.report({'INFO'}, f"Added custom normals to {_meshes(added)}")
        return {'FINISHED'}


classes = (
    COCOATTRS_OT_add_vertex_group,
    COCOATTRS_OT_add_attribute,
    COCOATTRS_OT_remove_vertex_groups,
    COCOATTRS_OT_remove_attributes,
    COCOATTRS_OT_fill_missing_vertex_groups,
    COCOATTRS_OT_fill_missing_attributes,
    COCOATTRS_OT_check_all_vertex_groups,
    COCOATTRS_OT_check_all_attributes,
    COCOATTRS_OT_assign_to_groups,
    COCOATTRS_OT_remove_from_groups,
    COCOATTRS_OT_select_group_vertices,
    COCOATTRS_OT_deselect_group_vertices,
    COCOATTRS_OT_add_custom_normals,
)

# Which buttons each list's side column shows, in order.
BUTTONS = {
    'VGROUP': (COCOATTRS_OT_add_vertex_group, COCOATTRS_OT_remove_vertex_groups,
               COCOATTRS_OT_fill_missing_vertex_groups, COCOATTRS_OT_check_all_vertex_groups),
    'DATA': (COCOATTRS_OT_add_attribute, COCOATTRS_OT_remove_attributes,
             COCOATTRS_OT_fill_missing_attributes, COCOATTRS_OT_check_all_attributes),
}


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
