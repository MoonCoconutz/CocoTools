"""Constants: pie slot geometry, item row sizing, and the Blender keymap
each scope registers into."""

import bpy
import os
import json
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, FloatProperty,
)
from bpy.types import Operator, PropertyGroup, Menu, AddonPreferences


# Blender fills the eight pie slots in a fixed order:
#   0 West, 1 East, 2 South, 3 North, 4 North-West, 5 North-East,
#   6 South-West, 7 South-East
POSITION_ARROWS = {
    0: '←', 1: '→', 2: '↓', 3: '↑',
    4: '↖', 5: '↗', 6: '↙', 7: '↘',
}

POSITION_NAMES = {
    0: "Left", 1: "Right", 2: "Bottom", 3: "Top",
    4: "Top-Left", 5: "Top-Right", 6: "Bottom-Left", 7: "Bottom-Right",
}

# Row-major reading order of a 3x3 grid; None is the (inert) centre cell
POSITION_GRID = (4, 3, 5, 0, None, 1, 6, 2, 7)

_UI_UNIT_Y = 20

# One cell of the picker grid, square: UI_UNIT_X and UI_UNIT_Y are both
# widget_unit, so the same number gives a cell as wide as it is tall.
GRID_CELL_UNITS = 2.0

# The padding Blender puts around a popup's contents. Measured, since it is not
# exposed, and near enough the same on both axes.
_GRID_POPUP_PADDING = 1.2

# Three square cells plus that padding. The grid deliberately carries nothing
# between the rows: a separator line adds height without adding any width, and
# that alone is what made every earlier attempt at a square popup fail.
GRID_POPUP_WIDTH = int((3 * GRID_CELL_UNITS + _GRID_POPUP_PADDING) * _UI_UNIT_Y)

# Height of one item row, and the width of the two icon-only columns in it.
#
# UI_UNIT_X and UI_UNIT_Y are both Blender's widget_unit, so a row's scale_y
# and a column's ui_units_x are the same size in the same units: setting them
# to the same number is what makes the Pos and Icon buttons come out square.
# They are derived from one constant rather than set side by side so they
# cannot drift apart again. Both are fixed widths, so the buttons stay square
# no matter how wide the Preferences window is stretched.
ITEM_ROW_UNITS = 1.4

# Column widths shared by the item rows and their header, so the two line up
COL_CHECK_UNITS = 1.2
COL_POS_UNITS = ITEM_ROW_UNITS
COL_ICON_UNITS = ITEM_ROW_UNITS
COL_LABEL_SCALE = 1.8
COL_CMD_SCALE = 2.4

# Width of two icon-only buttons side by side. An icon-only button collapses to
# its content rather than expanding to fill its share of the row, so a slot
# holding two has to be sized to the buttons -- anything larger is dead space
# trailing after them, not wider buttons.
TWO_ICON_BUTTONS_UNITS = 2.3

COL_TOOLS_UNITS = TWO_ICON_BUTTONS_UNITS

# How many editor dropdowns sit side by side on one line in Settings. Each cell
# is a dropdown plus its remove button, so this is also how many of those pairs
# have to fit across the Settings box.
SCOPE_COLUMNS = 3


# Which Blender keymap each scope registers into: id -> (keymap name, space).
# Mode keymaps -- "Mesh", "UV Editor", "Sculpt" and friends -- are all
# space_type EMPTY; only whole-editor keymaps carry a space type of their own.
KEYMAP_CONFIG = {
    'WINDOW': ('Window', 'EMPTY'),

    # Modes. A pie scoped to one of these is live only in that mode, which is
    # what lets two pies share a key without fighting over it.
    'OBJECT_MODE': ('Object Mode', 'EMPTY'),
    'MESH': ('Mesh', 'EMPTY'),
    'CURVE': ('Curve', 'EMPTY'),
    'ARMATURE': ('Armature', 'EMPTY'),
    'POSE': ('Pose', 'EMPTY'),
    'SCULPT': ('Sculpt', 'EMPTY'),
    'VERTEX_PAINT': ('Vertex Paint', 'EMPTY'),
    'WEIGHT_PAINT': ('Weight Paint', 'EMPTY'),
    'IMAGE_PAINT': ('Image Paint', 'EMPTY'),
    'UV_EDITOR': ('UV Editor', 'EMPTY'),

    # Whole editors
    '3D_VIEW': ('3D View', 'VIEW_3D'),
    'IMAGE_EDITOR': ('Image', 'IMAGE_EDITOR'),
    'NODE_EDITOR': ('Node Editor', 'NODE_EDITOR'),
    'SEQUENCE_EDITOR': ('Sequencer', 'SEQUENCE_EDITOR'),
    'CLIP_EDITOR': ('Clip', 'CLIP_EDITOR'),
    'DOPESHEET_EDITOR': ('Dopesheet', 'DOPESHEET_EDITOR'),
    'GRAPH_EDITOR': ('Graph Editor', 'GRAPH_EDITOR'),
    'NLA_EDITOR': ('NLA Editor', 'NLA_EDITOR'),
    'TEXT_EDITOR': ('Text', 'TEXT_EDITOR'),
    'CONSOLE': ('Console', 'CONSOLE'),
    'INFO': ('Info', 'INFO'),
    'OUTLINER': ('Outliner', 'OUTLINER'),
    'PROPERTIES': ('Property Editor', 'PROPERTIES'),
    'FILE_BROWSER': ('File Browser', 'FILE_BROWSER'),
    'PREFERENCES': ('Preferences', 'PREFERENCES'),
}

# "Window (Global)" is not really global -- it registers the shortcut into each
# of these mode keymaps, which is why it collides with any pie scoped to one of
# them and with none of the editor-scoped ones.
WINDOW_MODE_KEYMAPS = (
    'Object Mode', 'Mesh', 'Curve', 'Armature', 'Pose',
    'Sculpt', 'Vertex Paint', 'Weight Paint', 'Image Paint',
)


# The Editor dropdown's contents, shared by a pie's legacy `keymap_type` and by
# every row in its `keymap_scopes` so the two can never drift apart. The bare
# ("", "Modes", "") entries are Blender's own way of writing a heading inside
# an enum dropdown -- they carry no identifier, so anything walking this list
# for real scopes has to skip the falsy ones.
KEYMAP_TYPE_ITEMS = [
    ('WINDOW', "Window (Global)",
     "Every 3D viewport mode - object, edit, sculpt and the paint modes"),

    ("", "Modes", ""),
    ('OBJECT_MODE', "Object Mode", "3D viewport, object mode only"),
    ('MESH', "Mesh (Edit Mode)", "3D viewport, mesh edit mode only"),
    ('CURVE', "Curve (Edit Mode)", "3D viewport, curve edit mode only"),
    ('ARMATURE', "Armature (Edit Mode)", "3D viewport, armature edit mode only"),
    ('POSE', "Pose Mode", "3D viewport, pose mode only"),
    ('SCULPT', "Sculpt Mode", "3D viewport, sculpt mode only"),
    ('VERTEX_PAINT', "Vertex Paint", "3D viewport, vertex paint mode only"),
    ('WEIGHT_PAINT', "Weight Paint", "3D viewport, weight paint mode only"),
    ('IMAGE_PAINT', "Texture Paint", "3D viewport, texture paint mode only"),
    ('UV_EDITOR', "UV Editor", "UV editing only, not the Image editor at large"),

    ("", "Editors", ""),
    ('3D_VIEW', "3D View", "3D Viewport, every mode"),
    ('IMAGE_EDITOR', "Image Editor", "Image Editor, including UV editing"),
    ('NODE_EDITOR', "Node Editor", "Node Editor/Shader Editor/Geometry Nodes"),
    ('SEQUENCE_EDITOR', "Sequencer", "Video Sequencer"),
    ('CLIP_EDITOR', "Movie Clip Editor", "Movie Clip Editor"),
    ('DOPESHEET_EDITOR', "Dope Sheet", "Dope Sheet"),
    ('GRAPH_EDITOR', "Graph Editor", "Graph Editor"),
    ('NLA_EDITOR', "NLA Editor", "NLA Editor"),
    ('TEXT_EDITOR', "Text Editor", "Text Editor"),
    ('CONSOLE', "Python Console", "Python Console"),
    ('INFO', "Info", "Info"),
    ('OUTLINER', "Outliner", "Outliner"),
    ('PROPERTIES', "Properties", "Properties"),
    ('FILE_BROWSER', "File Browser", "File Browser"),
    ('PREFERENCES', "Preferences", "Preferences"),
]
