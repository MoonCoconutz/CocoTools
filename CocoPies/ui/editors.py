"""The Editors popover: every editor a pie can live in, one checkbox each.

A popover rather than a Menu because a menu closes on the first click, and
picking editors usually means ticking several. Registered against the 3D
Viewport's header only because a Panel needs a space and a region; a header
panel is never drawn by itself, only when something calls layout.popover().
"""

from bpy.types import Panel

from ..items import KEYMAP_TYPE_ITEMS
from ..utils import get_prefs, ensure_keymap_scopes


def _sections():
    """KEYMAP_TYPE_ITEMS split at its headings: [(heading, [(id, name)])]"""
    sections = [("", [])]
    for item in KEYMAP_TYPE_ITEMS:
        if not item[0]:
            sections.append((item[1], []))
        else:
            sections[-1][1].append((item[0], item[1]))
    return [s for s in sections if s[1]]


def editors_summary(pie):
    """The popover button's text: the editor's name, or "Multiple".

    One fixed-width button cannot fit a list of names, and a cut-off list
    reads as if it were the whole of it.
    """
    scopes = {s.keymap_type for s in ensure_keymap_scopes(pie)}
    if len(scopes) > 1:
        return "Multiple"
    labels = dict((item[0], item[1]) for item in KEYMAP_TYPE_ITEMS if item[0])
    key = next(iter(scopes), "")
    return labels.get(key, key) or "None"


class COCOPIE_PT_editors(Panel):
    """Tick every editor this pie's shortcut should work in"""
    bl_idname = "COCOPIE_PT_editors"
    bl_label = "Editors"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 18

    def draw(self, context):
        prefs = get_prefs(context)
        if prefs is None or not (0 <= prefs.active_pie_index < len(prefs.pie_menus)):
            return
        pie_index = prefs.active_pie_index
        pie = prefs.pie_menus[pie_index]
        taken = {s.keymap_type for s in ensure_keymap_scopes(pie)}

        # Window (Global) on top, then Modes and Editors side by side
        sections = _sections()
        layout = self.layout
        top, rest = sections[0], sections[1:]
        self._draw_boxes(layout.column(align=True), top[1], taken, pie_index)
        layout.separator()
        row = layout.row()
        for heading, items in rest:
            col = row.column(align=True)
            col.label(text=heading)
            self._draw_boxes(col, items, taken, pie_index)

    @staticmethod
    def _draw_boxes(col, items, taken, pie_index):
        for key, name in items:
            on = key in taken
            cell = col.row(align=True)
            # Text next to its checkbox, not centred in the column
            cell.alignment = 'LEFT'
            # The last editor cannot be unticked (see toggle_keymap_scope)
            cell.enabled = not (on and len(taken) == 1)
            op = cell.operator("cocopie.toggle_keymap_scope", text=name,
                               icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT',
                               emboss=False)
            op.pie_index = pie_index
            op.keymap_type = key
