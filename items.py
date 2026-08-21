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

# The slot-picker popup holds nothing but the 3x3 compass, so it is sized to
# come out square rather than to fit any text.
#
# invoke_popup()'s width and a row's scale_y are both expressed in the same
# unscaled units (Blender applies the UI scale to each afterwards), so the
# width that squares the popup can be derived instead of guessed: three rows
# of GRID_CELL_SCALE_Y * UI_UNIT_Y, plus the popup's own padding and the two
# separator lines between the rows (measured at ~24 units together).
GRID_CELL_SCALE_Y = 2.0
_UI_UNIT_Y = 20
_GRID_CHROME_UNITS = 24
GRID_POPUP_WIDTH = int(3 * GRID_CELL_SCALE_Y * _UI_UNIT_Y + _GRID_CHROME_UNITS)

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

# Width of the two icon-only tool buttons. An icon-only button collapses to
# its content rather than expanding to fill its share of the row, so this has
# to be sized to the buttons -- anything larger is dead space trailing after
# them, not wider buttons.
COL_TOOLS_UNITS = 2.3



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
