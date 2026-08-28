# SPDX-License-Identifier: GPL-3.0-or-later
"""CocoDelete - X deletes straight away in mesh and curve edit mode.

Mesh  : vertices and edges are dissolved (no hole), faces are deleted.
Curve : the selected segment is deleted.

No delete menu, no confirmation popup. Everything lives in the add-on
preferences.
"""

bl_info = {
    "name": "CocoDelete",
    "author": "MoonCoconutz",
    "version": (2, 0, 0),
    "blender": (2, 80, 0),
    "location": "3D Viewport > Edit Mode > X / Delete",
    "description": "Delete in edit mode without the delete menu",
    "category": "3D View",
}

import bpy
from bpy.props import BoolProperty
from bpy.types import AddonPreferences, Operator

# Works as a legacy add-on ("CocoDelete") and as a 4.2+ extension
# ("bl_ext.user_default.CocoDelete").
ADDON_ID = __package__ or __name__

OUR_IDNAMES = {"mesh.cocodelete_delete", "curve.cocodelete_delete"}

# Blender spells DEL as "Delete" everywhere the user sees it.
KEY_LABELS = {'DEL': "Delete"}

# The 3D View region keymap is consulted before the mode keymaps, so a
# binding there can take the key before either of ours does.
REGION_KEYMAP = "3D View"


def get_prefs(context=None):
    """This add-on's preferences, or None if they are not available yet."""
    addon = (context or bpy.context).preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def bound_keys(prefs):
    return ('X', 'DEL') if prefs is None or prefs.use_delete_key else ('X',)


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------

class COCODELETE_OT_mesh_delete(Operator):
    """Delete the selection without showing the delete menu"""
    bl_idname = "mesh.cocodelete_delete"
    bl_label = "Delete (No Menu)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        use_vert, use_edge, use_face = context.tool_settings.mesh_select_mode

        if use_vert or not (use_edge or use_face):
            # delete(type='VERT') also takes the vertex's edges and faces,
            # punching a hole; dissolving merges the surrounding faces instead.
            return bpy.ops.mesh.dissolve_verts()

        if use_edge:
            # delete(type='EDGE') takes the faces on both sides with it;
            # dissolving merges them and clears the redundant vertices.
            return bpy.ops.mesh.dissolve_edges(use_verts=True, use_face_split=False)

        # A lone face has no dissolve equivalent - removing it leaves a hole.
        return bpy.ops.mesh.delete(type='FACE')


class COCODELETE_OT_curve_delete(Operator):
    """Delete the selected segment without showing the delete menu"""
    bl_idname = "curve.cocodelete_delete"
    bl_label = "Delete Segment (No Menu)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_CURVE'

    def execute(self, context):
        return bpy.ops.curve.delete(type='SEGMENT')


# -----------------------------------------------------------------------------
# Keymaps
# -----------------------------------------------------------------------------

addon_keymaps = []


def register_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode without a key configuration
        return

    prefs = get_prefs()
    targets = []
    if prefs is None or prefs.use_mesh_edit:
        targets.append(("Mesh", COCODELETE_OT_mesh_delete.bl_idname))
    if prefs is None or prefs.use_curve_edit:
        targets.append(("Curve", COCODELETE_OT_curve_delete.bl_idname))

    for km_name, idname in targets:
        km = kc.keymaps.new(name=km_name, space_type='EMPTY')
        for key in bound_keys(prefs):
            addon_keymaps.append((km, km.keymap_items.new(idname, key, 'PRESS')))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()


def _refresh_keymaps(self, context):
    unregister_keymaps()
    register_keymaps()


# -----------------------------------------------------------------------------
# What is using the shortcut
# -----------------------------------------------------------------------------

def bindings(km_name, keys):
    """Every unmodified X / Delete binding that applies in this edit mode.

    Read from the merged user keyconfig - the one Blender actually runs - in
    the order it resolves them: the 3D View region keymap is consulted before
    the mode keymap, and inside a keymap the first enabled entry for a key
    wins (add-on entries sit ahead of Blender's defaults).

    Returns (keymap_item, wins) pairs. Disabled entries are included so they
    can be switched back on, but never win.
    """
    kc = bpy.context.window_manager.keyconfigs.user
    if kc is None:
        return []

    rows = []
    claimed = set()
    for name in (REGION_KEYMAP, km_name):
        km = kc.keymaps.get(name)
        if km is None:
            continue
        for kmi in km.keymap_items:
            if (kmi.type not in keys or kmi.any
                    or kmi.ctrl or kmi.alt or kmi.shift or kmi.oskey):
                continue
            wins = kmi.active and kmi.type not in claimed
            if wins:
                claimed.add(kmi.type)
            rows.append((kmi, wins))
    return rows


# -----------------------------------------------------------------------------
# Preferences
# -----------------------------------------------------------------------------

class COCODELETE_Preferences(AddonPreferences):
    bl_idname = ADDON_ID

    use_mesh_edit: BoolProperty(
        name="Mesh Edit Mode",
        description=(
            "X / Delete removes the selection straight away: vertices and edges "
            "are dissolved so no hole is left, faces are deleted"
        ),
        default=True,
        update=_refresh_keymaps,
    )
    use_curve_edit: BoolProperty(
        name="Curve Edit Mode",
        description=(
            "X / Delete removes the selected segment straight away. Needs two "
            "neighbouring points selected, like Blender's own Delete Segment"
        ),
        default=True,
        update=_refresh_keymaps,
    )
    use_delete_key: BoolProperty(
        name="Use the Delete key as well as X",
        default=True,
        update=_refresh_keymaps,
    )

    def draw(self, context):
        layout = self.layout
        keys = bound_keys(self)

        self._mode_block(layout, "use_mesh_edit", "Mesh", keys)
        layout.separator()
        self._mode_block(layout, "use_curve_edit", "Curve", keys)
        layout.separator()
        layout.prop(self, "use_delete_key")

    def _mode_block(self, layout, prop, km_name, keys):
        """The mode's checkbox, with everything using the key listed beside it."""
        split = layout.split(factor=0.35)
        split.prop(self, prop)

        col = split.column(align=True)
        col.active = getattr(self, prop)

        rows = bindings(km_name, keys)
        if not rows:
            col.label(text="nothing bound to %s" % " or ".join(
                KEY_LABELS.get(k, k) for k in keys))
            return

        for kmi, wins in rows:
            row = col.row(align=True)

            toggle = row.row(align=True)
            # Our own entries are controlled by the checkbox on the left.
            toggle.enabled = kmi.idname not in OUR_IDNAMES
            toggle.prop(kmi, "active", text="")

            body = row.row(align=True)
            body.active = kmi.active
            body.label(text="%s   %s" % (KEY_LABELS.get(kmi.type, kmi.type), kmi.idname),
                       icon='CHECKMARK' if wins else 'BLANK1')


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------

classes = (
    COCODELETE_OT_mesh_delete,
    COCODELETE_OT_curve_delete,
    COCODELETE_Preferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
