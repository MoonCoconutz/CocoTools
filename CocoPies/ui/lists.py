"""One row of the Pie Menus list.

Drawn as ordinary rows in a column rather than through `template_list`.
`template_list` is Blender's only list widget, and it always renders inside a
box -- one box per section made the grouped list look like six stacked panels
rather than one list. Plain rows have no box at all, at the cost of the two
things only `template_list` provides: the native full-row selection highlight
(the active pie is shown with a depressed name button instead) and the
drag-to-resize grab handle (sections collapse instead, see
`COCOPIE_OT_toggle_group`).
"""

import bpy

from ..utils import format_shortcut, find_shortcut_conflicts


# Splits shared by every row, so the columns line up down the whole list
# regardless of how long any one pie's name is. Same proportions the
# template_list rows used, kept so the layout did not visibly shift.
NAME_SPLIT = 0.55
SHORTCUT_SPLIT = 0.58


def draw_pie_row(layout, prefs, pie, index, is_active):
    """One pie's row: enabled toggle, name, shortcut, duplicate and delete"""
    row = layout.row(align=False)
    row.scale_y = 1.2

    row.prop(pie, "enabled", text="",
             icon='CHECKBOX_HLT' if pie.enabled else 'CHECKBOX_DEHLT',
             emboss=False)

    name_shortcut_split = row.split(factor=NAME_SPLIT, align=True)

    # The name doubles as the row's select button. Embossed only while active:
    # an unembossed operator button reads as a plain label, so an inactive row
    # carries no button frame and the list stays flat, while the active one is
    # unmistakable. depress is what paints it in the theme's selected colour.
    name_col = name_shortcut_split.row(align=True)
    name_col.active = pie.enabled
    if is_active:
        # Renaming in place. Blender's double-click-to-rename belongs to
        # template_list, which this list deliberately is not (see the module
        # docstring), so the second click has to land on something already
        # editable: the selected row draws its name as the field itself.
        # Double-clicking an unselected row therefore still renames it --
        # the first click selects and redraws, the second lands in the field.
        #
        # A text field cannot carry the depressed selection colour the name
        # button used to, so the marker does it instead -- the row would
        # otherwise be the only one in the list with nothing showing it is
        # current. A box around the row was the alternative and was rejected:
        # it indents the row and reintroduces exactly the framing this list
        # exists to avoid.
        marker = name_col.row(align=True)
        marker.operator("cocopie.select_pie", text="", icon='LAYER_ACTIVE',
                        depress=True).index = index
        name_col.prop(pie, "name", text="")
    else:
        name_col.alignment = 'LEFT'
        op = name_col.operator("cocopie.select_pie",
                               text=pie.name or "Untitled",
                               emboss=False, depress=False)
        op.index = index

    shortcut_actions_split = name_shortcut_split.split(factor=SHORTCUT_SPLIT,
                                                       align=True)

    shortcut_col = shortcut_actions_split.row(align=True)
    shortcut_col.alignment = 'RIGHT'
    shortcut_col.active = pie.enabled
    if find_shortcut_conflicts(prefs, pie, index):
        warn = shortcut_col.row(align=True)
        warn.label(text="", icon='ERROR')
    shortcut_col.label(text=format_shortcut(pie))

    actions_col = shortcut_actions_split.row(align=True)
    actions_col.alignment = 'RIGHT'
    op = actions_col.operator("cocopie.duplicate_pie_menu", text="",
                              icon='DUPLICATE', emboss=False)
    op.index = index
    op = actions_col.operator("cocopie.remove_pie_menu", text="",
                              icon='TRASH', emboss=False)
    op.index = index
