"""The starter pie menus, and the example workspace scripts they run."""

import bpy
import os
import json
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, FloatProperty,
)
from bpy.types import Operator, PropertyGroup, Menu, AddonPreferences
from .items import (
    POSITION_ARROWS, POSITION_NAMES, POSITION_GRID,
    GRID_CELL_UNITS, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
    COL_CHECK_UNITS, COL_POS_UNITS, COL_ICON_UNITS,
    COL_LABEL_SCALE, COL_CMD_SCALE, COL_TOOLS_UNITS,
    KEYMAP_CONFIG, WINDOW_MODE_KEYMAPS,
)
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
)
from .keymaps import register_pie_menus, unregister_pie_menus
from .presets import (
    _apply_pie_dict, _merge_preset_menus, _pending_preset_data,
    _draw_preset_conflict_popup, _deferred_show_preset_conflict_popup,
)


# Workspaces the bundled scripts switch to. Each has a .py file shipped in
# scripts/workspaces/ beside this module, and one slot in the Workspace pie.
# They run as script files rather than inline commands on purpose: the Workspace
# pie doubles as a worked example of what an execute_script() slot looks like.
WORKSPACE_TARGETS = (
    ("WorkspaceToShading.py",       "Shading",        'SHADING_TEXTURE',  0),
    ("WorkspaceToLayout.py",        "Layout",         'VIEW3D',           1),
    ("WorkspaceToUVEditing.py",     "UV Editing",     'UV',               2),
    ("WorkspaceToGeometryNodes.py", "Geometry Nodes", 'GEOMETRY_NODES',   3),
    ("WorkspaceToSculpting.py",     "Sculpting",      'SCULPTMODE_HLT',   4),
    ("WorkspaceToScripting.py",     "Scripting",      'FILE_SCRIPT',      5),
)


def bundled_scripts_dir():
    """Folder the example workspace scripts ship in, inside this package"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "scripts", "workspaces")


def bundled_script_paths():
    """{filename: absolute path} for the example scripts that are present.

    Resolved from this file's own location, so the paths baked into the starter
    pie point at wherever CocoPie was installed -- an absolute path saved on one
    machine, or under one Blender version, does not survive being carried to
    another. A missing file is left out rather than pointed at.
    """
    folder = bundled_scripts_dir()
    paths = {}
    for filename, _workspace, _icon, _position in WORKSPACE_TARGETS:
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            paths[filename] = path
        else:
            print(f"CocoPie: bundled script missing: {path}")
    return paths


def default_pie_definitions(script_paths):
    """The starter pies, in the same dict shape the preset loader consumes"""
    workspace_items = []
    for filename, workspace, icon, position in WORKSPACE_TARGETS:
        path = script_paths.get(filename)
        workspace_items.append({
            "label": workspace,
            "icon": icon,
            "position": position,
            "enabled": True,
            # No script on disk means no command; the slot stays visible but
            # inert rather than pointing at a file that isn't there
            "command": 'execute_script("%s")' % path.replace("\\", "/") if path else "",
        })

    def overlay(name):
        prop = f"bpy.context.space_data.overlay.{name}"
        return f"{prop} = not {prop}"

    return [
        {
            "name": "Workspace Menu",
            "idname": "COCOPIE_MT_workspace",
            "keymap_type": "WINDOW", "keymap_scopes": ["WINDOW"],
            "key": "T",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            # Held, this opens the pie; tapped, it alternates between Layout
            # and UV Editing without opening anything. event_value is spelled
            # out to match what turning Tap to Toggle on forces anyway, so the
            # stored data is self-consistent rather than leaning on the update
            # callback to correct it afterwards.
            "event_value": "CLICK_DRAG",
            "tap_toggle": True,
            "tap_toggle_a": "1",   # Right: Layout
            "tap_toggle_b": "2",   # Bottom: UV Editing
            "items": workspace_items,
        },
        {
            "name": "Edge Info",
            "idname": "COCOPIE_MT_edge_info",
            "keymap_type": "WINDOW", "keymap_scopes": ["WINDOW"], "key": "2",
            "ctrl": False, "shift": False, "alt": True,
            "enabled": True,
            "items": [
                {"label": "Display Bevel Weight", "icon": 'COLORSET_04_VEC', "position": 0,
                 "enabled": True, "command": overlay("show_edge_bevel_weight")},
                {"label": "Display Seams", "icon": 'COLORSET_01_VEC', "position": 1,
                 "enabled": True, "command": overlay("show_edge_seams")},
                {"label": "Display Crease", "icon": 'COLORSET_03_VEC', "position": 2,
                 "enabled": True, "command": overlay("show_edge_crease")},
                {"label": "Display Sharp", "icon": 'COLORSET_06_VEC', "position": 3,
                 "enabled": True, "command": overlay("show_edge_sharp")},
            ],
        },
        # Mostly Zen UV; Flip X/Y are stock Blender instead (see above).
        # Without Zen UV installed the rest of these slots simply report a
        # missing operator; install it and they start working, with no edit
        # needed here.
        {
            "name": "UV Transform",
            "idname": "COCOPIE_MT_uv_transform",
            "keymap_type": "UV_EDITOR", "keymap_scopes": ["UV_EDITOR"], "key": "D",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                # Stock Blender rather than Zen UV: transform.resize with a
                # constrained axis is exactly what S, X, -1 does in the UV
                # editor -- reflects the selection around its own median
                # point. Verified against real UV coordinates, not assumed.
                {"label": "Flip X", "icon": 'MOD_MIRROR', "position": 0, "enabled": True,
                 "command": "bpy.ops.transform.resize(value=(-1, 1, 1), constraint_axis=(True, False, False))"},
                {"label": "Stack Islands", "icon": 'DUPLICATE', "position": 1, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_simple_stack()"},
                # Stock Blender: transform.rotate is what R 90 Enter runs in the
                # UV editor -- negative because the user wants this slot to spin
                # clockwise; positive is counter-clockwise, confirmed against
                # real UV coordinates, not assumed from the sign alone. The
                # value is radians pre-computed to a literal -- math.radians(90)
                # itself is a call, not a literal, so the parser that reads this
                # command (deliberately, for safety -- see _parse_bpy_ops_call
                # in menus.py) would not accept it and this would silently fall
                # back to the exec() path instead.
                {"label": "Rotate 90", "icon": 'DRIVER_ROTATIONAL_DIFFERENCE', "position": 2, "enabled": True,
                 "command": "bpy.ops.transform.rotate(value=-1.5707963267948966)"},
                {"label": "Flip Y", "icon": 'MOD_MIRROR', "position": 3, "enabled": True,
                 "command": "bpy.ops.transform.resize(value=(1, -1, 1), constraint_axis=(False, True, False))"},
                {"label": "Sort", "icon": 'SORTSIZE', "position": 4, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_distribute_islands()"},
                {"label": "Stack Similar", "icon": 'STICKY_UVS_LOC', "position": 5, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_stack_similar()"},
                {"label": "Orient World", "icon": 'WORLD', "position": 6, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_world_orient()"},
                # Explicit rather than defaults: Zen UV's own default for
                # "Orient by" is Bounding Box, but the user wants By Selection.
                # The other three already matched Zen UV's defaults, spelled
                # out anyway so the whole setting is visible in one place and
                # will not drift if Zen UV's defaults ever change.
                {"label": "Orient to Axis", "icon": 'ORIENTATION_GIMBAL', "position": 7, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_orient_island(order='ONE_BY_ONE', "
                            "mode='BY_SELECTION', orient_direction='AUTO', rotate_direction='CCW')"},
            ],
        },
        {
            "name": "UV Select",
            "idname": "COCOPIE_MT_uv_select",
            "keymap_type": "UV_EDITOR", "keymap_scopes": ["UV_EDITOR"], "key": "A",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            # Mostly Mio3 UV, with overlap coming from Zen UV
            "items": [
                {"label": "Select Similar", "icon": 'SELECT_SET', "position": 0, "enabled": True,
                 "command": "bpy.ops.uv.mio3_select_similar()"},
                {"label": "Select Overlap", "icon": 'SELECT_SUBTRACT', "position": 1, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_select_uv_overlap()"},
                {"label": "Select Zero", "icon": 'ERROR', "position": 2, "enabled": True,
                 "command": "bpy.ops.uv.mio3_select_zero()"},
                {"label": "Select Flipped", "icon": 'MOD_MIRROR', "position": 3, "enabled": True,
                 "command": "bpy.ops.uv.mio3_select_flipped_faces()"},
                {"label": "Boundary", "icon": 'MESH_GRID', "position": 7, "enabled": True,
                 "command": "bpy.ops.uv.mio3_select_edge()"},
            ],
        },
        # Unlike the other two UV pies, this one drives Mio3 UV rather than
        # Zen UV, and only the classic unwrap is stock Blender.
        {
            "name": "UV Unwrap",
            "idname": "COCOPIE_MT_uv_unwrap",
            "keymap_type": "UV_EDITOR", "keymap_scopes": ["UV_EDITOR"], "key": "F",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                # Icons chosen to read as the command: the two aligns share the
                # ANCHOR family and the two axis unwraps share AXIS, so each
                # pair reads as siblings rather than as unrelated pictures
                {"label": "Align UVs X", "icon": 'ANCHOR_LEFT', "position": 0, "enabled": True,
                 "command": "bpy.ops.uv.mio3_align(type='ALIGN_X')"},
                {"label": "Unwrap Classic", "icon": 'MOD_UVPROJECT', "position": 1, "enabled": True,
                 "command": "bpy.ops.uv.unwrap(method='ANGLE_BASED')"},
                {"label": "Align UVs Y", "icon": 'ANCHOR_TOP', "position": 2, "enabled": True,
                 "command": "bpy.ops.uv.mio3_align(type='ALIGN_Y')"},
                {"label": "UV Unwrap Mio", "icon": 'UV', "position": 3, "enabled": True,
                 "command": "bpy.ops.uv.mio3_unwrap()"},
                {"label": "Rectify", "icon": 'MESH_PLANE', "position": 4, "enabled": True,
                 "command": "bpy.ops.uv.mio3_rectify()"},
                {"label": "Gridify", "icon": 'MESH_GRID', "position": 5, "enabled": True,
                 "command": "bpy.ops.uv.mio3_gridify()"},
                {"label": "UV Unwrap X", "icon": 'AXIS_SIDE', "position": 6, "enabled": True,
                 "command": "bpy.ops.uv.mio3_unwrap(axis='X')"},
                {"label": "UV Unwrap Y", "icon": 'AXIS_FRONT', "position": 7, "enabled": True,
                 "command": "bpy.ops.uv.mio3_unwrap(axis='Y')"},
            ],
        },
        # Mesh-edit-mode UV prep, in the 3D viewport rather than the UV
        # editor -- seams, sharp and crease are usually set while looking at
        # the mesh, not the unwrap. Bevel Weight/Crease/Sharp are toggles
        # rather than Blender's relative transform.edge_* modal operators:
        # those add a delta and need a mouse drag, which does not fit a pie
        # slot. Each toggle instead reads the current value directly off the
        # mesh (bevel weight and crease are float custom-data layers since
        # Blender 4.0's edge-attribute rework; sharp is BMEdge.smooth) and
        # flips the whole selection to the opposite state in one press.
        {
            "name": "3D UV",
            "idname": "COCOPIE_MT_3d_uv",
            "keymap_type": "3D_VIEW", "keymap_scopes": ["3D_VIEW"], "key": "F",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Clear Seams", "icon": 'X', "position": 0, "enabled": True,
                 "command": "bpy.ops.mesh.mark_seam(clear=True)"},
                {"label": "Mark Seams", "icon": 'EDGE_SEAM', "position": 1, "enabled": True,
                 "command": "bpy.ops.mesh.mark_seam(clear=False)"},
                {"label": "Smart UV Project", "icon": 'MOD_UVPROJECT', "position": 2, "enabled": True,
                 "command": "bpy.ops.uv.smart_project()"},
                {"label": "Unwrap", "icon": 'UV', "position": 3, "enabled": True,
                 "command": "bpy.ops.uv.unwrap()"},
                # No stock "clear every seam" operator exists, so this
                # selects everything first -- the one unavoidable side
                # effect of a genuinely whole-mesh clear.
                {"label": "Clear All Seams", "icon": 'X', "position": 4, "enabled": True,
                 "command": "bpy.ops.mesh.select_all(action='SELECT')\n"
                            "bpy.ops.mesh.mark_seam(clear=True)"},
                {"label": "Edge Bevel Weight", "icon": 'EDGE_BEVEL', "position": 5, "enabled": True,
                 "command": "import bmesh\n"
                            "bm = bmesh.from_edit_mesh(context.object.data)\n"
                            "bm.edges.ensure_lookup_table()\n"
                            "layer = bm.edges.layers.float.get('bevel_weight_edge') "
                            "or bm.edges.layers.float.new('bevel_weight_edge')\n"
                            "sel = [e for e in bm.edges if e.select]\n"
                            "new_val = 0.0 if sel and all(e[layer] >= 0.999 for e in sel) else 1.0\n"
                            "for e in sel:\n"
                            "    e[layer] = new_val\n"
                            "bmesh.update_edit_mesh(context.object.data)"},
                {"label": "Edge Crease", "icon": 'EDGE_CREASE', "position": 6, "enabled": True,
                 "command": "import bmesh\n"
                            "bm = bmesh.from_edit_mesh(context.object.data)\n"
                            "bm.edges.ensure_lookup_table()\n"
                            "layer = bm.edges.layers.float.get('crease_edge') "
                            "or bm.edges.layers.float.new('crease_edge')\n"
                            "sel = [e for e in bm.edges if e.select]\n"
                            "new_val = 0.0 if sel and all(e[layer] >= 0.999 for e in sel) else 1.0\n"
                            "for e in sel:\n"
                            "    e[layer] = new_val\n"
                            "bmesh.update_edit_mesh(context.object.data)"},
                {"label": "Mark Sharp", "icon": 'EDGE_SHARP', "position": 7, "enabled": True,
                 "command": "import bmesh\n"
                            "bm = bmesh.from_edit_mesh(context.object.data)\n"
                            "sel = [e for e in bm.edges if e.select]\n"
                            "new_smooth = bool(sel) and all(not e.smooth for e in sel)\n"
                            "for e in sel:\n"
                            "    e.smooth = new_smooth\n"
                            "bmesh.update_edit_mesh(context.object.data)"},
            ],
        },
    ]


def ensure_default_pies(prefs):
    """Add any starter pie that isn't present, and return how many were added.

    Matched by name, so a starter pie the user has renamed, edited or deleted
    is never resurrected or overwritten -- only genuinely missing ones are
    added. On a fresh install that means all of them.
    """
    existing = {pie.name for pie in prefs.pie_menus}
    added = 0

    for definition in default_pie_definitions(bundled_script_paths()):
        if definition["name"] in existing:
            continue

        pie = prefs.pie_menus.add()
        pie.name = definition["name"]
        _apply_pie_dict(pie, definition)
        added += 1

    return added


class COCOPIE_OT_restore_defaults(Operator):
    """Add any starter pie menus that are missing.
    Pie menus you already have are left untouched"""
    bl_idname = "cocopie.restore_defaults"
    bl_label = "Restore Starter Pies"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        prefs = get_prefs(context)
        if not prefs:
            return {'CANCELLED'}
        try:
            added = ensure_default_pies(prefs)
        except Exception as e:
            self.report({'ERROR'}, f"Could not restore starter pies: {e}")
            return {'CANCELLED'}

        register_pie_menus()
        if added:
            self.report({'INFO'}, f"Added {added} starter pie menu(s)")
        else:
            self.report({'INFO'}, "All starter pie menus are already present")
        return {'FINISHED'}
