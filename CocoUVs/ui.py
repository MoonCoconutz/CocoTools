"""The CocoUVs tab in the UV Editor sidebar: UV Maps, Texel Density, Checker
Map, Trims and Debug. The tab name comes from the add-on preferences; an empty name
leaves the panels unregistered."""

import bpy
from bpy.types import Panel

from . import checker, common, debug, heatmap, trims, uv_sets

PIN_ROOM = 3.0   # separator factor: the width of the header pin


class _CocoUVsPanel:
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "CocoUVs"

    @classmethod
    def poll(cls, context):
        return context.space_data.mode == 'UV' and common.has_targets(context)


def _room_for_pin(panel):
    """A pinned panel gets a pin drawn at the right end of its header, on top
    of whatever draw_header_preset put there: leave it its room."""
    if panel.use_pin:
        panel.layout.separator(factor=PIN_ROOM)


class COCOUVS_PT_uv_maps(_CocoUVsPanel, Panel):
    bl_idname = "COCOUVS_PT_uv_maps"
    bl_label = "UV Maps"

    def draw_header_preset(self, context):
        # Right-hand end of the panel header.
        self.layout.prop(context.scene.cocouvs, "update_seams", text="Seams Update")
        _room_for_pin(self)

    def draw(self, context):
        layout = self.layout
        objects = common.target_objects(context)
        # The list holds every UV map name on any selected object; if that
        # changed, a timer rewrites it (a draw call may not write ID data).
        uv_sets.request_sync(uv_sets.union_names(objects))
        counts = uv_sets.active_map_counts(objects)
        uv_sets.set_row_state(counts, len(objects), uv_sets.chosen_name(counts, objects))

        row = layout.row()
        row.template_list(
            "COCOUVS_UL_uv_maps", "",
            context.window_manager, "cocouvs_uv_list",
            context.scene.cocouvs, "uv_index",
            rows=4,
        )
        side = row.column(align=True)
        side.operator("cocouvs.uv_add", text="", icon='ADD')
        side.operator("cocouvs.uv_remove", text="", icon='REMOVE')
        side.separator()
        side.operator("cocouvs.uv_move_up", text="", icon='TRIA_UP')
        side.operator("cocouvs.uv_move_down", text="", icon='TRIA_DOWN')
        side.separator()
        # A popover opens anchored under the button, like CocoBackup's menu.
        side.popover("COCOUVS_PT_rename", text="", icon='GREASEPENCIL')

        count = len({obj.data for obj in objects})
        if count > 1:
            info = layout.row()
            info.active = False
            info.label(text=f"Changes apply to {count} meshes", icon='INFO')


class COCOUVS_PT_texel_density(_CocoUVsPanel, Panel):
    bl_idname = "COCOUVS_PT_texel_density"
    bl_label = "Texel Density"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.cocouvs

        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(settings, "texture_size", text="Texture")

        # No property split on this row: in a narrow sidebar the split label
        # squeezed the unit dropdown down to "p...". The label goes inside the
        # number field instead.
        layout.use_property_split = False
        row = layout.row(align=True)
        row.operator("cocouvs.select_by_density", text="", icon='RESTRICT_SELECT_OFF')
        row.prop(settings, "density", text="Density")
        sub = row.row(align=True)
        sub.ui_units_x = 3.5
        sub.prop(settings, "unit", text="")
        layout.operator("cocouvs.calculate_density", text="Pick Texel Density", icon='EYEDROPPER')

        row = layout.row(align=True)
        label = row.row()
        label.ui_units_x = 3.0
        label.label(text="Apply")
        row.operator("cocouvs.assign_density_per_island", text="Islands")
        row.operator("cocouvs.assign_density_average", text="Average")

        layout.separator()
        wm = context.window_manager
        layout.prop(wm, "cocouvs_heatmap", text="Show Heatmap", toggle=True, icon='COLOR')
        if wm.cocouvs_heatmap:
            values = heatmap.legend()
            col = layout.column(align=True)
            if values is None:
                col.label(text="No UVs to show")
            else:
                low, high, uniform = values
                if uniform:
                    col.label(text=f"Uniform  {common.format_density(high, settings.unit)}", icon='STRIP_COLOR_04')
                else:
                    col.label(text=f"Lowest   {common.format_density(low, settings.unit)}", icon='STRIP_COLOR_01')
                    col.label(text=f"Highest  {common.format_density(high, settings.unit)}", icon='STRIP_COLOR_04')


class COCOUVS_PT_trims(_CocoUVsPanel, Panel):
    bl_idname = "COCOUVS_PT_trims"
    bl_label = "Trims"

    def draw_header_preset(self, context):
        self.layout.prop(context.window_manager, "cocouvs_trims_show", text="",
                         icon='HIDE_OFF' if context.window_manager.cocouvs_trims_show else 'HIDE_ON',
                         emboss=False)
        # A little room after it, so it sits left of the header's drag handle.
        self.layout.separator(factor=1.5)
        _room_for_pin(self)

    def draw(self, context):
        layout = self.layout
        # Unfold needs no material, so it sits above the material check.
        row = layout.row(align=True)
        row.operator("cocouvs.unfold_along_u", text="Unfold U")
        row.operator("cocouvs.unfold_along_v", text="Unfold V")

        mat = trims.material(context)
        if mat is None:
            layout.label(text="The active object has no material", icon='INFO')
            return

        row = layout.row()
        row.template_list("COCOUVS_UL_trims", "", mat, "cocouvs_trims", mat, "cocouvs_trim_index", rows=8)
        side = row.column(align=True)
        # + starts draw mode (never stops it); the next drag makes the area.
        side.operator("cocouvs.trim_draw", text="", icon='ADD').toggle = False
        side.operator("cocouvs.trim_add_selection", text="", icon='SELECT_SET')
        side.operator("cocouvs.trim_remove", text="", icon='REMOVE')
        side.operator("cocouvs.trim_clear", text="", icon='TRASH')
        side.separator()
        side.operator("cocouvs.trim_move_up", text="", icon='TRIA_UP')
        side.operator("cocouvs.trim_move_down", text="", icon='TRIA_DOWN')
        side.separator()
        side.operator("cocouvs.trim_export", text="", icon='EXPORT')
        side.operator("cocouvs.trim_import", text="", icon='IMPORT')

        drawing = trims.is_drawing()
        layout.operator("cocouvs.trim_draw", text="Finish Drawing" if drawing else "Draw Areas",
                        icon='GREASEPENCIL', depress=drawing)

        area = trims.picked_area(context)
        if area is not None:
            # A dropdown: three expanded buttons cut "Horizontal" off in the sidebar.
            row = layout.row(align=True)
            row.prop(area, "tiling", text="Tiling")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("cocouvs.trim_fit_tile", text="Fit + Tile")
        row.operator("cocouvs.trim_fit_inside", text="Fit Inside")
        row = col.row(align=True)
        row.operator("cocouvs.trim_fill", text="Fill")
        row.operator("cocouvs.trim_move_islands", text="Move")
        row = layout.row()
        settings = context.scene.cocouvs
        # Short labels: three full names are cut off at the sidebar's usual width
        row.prop(settings, "trim_rotate", text="Rotate")
        row.prop(settings, "trim_randomize", text="Random")
        row.prop(settings, "trim_stack")


class COCOUVS_PT_debug(_CocoUVsPanel, Panel):
    bl_idname = "COCOUVS_PT_debug"
    bl_label = "Debug"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        row = layout.row(align=True)
        row.operator("cocouvs.add_done", text="Add Done", icon='ADD')
        row.operator("cocouvs.remove_done", text="Remove Done", icon='REMOVE')

        col = layout.column(align=True)
        for kind in debug.FACE_KINDS:
            label, icon, _slot = debug.KIND_INFO[kind]
            prop = f"cocouvs_debug_{kind.lower()}"
            text = label
            if getattr(wm, prop):
                n = debug.found(kind)
                if n is not None:
                    text = f"{label}  ({n})"
            row = col.row(align=True)
            row.operator(debug.SELECT_OPERATORS[kind], text="", icon='RESTRICT_SELECT_OFF')
            row.prop(wm, prop, text=text, toggle=True, icon=icon)
        row = col.row(align=True)
        row.operator(debug.SELECT_OPERATORS['EDGES'], text="", icon='RESTRICT_SELECT_OFF')
        row.prop(wm, "cocouvs_debug_edges", text="Seams / Crease / Sharp / Bevel", toggle=True, icon='EDGESEL')


class COCOUVS_PT_checker(_CocoUVsPanel, Panel):
    bl_idname = "COCOUVS_PT_checker"
    bl_label = "Checker Map"

    def draw(self, context):
        settings = context.scene.cocouvs
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.operator("cocouvs.checker_toggle", text="", icon='TEXTURE', depress=checker.is_on())
        row.prop(settings, "checker_size", text="")
        row.operator("cocouvs.checker_import", text="", icon='FILEBROWSER')
        # The map name gets its own row so nothing is cut off in a narrow sidebar.
        col.prop(settings, "checker_map", text="")


# Registration order is the order in the sidebar (the user's).
classes = (COCOUVS_PT_uv_maps, COCOUVS_PT_texel_density, COCOUVS_PT_checker, COCOUVS_PT_trims,
           COCOUVS_PT_debug)


def tab_name():
    """The sidebar tab from the add-on preferences (default "CocoUVs")."""
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences.tab_name if addon is not None else "CocoUVs"


_registered = []


def update_tab(_self=None, _context=None):
    """Re-register the panels under the current tab name (none if empty)."""
    for cls in reversed(_registered):
        bpy.utils.unregister_class(cls)
    _registered.clear()
    name = tab_name().strip()
    if not name:
        return
    for cls in classes:
        cls.bl_category = name
        bpy.utils.register_class(cls)
        _registered.append(cls)


def register():
    update_tab()


def unregister():
    for cls in reversed(_registered):
        bpy.utils.unregister_class(cls)
    _registered.clear()
