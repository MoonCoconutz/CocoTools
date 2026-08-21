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
    GRID_CELL_SCALE_Y, GRID_POPUP_WIDTH, ITEM_ROW_UNITS,
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
            "keymap_type": "WINDOW", "key": "T",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": workspace_items,
        },
        {
            "name": "Edge Info",
            "idname": "COCOPIE_MT_edge_info",
            "keymap_type": "WINDOW", "key": "2",
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
        # The UV pies drive Zen UV. Without it installed the slots simply
        # report that the operator is missing; install it and they start
        # working, with no edit needed here.
        {
            "name": "UV Transform",
            "idname": "COCOPIE_MT_uv_transform",
            "keymap_type": "UV_EDITOR", "key": "Q",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Flip X", "icon": 'MOD_MIRROR', "position": 0, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_flip(flip_direction='HORIZONTAL')"},
                {"label": "Stack Islands", "icon": 'DUPLICATE', "position": 1, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_simple_stack()"},
                {"label": "Rotate 90", "icon": 'DRIVER_ROTATIONAL_DIFFERENCE', "position": 2, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_rotate(rotation_mode='ANGLE', tr_rot_inc=90)"},
                {"label": "Flip Y", "icon": 'MOD_MIRROR', "position": 3, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_flip(flip_direction='VERTICAL')"},
                {"label": "Sort", "icon": 'SORTSIZE', "position": 4, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_distribute_islands()"},
                {"label": "Stack Similar", "icon": 'STICKY_UVS_LOC', "position": 5, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_stack_similar()"},
                {"label": "Orient World", "icon": 'WORLD', "position": 6, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_world_orient()"},
                {"label": "Orient to Axis", "icon": 'ORIENTATION_GIMBAL', "position": 7, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_orient_island()"},
            ],
        },
        {
            "name": "UV Select",
            "idname": "COCOPIE_MT_uv_select",
            "keymap_type": "UV_EDITOR", "key": "Q",
            "ctrl": False, "shift": False, "alt": True,
            "enabled": True,
            "items": [
                {"label": "Select Similar", "icon": 'SELECT_SET', "position": 0, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_select_similar()"},
                {"label": "Select Overlap", "icon": 'SELECT_SUBTRACT', "position": 1, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_select_uv_overlap()"},
                {"label": "Select Zero", "icon": 'ERROR', "position": 2, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_select_zero_area_faces()"},
                {"label": "Select Flipped", "icon": 'MOD_MIRROR', "position": 3, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_select_flipped()"},
                {"label": "Boundary", "icon": 'MESH_GRID', "position": 7, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_select_uv_borders()"},
            ],
        },
        {
            "name": "UV Unwrap",
            "idname": "COCOPIE_MT_uv_unwrap",
            "keymap_type": "UV_EDITOR", "key": "Q",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": [
                # Left empty on purpose: Mio3 UV does not register an unwrap
                # operator to point at, so there is nothing to wire it to here
                {"label": "UV Unwrap Mio", "icon": 'NONE', "position": 0,
                 "enabled": True, "command": ""},
                {"label": "Unwrap Classic", "icon": 'MOD_UVPROJECT', "position": 1, "enabled": True,
                 "command": "bpy.ops.uv.unwrap()"},
                {"label": "Zen Unwrap", "icon": 'UV_DATA', "position": 2, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_unwrap()"},
                {"label": "Relax", "icon": 'MOD_SMOOTH', "position": 3, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_relax()"},
                {"label": "Rectify", "icon": 'MESH_PLANE', "position": 6, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_rectify()"},
                {"label": "Gridify", "icon": 'MESH_GRID', "position": 7, "enabled": True,
                 "command": "bpy.ops.uv.zenuv_quadrify()"},
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
