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
from .icons import safe_icon
from .utils import (
    ADDON_ID, get_prefs, get_pie, get_pie_item, format_shortcut,
    keymap_names_for, find_shortcut_conflicts, find_duplicate_positions, _debug,
)
from .keymaps import register_pie_menus, unregister_pie_menus
from .presets import (
    _apply_pie_dict, _merge_preset_menus, _pending_preset_data,
    _draw_preset_conflict_popup, _deferred_show_preset_conflict_popup,
)


# Since 4.3 a sculpt brush is an *asset*, not a tool setting, so selecting one
# means activating it out of Blender's bundled "Essentials" library rather than
# setting an enum. The identifier is a path inside that library, and it is
# built with os.path.join deliberately: Blender matches it against a
# platform-native relative path, so this is a backslashed path on Windows.
# Embedding it with repr() keeps that correct through storage, since the
# command is kept as text and parsed back with ast.literal_eval.
_SCULPT_BRUSH_LIBRARY = ("brushes", "essentials_brushes-mesh_sculpt.blend", "Brush")


def _sculpt_brush_command(brush_name):
    """The command that activates one bundled sculpt brush by its asset name"""
    identifier = os.path.join(*_SCULPT_BRUSH_LIBRARY, brush_name)
    return ("bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', "
            f"relative_asset_identifier={identifier!r})")


def _sub_pie_command(idname):
    """The command that opens another pie from a slot of this one"""
    return f"bpy.ops.wm.call_menu_pie(name='{idname}')"


def _brush_slots(entries):
    """[(position, brush asset name, icon)] -> pie item dicts"""
    return [
        {"label": name, "icon": icon, "position": position, "enabled": True,
         "command": _sculpt_brush_command(name)}
        for position, name, icon in entries
    ]


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


# The mesh delete script, which a starter pie runs on tap. Resolved the same
# way and for the same reason as the workspace scripts: the path is baked into
# stored pie data, so it has to point at wherever this install actually is.
MESH_DELETE_SCRIPT = "MeshDeleteNoMenu.py"


def delete_script_path():
    """Absolute path to the bundled mesh delete script, or None if missing"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "scripts", "delete", MESH_DELETE_SCRIPT)
    if os.path.exists(path):
        return path
    print(f"CocoPies: bundled script missing: {path}")
    return None


def _icon(*candidates):
    """The first of `candidates` this Blender actually has.

    Blender 5.0 added the EDGE_SEAM / EDGE_CREASE / EDGE_SHARP / EDGE_BEVEL
    icons; 4.5 ships none of them. Naming one there is not an error -- draw
    time runs every icon through safe_icon() -- but the slot comes out with a
    blank where its icon should be, so the starters would look half-finished
    on the older release the addon still supports. Each slot therefore names
    the icon it wants first and a 4.5-era stand-in after it, resolved once
    here when the starter pies are created.

    The result is baked into the stored pie, so a pie seeded on 4.5 keeps the
    fallback if that config is later opened on 5.x. That is deliberate: by
    then it is the user's own data, and theirs to change.
    """
    for name in candidates:
        if safe_icon(name, fallback=None) is not None:
            return name
    return 'NONE'


def bundled_script_paths():
    """{filename: absolute path} for the example scripts that are present.

    Resolved from this file's own location, so the paths baked into the starter
    pie point at wherever CocoPies was installed -- an absolute path saved on one
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
            print(f"CocoPies: bundled script missing: {path}")
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

    delete_script = delete_script_path()
    mesh_delete_tap = ('execute_script("%s")' % delete_script.replace("\\", "/")
                       if delete_script else "")

    return [
        # X in curve edit: tapped it deletes the segment, held it opens the
        # pie. One key doing both is the point -- this and the Quick Tap on
        # Mesh Delete below replace the CocoDelete extension, which bound X
        # itself and raced CocoPies for it, whichever registered first
        # winning. Curve needs no script: its delete takes no select-mode
        # branching, unlike mesh.
        {
            "name": "Curve Delete",
            "idname": "COCOPIE_MT_curve_delete",
            "keymap_type": "CURVE", "keymap_scopes": ["CURVE"],
            "key": "X",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "event_value": "CLICK_DRAG",
            "tap_toggle": True,
            "tap_action": "COMMAND",
            # A one-liner rather than a script: curve delete needs no
            # select-mode branching, so there is nothing for a script to hold
            "tap_command": "bpy.ops.curve.delete(type='SEGMENT')",
            "items": [
                {"label": "Delete Vertices", "position": 0,
                 "command": "bpy.ops.curve.delete(type='VERT')",
                 "icon": _icon("DOT"), "enabled": True},
                {"label": "Delete Segment", "position": 1,
                 "command": "bpy.ops.curve.delete(type='SEGMENT')",
                 "icon": _icon("DRIVER_DISTANCE"), "enabled": True},
            ],
        },
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
                {"label": "Display Bevel Weight", "icon": _icon('EDGE_BEVEL', 'MOD_BEVEL'), "position": 0,
                 "enabled": True, "command": overlay("show_edge_bevel_weight")},
                {"label": "Display Seams", "icon": _icon('EDGE_SEAM', 'COLORSET_01_VEC'), "position": 1,
                 "enabled": True, "command": overlay("show_edge_seams")},
                {"label": "Display Crease", "icon": _icon('EDGE_CREASE', 'COLORSET_03_VEC'), "position": 2,
                 "enabled": True, "command": overlay("show_edge_crease")},
                {"label": "Display Sharp", "icon": _icon('EDGE_SHARP', 'MOD_EDGESPLIT'), "position": 3,
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
            # 3D View Generic, not 3D View: that keymap is consulted first, so
            # Shift+F wins over anything else bound to it in the viewport
            "keymap_type": "3D_VIEW_GENERIC", "keymap_scopes": ["3D_VIEW_GENERIC"], "key": "F",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Clear Seams", "icon": 'X', "position": 0, "enabled": True,
                 "command": "bpy.ops.mesh.mark_seam(clear=True)"},
                {"label": "Mark Seams", "icon": _icon('EDGE_SEAM', 'COLORSET_01_VEC'), "position": 1, "enabled": True,
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
                {"label": "Edge Bevel Weight", "icon": _icon('EDGE_BEVEL', 'MOD_BEVEL'), "position": 5, "enabled": True,
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
                {"label": "Edge Crease", "icon": _icon('EDGE_CREASE', 'COLORSET_03_VEC'), "position": 6, "enabled": True,
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
                {"label": "Mark Sharp", "icon": _icon('EDGE_SHARP', 'MOD_EDGESPLIT'), "position": 7, "enabled": True,
                 "command": "import bmesh\n"
                            "bm = bmesh.from_edit_mesh(context.object.data)\n"
                            "sel = [e for e in bm.edges if e.select]\n"
                            "new_smooth = bool(sel) and all(not e.smooth for e in sel)\n"
                            "for e in sel:\n"
                            "    e.smooth = new_smooth\n"
                            "bmesh.update_edit_mesh(context.object.data)"},
            ],
        },
        # The next six starters port pies from the "3D Viewport Pie Menus"
        # extension (blender_org/viewport_pie_menus) using only stock Blender
        # operators -- no dependency on that extension staying installed.
        # Two of the originals (Mesh Select, Proportional Edit) used a
        # mouse-drag gesture to pick between a single fallback action on a
        # tap and the full pie on a hold; CocoPies has no drag-distance
        # gesture yet, only Tap to Toggle's hold-duration timer, used here
        # as the nearest equivalent.
        {
            "name": "Mesh Delete",
            "idname": "COCOPIE_MT_mesh_delete",
            "keymap_type": "MESH", "keymap_scopes": ["MESH"], "key": "X",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            # Tapped, X deletes through the bundled script -- which carries
            # the select-mode branching that made CocoDelete worth having --
            # while holding X opens this pie. See the Curve Delete note above.
            "event_value": "CLICK_DRAG",
            "tap_toggle": True,
            "tap_action": "COMMAND",
            "tap_command": mesh_delete_tap,
            "items": [
                {"label": "Limited Dissolve", "icon": "STICKY_UVS_LOC", "position": 0, "enabled": True,
                 "command": "bpy.ops.mesh.dissolve_limited()"},
                {"label": "Merge By Distance", "icon": "NONE", "position": 1, "enabled": True,
                 "command": "bpy.ops.mesh.remove_doubles()"},
                {"label": "Dissolve Edges", "icon": "SNAP_EDGE", "position": 2, "enabled": True,
                 "command": "bpy.ops.mesh.dissolve_edges()"},
                {"label": "Delete Edges", "icon": "EDGESEL", "position": 3, "enabled": True,
                 "command": "bpy.ops.mesh.delete(type='EDGE')"},
                {"label": "Delete Vertices", "icon": "VERTEXSEL", "position": 4, "enabled": True,
                 "command": "bpy.ops.mesh.delete(type='VERT')"},
                {"label": "Delete Faces", "icon": "FACESEL", "position": 5, "enabled": True,
                 "command": "bpy.ops.mesh.delete(type='FACE')"},
                {"label": "Dissolve Vertices", "icon": "SNAP_VERTEX", "position": 6, "enabled": True,
                 "command": "bpy.ops.mesh.dissolve_verts()"},
                {"label": "Dissolve Faces", "icon": "SNAP_FACE", "position": 7, "enabled": True,
                 "command": "bpy.ops.mesh.dissolve_faces()"},
            ],
        },
        {
            "name": "Mesh Merge",
            "idname": "COCOPIE_MT_mesh_merge",
            "keymap_type": "MESH", "keymap_scopes": ["MESH"], "key": "M",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": [
                {"label": "By Distance", "icon": "PROP_ON", "position": 0, "enabled": True,
                 "command": "bpy.ops.mesh.remove_doubles()"},
                {"label": "At Center", "icon": "SNAP_FACE_CENTER", "position": 1, "enabled": True,
                 "command": "bpy.ops.mesh.merge(type='CENTER')"},
                {"label": "Collapse", "icon": "FULLSCREEN_EXIT", "position": 2, "enabled": True,
                 "command": "bpy.ops.mesh.merge(type='COLLAPSE')"},
                {"label": "At First", "icon": "TRACKING_REFINE_BACKWARDS", "position": 4, "enabled": True,
                 "command": "bpy.ops.mesh.merge(type='FIRST')"},
                {"label": "At Last", "icon": "TRACKING_REFINE_FORWARDS", "position": 5, "enabled": True,
                 "command": "bpy.ops.mesh.merge(type='LAST')"},
                {"label": "At 3D Cursor", "icon": "PIVOT_CURSOR", "position": 7, "enabled": True,
                 "command": "bpy.ops.mesh.merge(type='CURSOR')"},
            ],
        },
        # Original fallback on a tap was mesh.select_all(action='TOGGLE'),
        # which itself alternates select-all/deselect-all depending on
        # current state -- Select All/Deselect All on tap_toggle_a/b
        # reproduces that same alternation.
        {
            "name": "Mesh Select",
            "idname": "COCOPIE_MT_mesh_select",
            "keymap_type": "MESH", "keymap_scopes": ["MESH"], "key": "A",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "event_value": "CLICK_DRAG",
            "tap_toggle": True,
            "tap_toggle_a": "3",  # Top: Select All
            "tap_toggle_b": "2",  # Bottom: Deselect All
            "items": [
                {"label": "Select Less", "icon": "REMOVE", "position": 0, "enabled": True,
                 "command": "bpy.ops.mesh.select_less()"},
                {"label": "Select More", "icon": "ADD", "position": 1, "enabled": True,
                 "command": "bpy.ops.mesh.select_more()"},
                {"label": "Deselect All", "icon": "OUTLINER_DATA_POINTCLOUD", "position": 2, "enabled": True,
                 "command": "bpy.ops.mesh.select_all(action='DESELECT')"},
                {"label": "Select All", "icon": "OUTLINER_OB_POINTCLOUD", "position": 3, "enabled": True,
                 "command": "bpy.ops.mesh.select_all(action='SELECT')"},
                {"label": "Invert Selection", "icon": "CLIPUV_DEHLT", "position": 4, "enabled": True,
                 "command": "bpy.ops.mesh.select_all(action='INVERT')"},
                {"label": "Select Linked", "icon": "FILE_3D", "position": 5, "enabled": True,
                 "command": "bpy.ops.mesh.select_linked()"},
            ],
        },
        {
            "name": "Add Object",
            "idname": "COCOPIE_MT_object_add",
            "keymap_type": "OBJECT_MODE", "keymap_scopes": ["OBJECT_MODE"], "key": "A",
            "ctrl": True, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                {"label": "UV Sphere", "icon": "MESH_UVSPHERE", "position": 0, "enabled": True,
                 "command": "bpy.ops.mesh.primitive_uv_sphere_add()"},
                {"label": "Cube", "icon": "MESH_CUBE", "position": 1, "enabled": True,
                 "command": "bpy.ops.mesh.primitive_cube_add()"},
                {"label": "Suzanne", "icon": "MESH_MONKEY", "position": 2, "enabled": True,
                 "command": "bpy.ops.mesh.primitive_monkey_add()"},
                {"label": "Plane", "icon": "MESH_PLANE", "position": 3, "enabled": True,
                 "command": "bpy.ops.mesh.primitive_plane_add()"},
                {"label": "Cylinder", "icon": "MESH_CYLINDER", "position": 4, "enabled": True,
                 "command": "bpy.ops.mesh.primitive_cylinder_add()"},
                {"label": "Circle", "icon": "MESH_CIRCLE", "position": 5, "enabled": True,
                 "command": "bpy.ops.mesh.primitive_circle_add()"},
                {"label": "Bezier Curve", "icon": "CURVE_BEZCURVE", "position": 6, "enabled": True,
                 "command": "bpy.ops.curve.primitive_bezier_curve_add()"},
                {"label": "More...", "icon": "THREE_DOTS", "position": 7, "enabled": True,
                 "command": 'bpy.ops.wm.call_menu(name="VIEW3D_MT_add")'},
            ],
        },
        # Split into two starters (rather than one pie with two keymap
        # scopes) because their contents genuinely differ by mode: Object
        # Mode shows Root/Inverse Square falloffs directly, Mesh Edit mode
        # shows Connected/Projected toggles in those same two slots instead.
        # Each drops one slot the original spent on a "More..." submenu of
        # extra falloff shapes -- a genuine extension-only Menu class, not
        # portable without keeping that extension installed.
        {
            "name": "Proportional Edit (Object Mode)",
            "idname": "COCOPIE_MT_prop_edit_object",
            "keymap_type": "OBJECT_MODE", "keymap_scopes": ["OBJECT_MODE"], "key": "O",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "event_value": "CLICK_DRAG",
            "tap_toggle": True,
            "tap_toggle_a": "3",  # Top: Toggle Proportional
            "tap_toggle_b": "3",
            "items": [
                {"label": "Smooth", "icon": "SMOOTHCURVE", "position": 0, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'SMOOTH'\n"
                            "bpy.context.tool_settings.use_proportional_edit_objects = True"},
                {"label": "Sharp", "icon": "SHARPCURVE", "position": 2, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'SHARP'\n"
                            "bpy.context.tool_settings.use_proportional_edit_objects = True"},
                {"label": "Toggle Proportional", "icon": "PROP_ON", "position": 3, "enabled": True,
                 "command": "bpy.context.tool_settings.use_proportional_edit_objects = "
                            "not bpy.context.tool_settings.use_proportional_edit_objects"},
                {"label": "Root", "icon": "ROOTCURVE", "position": 4, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'ROOT'\n"
                            "bpy.context.tool_settings.use_proportional_edit_objects = True"},
                {"label": "Inverse Square", "icon": "INVERSESQUARECURVE", "position": 5, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'INVERSE_SQUARE'\n"
                            "bpy.context.tool_settings.use_proportional_edit_objects = True"},
                {"label": "Linear", "icon": "LINCURVE", "position": 6, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'LINEAR'\n"
                            "bpy.context.tool_settings.use_proportional_edit_objects = True"},
                {"label": "Sphere", "icon": "SPHERECURVE", "position": 7, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'SPHERE'\n"
                            "bpy.context.tool_settings.use_proportional_edit_objects = True"},
            ],
        },
        {
            "name": "Proportional Edit (Mesh Edit)",
            "idname": "COCOPIE_MT_prop_edit_mesh",
            "keymap_type": "MESH", "keymap_scopes": ["MESH"], "key": "O",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "event_value": "CLICK_DRAG",
            "tap_toggle": True,
            "tap_toggle_a": "3",  # Top: Toggle Proportional
            "tap_toggle_b": "3",
            "items": [
                {"label": "Smooth", "icon": "SMOOTHCURVE", "position": 0, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'SMOOTH'\n"
                            "bpy.context.tool_settings.use_proportional_edit = True"},
                {"label": "Sharp", "icon": "SHARPCURVE", "position": 2, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'SHARP'\n"
                            "bpy.context.tool_settings.use_proportional_edit = True"},
                {"label": "Toggle Proportional", "icon": "PROP_ON", "position": 3, "enabled": True,
                 "command": "bpy.context.tool_settings.use_proportional_edit = "
                            "not bpy.context.tool_settings.use_proportional_edit"},
                {"label": "Toggle Connected", "icon": "PROP_CON", "position": 4, "enabled": True,
                 "command": "bpy.context.tool_settings.use_proportional_connected = "
                            "not bpy.context.tool_settings.use_proportional_connected"},
                {"label": "Toggle Projected", "icon": "PROP_PROJECTED", "position": 5, "enabled": True,
                 "command": "bpy.context.tool_settings.use_proportional_projected = "
                            "not bpy.context.tool_settings.use_proportional_projected"},
                {"label": "Linear", "icon": "LINCURVE", "position": 6, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'LINEAR'\n"
                            "bpy.context.tool_settings.use_proportional_edit = True"},
                {"label": "Sphere", "icon": "SPHERECURVE", "position": 7, "enabled": True,
                 "command": "bpy.context.tool_settings.proportional_edit_falloff = 'SPHERE'\n"
                            "bpy.context.tool_settings.use_proportional_edit = True"},
            ],
        },
        {
            # "3D View Generic" rather than "3D View" on purpose: that keymap
            # stays live while another tool is running, which is where Blender
            # itself keeps N. Bound in "3D View" the pie would go dead exactly
            # when a modal operator is up.
            "name": "Region Toggle",
            "idname": "COCOPIE_MT_region_toggle",
            "keymap_type": "3D_VIEW_GENERIC", "keymap_scopes": ["3D_VIEW_GENERIC"],
            "key": "N",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Toolbar", "icon": "TOOL_SETTINGS", "position": 0, "enabled": True,
                 "command": "bpy.context.space_data.show_region_toolbar = True"},
                {"label": "Sidebar", "icon": "MENU_PANEL", "position": 1, "enabled": True,
                 "command": "bpy.context.space_data.show_region_ui = True"},
                # Bottom-right rather than bottom: the asset shelf only exists
                # in the sculpt/paint/pose modes, so it greys out in object
                # mode and does not earn the easiest slot in the pie.
                {"label": "Asset Shelf", "icon": "ASSET_MANAGER", "position": 7, "enabled": True,
                 "command": "bpy.context.space_data.show_region_asset_shelf = True"},
                {"label": "Tool Settings", "icon": "PREFERENCES", "position": 3, "enabled": True,
                 "command": "bpy.context.space_data.show_region_tool_header = True"},
                {"label": "Header", "icon": "TOPBAR", "position": 4, "enabled": True,
                 "command": "bpy.context.space_data.show_region_header = True"},
                {"label": "Adjust Last Operation", "icon": "LOOP_BACK", "position": 5, "enabled": True,
                 "command": "bpy.context.space_data.show_region_hud = True"},
            ],
        },
        {
            "name": "Animation",
            "idname": "COCOPIE_MT_animation",
            # Window (Global) rather than Object Non-modal: playback is worth
            # having in every 3D viewport mode, not just object mode
            "keymap_type": "WINDOW", "keymap_scopes": ["WINDOW"],
            "key": "SPACE",
            "ctrl": False, "shift": True, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Jump to Start", "icon": "REW", "position": 0, "enabled": True,
                 "command": "bpy.ops.screen.frame_jump(end=False)"},
                {"label": "Jump to End", "icon": "FF", "position": 1, "enabled": True,
                 "command": "bpy.ops.screen.frame_jump(end=True)"},
                {"label": "Play Reverse", "icon": "PLAY_REVERSE", "position": 2, "enabled": True,
                 "command": "bpy.ops.screen.animation_play(reverse=True)"},
                {"label": "Play / Pause", "icon": "PLAY", "position": 3, "enabled": True,
                 "command": "bpy.ops.screen.animation_play()"},
                {"label": "Previous Keyframe", "icon": "PREV_KEYFRAME", "position": 4, "enabled": True,
                 "command": "bpy.ops.screen.keyframe_jump(next=False)"},
                {"label": "Next Keyframe", "icon": "NEXT_KEYFRAME", "position": 5, "enabled": True,
                 "command": "bpy.ops.screen.keyframe_jump(next=True)"},
                {"label": "Auto Keying", "icon": "REC", "position": 6, "enabled": True,
                 "command": "bpy.context.tool_settings.use_keyframe_insert_auto = True"},
                {"label": "Keyframe Menu", "icon": "KEYINGSET", "position": 7, "enabled": True,
                 "command": "bpy.ops.wm.call_menu(name='VIEW3D_MT_object_animation')"},
            ],
        },
        {
            # Five slots, laid out as the 3D Viewport Pie Menus version is:
            # the two "set" actions on the right, the three "clear" ones on
            # the left, and the bottom kept empty so a mis-flick does nothing.
            "name": "Object Parenting",
            "idname": "COCOPIE_MT_object_parenting",
            "keymap_type": "OBJECT_MODE", "keymap_scopes": ["OBJECT_MODE"],
            "key": "P",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Clear Parent", "icon": "X", "position": 0, "enabled": True,
                 "command": "bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')"},
                {"label": "Set Parent", "icon": "CON_CHILDOF", "position": 1, "enabled": True,
                 "command": "bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)"},
                {"label": "Clear Parent (Without Correction)", "icon": "UNLINKED",
                 "position": 4, "enabled": True,
                 "command": "bpy.ops.object.parent_clear(type='CLEAR')"},
                # INVOKE_DEFAULT rather than a plain call: it is what makes
                # parent_set raise its own type menu instead of silently
                # running with whatever type was last used. A positional
                # argument does not parse as a native button, so this slot
                # runs through cocopie.execute_command -- which is fine, and
                # is the whole reason that fallback path exists.
                {"label": "Set Parent (Advanced)", "icon": "CON_CHILDOF",
                 "position": 5, "enabled": True,
                 "command": "bpy.ops.object.parent_set('INVOKE_DEFAULT')"},
                {"label": "Clear Offset Correction", "icon": "DRIVER_DISTANCE",
                 "position": 6, "enabled": True,
                 "command": "bpy.ops.object.parent_clear(type='CLEAR_INVERSE')"},
            ],
        },
        # --- Sculpt Brush Select -------------------------------------------
        # One entry pie on W plus four sub-pies it opens. There are far more
        # than eight sculpt brushes, so they are grouped by family exactly as
        # the 3D Viewport Pie Menus version groups them. The four sub-pies
        # carry no shortcut of their own on purpose: they are reached only
        # from the entry pie, and a pie with no key registers as a menu with
        # no keymap item (see register_pie_menus).
        {
            "name": "Sculpt Brush Select",
            "idname": "COCOPIE_MT_sculpt_brush_select",
            "keymap_type": "SCULPT", "keymap_scopes": ["SCULPT"], "key": "W",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": [
                {"label": "Transform Brushes...", "icon": "brush:snake_hook",
                 "position": 0, "enabled": True,
                 "command": _sub_pie_command("COCOPIE_MT_sculpt_brush_transform")},
                {"label": "Volume Brushes...", "icon": "brush:blob",
                 "position": 1, "enabled": True,
                 "command": _sub_pie_command("COCOPIE_MT_sculpt_brush_volume")},
                # Bottom is left empty: the original puts Blender's brush
                # asset-shelf popup selector here, which is a UI widget rather
                # than a command and has no slot equivalent.
                {"label": "Mask", "icon": "brush:mask", "position": 3, "enabled": True,
                 "command": _sculpt_brush_command("Mask")},
                {"label": "Grab", "icon": "brush:grab", "position": 4, "enabled": True,
                 "command": _sculpt_brush_command("Grab")},
                {"label": "Draw", "icon": "brush:draw", "position": 5, "enabled": True,
                 "command": _sculpt_brush_command("Draw")},
                {"label": "Contrast Brushes...", "icon": "brush:flatten",
                 "position": 6, "enabled": True,
                 "command": _sub_pie_command("COCOPIE_MT_sculpt_brush_contrast")},
                {"label": "Special Brushes...", "icon": "brush:draw_face_sets",
                 "position": 7, "enabled": True,
                 "command": _sub_pie_command("COCOPIE_MT_sculpt_brush_special")},
            ],
        },
        {
            "name": "Sculpt Brushes: Transform",
            "idname": "COCOPIE_MT_sculpt_brush_transform",
            "keymap_type": "SCULPT", "keymap_scopes": ["SCULPT"], "key": "",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": _brush_slots([
                (0, "Elastic Grab", 'brush:elastic_deform'),
                (1, "Nudge", 'brush:nudge'),
                (2, "Relax Slide", 'brush:topology'),
                (3, "Snake Hook", 'brush:snake_hook'),
                (4, "Twist", 'brush:rotate'),
                (5, "Pose", 'brush:pose'),
                (6, "Pinch/Magnify", 'brush:pinch'),
                (7, "Thumb", 'brush:thumb'),
            ]),
        },
        {
            "name": "Sculpt Brushes: Volume",
            "idname": "COCOPIE_MT_sculpt_brush_volume",
            "keymap_type": "SCULPT", "keymap_scopes": ["SCULPT"], "key": "",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": _brush_slots([
                (0, "Blob", 'brush:blob'),
                (1, "Clay", 'brush:clay'),
                (2, "Inflate/Deflate", 'brush:inflate'),
                (3, "Draw Sharp", 'brush:draw_sharp'),
                (4, "Clay Strips", 'brush:clay_strips'),
                (5, "Crease Polish", 'brush:crease'),
                (6, "Clay Thumb", 'brush:clay_thumb'),
                (7, "Layer", 'brush:layer'),
            ]),
        },
        {
            "name": "Sculpt Brushes: Contrast",
            "idname": "COCOPIE_MT_sculpt_brush_contrast",
            "keymap_type": "SCULPT", "keymap_scopes": ["SCULPT"], "key": "",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": _brush_slots([
                (0, "Flatten/Contrast", 'brush:flatten'),
                (1, "Scrape/Fill", 'brush:scrape'),
                (2, "Fill/Deepen", 'brush:fill'),
                (3, "Scrape Multiplane", 'brush:multiplane_scrape'),
                (6, "Smooth", 'brush:smooth'),
            ]),
        },
        {
            "name": "Sculpt Brushes: Special",
            "idname": "COCOPIE_MT_sculpt_brush_special",
            "keymap_type": "SCULPT", "keymap_scopes": ["SCULPT"], "key": "",
            "ctrl": False, "shift": False, "alt": False,
            "enabled": True,
            "items": _brush_slots([
                (0, "Grab Cloth", 'brush:cloth'),
                (1, "Erase Multires Displacement", 'brush:displacement_eraser'),
                (2, "Density", 'brush:simplify'),
                (3, "Paint Soft", 'brush:paint'),
                (4, "Smear", 'brush:smear'),
                (5, "Face Set Paint", 'brush:draw_face_sets'),
                (6, "Boundary", 'brush:boundary'),
                (7, "Smear Multires Displacement", 'brush:displacement_smear'),
            ]),
        },
    ]


def _seeded_starter_names(prefs):
    """Names of the starter pies this configuration has already been given"""
    raw = getattr(prefs, "seeded_starters", "") or ""
    if not raw:
        return set()
    try:
        names = json.loads(raw)
    except ValueError:
        return set()
    return set(names) if isinstance(names, list) else set()


def _record_seeded_starters(prefs, names):
    """Remember these starter names as already given, additively"""
    if not hasattr(prefs, "seeded_starters"):
        return
    prefs.seeded_starters = json.dumps(sorted(_seeded_starter_names(prefs) | set(names)))


# Blender's own X in mesh/curve edit opens a delete menu on PRESS, and a PRESS
# binding is resolved before a CLICK/CLICK_DRAG one can be considered -- so the
# two delete starters cannot own X by sitting above it (measured: CocoPies at
# Mesh[9]/[10], Blender at Mesh[112], Blender still won). They ship with that
# binding suppressed instead, which is what makes Quick Tap work the moment
# they are seeded rather than after the user finds the checkbox.
#
# Only ever seeded alongside the starter that needs it, and only when it is not
# recorded already, so a user who unticks the box does not get it back at the
# next startup. Tuple order matches utils.binding_identity().
STARTER_SUPPRESSIONS = {
    "Mesh Delete": ("Mesh", "wm.call_menu", "X", "PRESS",
                    "VIEW3D_MT_edit_mesh_delete", False, False, False, False, False),
    "Curve Delete": ("Curve", "wm.call_menu", "X", "PRESS",
                     "VIEW3D_MT_edit_curve_delete", False, False, False, False, False),
}


def seed_starter_suppression(prefs, starter_name):
    """Record the keymap suppression a freshly seeded starter needs, if any."""
    identity = STARTER_SUPPRESSIONS.get(starter_name)
    if identity is None:
        return False
    from .utils import find_suppression, record_prior_state
    if find_suppression(prefs, identity) is not None:
        return False
    entry = prefs.suppressed_bindings.add()
    (entry.keymap, entry.idname, entry.key_type, entry.value, entry.menu_name,
     entry.any_modifier, entry.shift, entry.ctrl, entry.alt,
     entry.oskey) = identity
    # Asked now, while the binding still has whatever state the user left it
    # in. A user who had already switched Blender's X delete off by hand keeps
    # it off when CocoPies is later removed.
    record_prior_state(prefs, entry)
    return True


def migrate_starter_suppressions(prefs):
    """Backfill suppressions for delete starters seeded before they existed.

    Runs once. A configuration that already holds "Mesh Delete" is recorded as
    seeded, so sync_starter_pies() correctly declines to touch it -- which
    would otherwise leave every existing install with the pie but not the
    keymap suppression that makes its Quick Tap actually fire.
    """
    if getattr(prefs, "starter_suppressions_migrated", False):
        return 0
    names = {pie.name for pie in prefs.pie_menus}
    added = sum(1 for name in STARTER_SUPPRESSIONS
                if name in names and seed_starter_suppression(prefs, name))
    try:
        prefs.starter_suppressions_migrated = True
    except AttributeError:
        pass
    return added


def ensure_default_pies(prefs):
    """Add any starter pie that isn't present, and return how many were added.

    Matched by name, so a starter pie the user has renamed or edited is never
    resurrected or overwritten -- only genuinely missing ones are added. On a
    fresh install that means all of them.

    This is the *deliberate* restore, behind the Restore Starter Pies button:
    it brings a deleted starter back regardless of having been seeded before.
    Automatic seeding at startup goes through sync_starter_pies() instead.
    """
    existing = {pie.name for pie in prefs.pie_menus}
    definitions = default_pie_definitions(bundled_script_paths())
    added = 0

    for definition in definitions:
        if definition["name"] in existing:
            continue

        pie = prefs.pie_menus.add()
        pie.name = definition["name"]
        _apply_pie_dict(pie, definition)
        # Added as we go, not just read once up front: two definitions sharing
        # a name would otherwise both pass the check and seed two pies. That
        # happened -- a second Mesh Delete was added to this list beside the
        # one already here, and a fresh install got both.
        existing.add(definition["name"])
        seed_starter_suppression(prefs, definition["name"])
        added += 1

    _record_seeded_starters(prefs, [d["name"] for d in definitions])
    return added


def sync_starter_pies(prefs):
    """Add starter pies this configuration has never been given, and return
    how many were added.

    Runs at startup, and is what makes a new starter shipped by an update turn
    up on its own rather than waiting for the user to press Restore Starter
    Pies. It is deliberately *not* "add whatever is missing": a starter the
    user deleted on purpose is already recorded as seeded, so it stays gone
    instead of returning at every startup.

    One-off consequence of introducing that record: on the first startup after
    this change, an existing configuration has an empty record, so any starter
    it is missing counts as never-seen and is added -- including one deleted
    before the record existed. It only happens that once; after it, deletions
    stick.
    """
    definitions = default_pie_definitions(bundled_script_paths())
    seeded = _seeded_starter_names(prefs)
    existing = {pie.name for pie in prefs.pie_menus}
    added = 0

    for definition in definitions:
        name = definition["name"]
        if name in seeded or name in existing:
            continue

        pie = prefs.pie_menus.add()
        pie.name = name
        _apply_pie_dict(pie, definition)
        # See ensure_default_pies: kept current so two definitions sharing a
        # name cannot both seed
        existing.add(name)
        seed_starter_suppression(prefs, name)
        added += 1

    _record_seeded_starters(prefs, [d["name"] for d in definitions])
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
