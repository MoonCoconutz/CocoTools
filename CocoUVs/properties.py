"""Settings stored on the Scene, and the heatmap switch on the WindowManager
(so it is never saved into a file)."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup

from . import common

TEXTURE_SIZES = (256, 512, 1024, 2048, 4096, 8192)


def _uv_index_get(self):
    from . import uv_sets

    return uv_sets._uv_index_get(self)


def _uv_index_set(self, value):
    """Clicking a row makes that UV map active on every target mesh that has
    it (see uv_sets)."""
    from . import uv_sets

    uv_sets._uv_index_set(self, value)


def _density_get(self):
    return common.ppm_to_unit(self.density_ppm, self.unit)


def _density_set(self, value):
    self.density_ppm = value * common.UNIT_FACTORS[self.unit]


def _refresh_heatmap(self, context):
    from . import heatmap

    heatmap.mark_dirty()


def _checker_maps(self, context):
    from . import checker

    return checker._map_items(self, context)


def _checker_changed(self, context):
    from . import checker

    checker._settings_changed(self, context)


def _update_seams_changed(self, context):
    # Records the borders as they are now, so the next change is noticed
    from . import seams
    seams.request_follow()


class COCOUVS_Settings(PropertyGroup):
    checker_map: EnumProperty(
        name="Checker Map",
        description="Which checker map to show",
        items=_checker_maps,
        update=_checker_changed,
    )
    checker_size: EnumProperty(
        name="Checker Size",
        description="Resolution of the generated checker maps",
        items=[(str(s), f"{s} px", f"{s} x {s}") for s in TEXTURE_SIZES],
        default="1024",
        update=_checker_changed,
    )
    update_seams: BoolProperty(
        name="Update Seams",
        description="Keep the seams on the active UV map's island borders: when a map is picked "
        "or removed in the list, and in Edit Mode whenever the islands change (Rip, Unwrap, Stitch...)",
        default=False,
        update=_update_seams_changed,
    )
    trim_rotate: BoolProperty(
        name="Auto-rotate",
        description="Turn islands 90 degrees when needed so their long side runs along the trim",
        default=False,
    )
    trim_randomize: BoolProperty(
        name="Randomize",
        description="Shift each island a random amount along a repeating trim, "
        "so repeated pieces show different parts of it",
        default=False,
    )
    uv_index: IntProperty(
        name="Active UV Map",
        description="UV map shown as active; selecting one sets it on every selected mesh",
        get=_uv_index_get,
        set=_uv_index_set,
    )
    texture_size: EnumProperty(
        name="Texture Size",
        description="Resolution of the (square) texture the density is measured against",
        items=[(str(s), f"{s} px", f"{s} x {s} texture") for s in TEXTURE_SIZES],
        default="2048",
        update=_refresh_heatmap,
    )
    unit: EnumProperty(
        name="Unit",
        description="Unit texel density is shown and entered in",
        items=[
            ('PX_M', "px/m", "Pixels per metre"),
            ('PX_CM', "px/cm", "Pixels per centimetre"),
            ('PX_MM', "px/mm", "Pixels per millimetre"),
        ],
        default='PX_M',
        update=_refresh_heatmap,
    )
    # Stored in px/m so switching the unit converts the value rather than
    # reinterpreting the number.
    density_ppm: FloatProperty(default=1024.0, min=0.0)
    density: FloatProperty(
        name="Texel Density",
        description="Texel density to assign; Calculate fills it from the selected islands",
        get=_density_get,
        set=_density_set,
        min=0.0,
        soft_max=100000.0,
        precision=3,
        step=10,
    )


def _heatmap_update(self, context):
    from . import heatmap

    heatmap.set_enabled(self.cocouvs_heatmap)


classes = (COCOUVS_Settings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cocouvs = PointerProperty(type=COCOUVS_Settings)
    bpy.types.WindowManager.cocouvs_heatmap = BoolProperty(
        name="Texel Density Heatmap",
        description="Colour every island by its texel density, red lowest to green highest, "
        "in the UV Editor and on the model",
        default=False,
        update=_heatmap_update,
    )


def unregister():
    del bpy.types.WindowManager.cocouvs_heatmap
    del bpy.types.Scene.cocouvs
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
