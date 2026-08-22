"""Blender's icon catalogue, grouped into browsable categories."""

import bpy
import os
import json
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, FloatProperty,
)
from bpy.types import Operator, PropertyGroup, Menu, AddonPreferences


# ----------------------------------------------------------------------------
# Icon catalogue
# ----------------------------------------------------------------------------

# 4-tuples (no icon element) so the tab strip stays text-only and fits on one row
ICON_CATEGORY_ENUM = [
    ('ALL',      "All",       "Every icon Blender ships with",          0),
    ('MESH',     "Mesh",      "Mesh, geometry and selection icons",     1),
    ('OBJECT',   "Object",    "Object types and outliner icons",        2),
    ('MODIFIER', "Modifier",  "Modifiers, constraints and physics",     3),
    ('SHADING',  "Shading",   "Materials, nodes, lights and render",    4),
    ('ANIM',     "Anim",      "Animation, keyframes and playback",      5),
    ('COLOR',    "Color",     "Color sets, brushes and swatches",       6),
    ('FILE',     "File",      "Files, folders, import and export",      7),
    ('INPUT',    "Input",     "Keyboard, mouse and event icons",        8),
    ('UI',       "UI",        "Arrows, toggles and window chrome",      9),
    ('OTHER',    "Other",     "Everything that didn't fit elsewhere",  10),
    # Not one of Blender's own: these come from image files CocoPie loads
    ('CUSTOM',   "Custom",    "Your own icons, loaded from image files", 11),
]

# Evaluated in order — the first rule that matches an icon name wins.
_ICON_CATEGORY_RULES = (
    ('INPUT', {
        'prefixes': ('EVENT_', 'MOUSE_'),
        'exact': ('HAND',),
    }),
    ('MODIFIER', {
        'prefixes': ('MOD_', 'CON_', 'FORCE_', 'PHYSICS'),
        'exact': ('MODIFIER', 'MODIFIER_DATA', 'MODIFIER_OFF', 'MODIFIER_ON',
                  'CONSTRAINT', 'CONSTRAINT_BONE'),
    }),
    ('COLOR', {
        'prefixes': ('COLORSET_', 'BRUSH_', 'SEQUENCE_COLOR_', 'MATCLOTH',
                     'MATCUBE', 'MATFLUID', 'MATPLANE', 'MATSHADERBALL',
                     'MATSPHERE'),
        'exact': ('COLOR', 'COLOR_RED', 'COLOR_GREEN', 'COLOR_BLUE',
                  'EYEDROPPER', 'RESTRICT_COLOR_ON', 'RESTRICT_COLOR_OFF'),
    }),
    ('ANIM', {
        'prefixes': ('ANIM', 'KEYFRAME', 'KEYINGSET', 'KEY_', 'ACTION', 'DRIVER',
                     'IPO_', 'NLA', 'HANDLE_', 'FRAME_', 'PMARKER', 'MARKER',
                     'TRACK', 'CLIP', 'GRAPH', 'DECORATE', 'ONIONSKIN'),
        'exact': ('PLAY', 'PLAY_SOUND', 'PLAY_REVERSE', 'REC', 'FF', 'REW',
                  'PAUSE', 'PREV_KEYFRAME', 'NEXT_KEYFRAME', 'TIME',
                  'MUTE_IPO_ON', 'MUTE_IPO_OFF'),
    }),
    ('SHADING', {
        'prefixes': ('MATERIAL', 'SHADING_', 'SHADERFX', 'NODE', 'TEXTURE',
                     'WORLD', 'IMAGE', 'RENDER', 'SCENE', 'OUTPUT', 'LIGHT',
                     'CAMERA', 'SEQ_'),
        'exact': ('SMOOTH', 'SHADERFX', 'HOLDOUT_ON', 'HOLDOUT_OFF',
                  'INDIRECT_ONLY_ON', 'INDIRECT_ONLY_OFF'),
    }),
    ('MESH', {
        'prefixes': ('MESH_', 'VERTEXSEL', 'EDGESEL', 'FACESEL', 'UV', 'SNAP_',
                     'PIVOT_', 'ORIENTATION_', 'PROP_', 'AUTOMERGE_',
                     'EDITMODE_', 'VERTEX_', 'FACE_', 'EDGE_', 'CURVE_',
                     'SURFACE_', 'META_', 'NORMALS_'),
        'exact': ('XRAY', 'CENTER_ONLY', 'SPHERECURVE', 'ROOTCURVE',
                  'SHARPCURVE', 'SMOOTHCURVE', 'LINCURVE', 'NOCURVE',
                  'RNDCURVE', 'INVERSESQUARECURVE'),
    }),
    ('OBJECT', {
        'prefixes': ('OBJECT_', 'OUTLINER_', 'EMPTY_', 'ARMATURE_', 'BONE_',
                     'POSE_', 'GROUP', 'LATTICE_', 'FONT_', 'GP_',
                     'GREASEPENCIL', 'PARTICLE', 'SPEAKER', 'VIEW_',
                     'ORPHAN_', 'COLLECTION'),
        'exact': ('MESH', 'OBJECT_DATA', 'OBJECT_ORIGIN'),
    }),
    ('FILE', {
        'prefixes': ('FILE', 'FOLDER', 'NEWFOLDER', 'DISK_', 'DOCUMENTS',
                     'LIBRARY_', 'ASSET_', 'PACKAGE', 'UGLYPACKAGE'),
        'exact': ('IMPORT', 'EXPORT', 'BLENDER', 'CURRENT_FILE', 'FUND', 'URL',
                  'LINKED', 'UNLINKED', 'APPEND_BLEND', 'LINK_BLEND'),
    }),
    ('UI', {
        'prefixes': ('TRIA_', 'DISCLOSURE_', 'CHECKBOX_', 'RADIOBUT_', 'PANEL_',
                     'MENU_', 'WINDOW', 'WORKSPACE', 'SCREEN_', 'PREFERENCES',
                     'ARROW_', 'LOOP_', 'ZOOM_', 'FULLSCREEN_', 'SORT',
                     'FILTER', 'RESTRICT_', 'HIDE_', 'GHOST_', 'THREE_DOTS',
                     'BLANK', 'DOT', 'PASTE', 'COPY', 'PRESET', 'FAKE_USER_'),
        'exact': ('ADD', 'REMOVE', 'PLUS', 'X', 'CANCEL', 'ERROR', 'INFO',
                  'QUESTION', 'HELP', 'CHECKMARK', 'BACK', 'FORWARD',
                  'LOCKED', 'UNLOCKED', 'PINNED', 'UNPINNED', 'PIN',
                  'TRASH', 'DUPLICATE', 'VIEWZOOM', 'GRIP', 'SETTINGS',
                  'TOOL_SETTINGS', 'RIGHTARROW', 'LEFTARROW', 'DOWNARROW_HLT'),
    }),
)

# Populated lazily — Blender's icon enum isn't available at import time
_ICON_DATA = {"all": None, "lookup": None, "by_category": None}


def get_all_icons():
    """Every icon identifier Blender exposes to UILayout, minus 'NONE'"""
    if _ICON_DATA["all"] is None:
        try:
            params = bpy.types.UILayout.bl_rna.functions['prop'].parameters
            _ICON_DATA["all"] = [
                i.identifier for i in params['icon'].enum_items
                if i.identifier != 'NONE'
            ]
        except Exception:
            _ICON_DATA["all"] = ['QUESTION', 'MESH_CUBE', 'MESH_UVSPHERE',
                                 'LIGHT', 'CAMERA_DATA', 'BLANK1']
    return _ICON_DATA["all"]


def safe_icon(name, fallback='BLANK1'):
    """Never let a stale/unknown icon name break a whole draw() call"""
    if not name or name == 'NONE':
        return fallback
    if _ICON_DATA["lookup"] is None:
        _ICON_DATA["lookup"] = set(get_all_icons())
    return name if name in _ICON_DATA["lookup"] else fallback


def _classify_icon(name):
    for category, rules in _ICON_CATEGORY_RULES:
        if name in rules['exact'] or name.startswith(rules['prefixes']):
            return category
    return 'OTHER'


def get_icons_by_category():
    """Icon identifiers bucketed by category id (cached)"""
    if _ICON_DATA["by_category"] is None:
        buckets = {entry[0]: [] for entry in ICON_CATEGORY_ENUM}
        for name in get_all_icons():
            buckets[_classify_icon(name)].append(name)
        buckets['ALL'] = list(get_all_icons())
        _ICON_DATA["by_category"] = buckets
    return _ICON_DATA["by_category"]
