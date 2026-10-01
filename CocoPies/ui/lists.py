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

from ..utils import format_shortcut, find_shortcut_conflicts


# Splits shared by every row, so every piece of it lines up down the whole
# list regardless of how long any one pie's name is. Splits and not a row:
# a row shares out its width by what its items would like, so a name too long
# for its place squeezed everything else on its line -- the indent, the
# checkbox and the key cap all moved left, on that row only. A split's
# factor holds whatever is drawn in it; a long name is cut short instead.
# Duplicate and delete live in the toolbar above the list
# (draw_list_toolbar), acting on the selected pie.
CHECK_SPLIT = 0.1
NAME_SPLIT = 0.62


def draw_pie_row(layout, prefs, pie, index, is_active):
    """One pie's row: enabled toggle, name and shortcut"""
    row = layout.split(factor=CHECK_SPLIT)
    row.scale_y = 1.2

    # Pushed to the right of its cell, which indents it under the heading
    check = row.row()
    check.alignment = 'RIGHT'
    check.prop(pie, "enabled", text="",
               icon='CHECKBOX_HLT' if pie.enabled else 'CHECKBOX_DEHLT',
               emboss=False)

    name_shortcut_split = row.split(factor=NAME_SPLIT)

    # The name doubles as the row's select button, and the selected row has
    # two states. Selected: name and shortcut are both depressed, so the row
    # carries one unbroken band of the theme's selected colour -- `template_list`
    # draws a real row background and this list is deliberately not one (see
    # the module docstring), so the buttons have to be the highlight. Renaming:
    # the name half becomes the field, the shortcut half stays depressed so
    # the row still reads as current.
    #
    # Clicking the name of an already-selected row is what switches between
    # them, which makes a double-click on any row rename it: first click
    # selects, second lands on the name of what is now the selected row.
    name_col = name_shortcut_split.row(align=True)
    name_col.active = pie.enabled
    is_renaming = is_active and prefs.renaming_pie_index == index
    if is_renaming:
        # No focus call here on purpose. activate_init only applies inside a
        # popup, and Blender exposes no operator that puts a field into edit
        # mode, so the field cannot open with the cursor already in it -- the
        # click that lands on it is what focuses it. A rename popup was tried
        # instead, purely to get that focus, and rejected: it is a worse
        # trade than one extra click.
        name_col.prop(pie, "name", text="")
    else:
        # EXPAND on the selected row so the button fills its half rather than
        # shrinking to the text, which is what makes the band full width
        name_col.alignment = 'EXPAND' if is_active else 'LEFT'
        op = name_col.operator("cocopie.select_pie",
                               text=pie.name or "Untitled",
                               emboss=is_active, depress=is_active)
        op.index = index
        op.rename_if_active = True

    shortcut_col = name_shortcut_split.row(align=True)
    shortcut_col.active = pie.enabled
    if find_shortcut_conflicts(prefs, pie, index):
        warn = shortcut_col.row(align=True)
        warn.alignment = 'RIGHT'
        warn.label(text="", icon='ERROR')
    if is_active:
        # Carries the selected colour across the rest of the row. Selects
        # rather than renames, so a click aimed at the shortcut does not open
        # a field the user was not reaching for.
        shortcut_col.operator("cocopie.select_pie",
                              text=format_shortcut(pie),
                              depress=True).index = index
    else:
        # A key cap: an embossed button filling the shortcut's cell, which is
        # the same width on every row, so the caps line up down the list. A
        # button rather than a label so it selects the row like the name does.
        shortcut_col.operator("cocopie.select_pie",
                              text=format_shortcut(pie)).index = index
