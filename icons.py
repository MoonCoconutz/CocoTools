"""Row state dots generated from the user's theme.

A UIList cannot paint its own row background, so the "this row is selected"
cue has to live in an icon. Blender has no built-in icon in the theme's
selection colour, so we generate one: a filled dot in exactly the colour the
outliner uses for selected / active objects.
"""

import bpy
import bpy.utils.previews

SIZE = 16

# Blender defaults, used only if the theme cannot be read.
_FALLBACK_SELECTED = (0.929, 0.620, 0.243)
_FALLBACK_ACTIVE = (1.000, 0.667, 0.251)
_EMPTY_COLOR = (0.45, 0.45, 0.45)

_pcoll = None
_signature = None
_rebuild_queued = False


def _theme_colors():
    """(selected, active) straight from the outliner theme."""
    try:
        outliner = bpy.context.preferences.themes[0].outliner
        return (
            tuple(round(c, 4) for c in outliner.selected_object[:3]),
            tuple(round(c, 4) for c in outliner.active_object[:3]),
        )
    except Exception:
        return _FALLBACK_SELECTED, _FALLBACK_ACTIVE


def _dot(color, filled=True):
    """Flat RGBA float list for a soft-edged dot."""
    centre = (SIZE - 1) / 2.0
    outer = SIZE * 0.30
    inner = SIZE * 0.17
    pixels = []
    for y in range(SIZE):
        for x in range(SIZE):
            dist = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            disc = min(1.0, max(0.0, outer + 0.5 - dist))
            if filled:
                alpha = disc
            else:
                hole = min(1.0, max(0.0, inner + 0.5 - dist))
                alpha = max(0.0, disc - hole)
            pixels.extend((color[0], color[1], color[2], alpha))
    return pixels


def _build():
    global _pcoll, _signature

    _free()
    selected, active = _theme_colors()
    _pcoll = bpy.utils.previews.new()
    for key, color, filled in (
        ("selected", selected, True),
        ("active", active, True),
        ("empty", _EMPTY_COLOR, False),
    ):
        preview = _pcoll.new(key)
        preview.image_size = (SIZE, SIZE)
        preview.image_pixels_float = _dot(color, filled)
    _signature = (selected, active)


def _free():
    global _pcoll, _signature
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:
            pass
    _pcoll = None
    _signature = None


def _rebuild_timer():
    global _rebuild_queued
    _rebuild_queued = False
    _build()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return None


def icon_id(state):
    """Icon for 'selected' / 'active' / 'empty'. Safe to call from draw().

    Never rebuilds during a draw pass - a theme change only schedules the
    rebuild, so we are not mutating preview data mid-redraw.
    """
    global _rebuild_queued

    if _pcoll is None:
        return 0

    if _signature != _theme_colors() and not _rebuild_queued:
        _rebuild_queued = True
        try:
            bpy.app.timers.register(_rebuild_timer, first_interval=0.0)
        except Exception:
            _rebuild_queued = False

    try:
        return _pcoll[state].icon_id
    except KeyError:
        return 0


def register():
    _build()


def unregister():
    global _rebuild_queued
    if _rebuild_queued:
        try:
            bpy.app.timers.unregister(_rebuild_timer)
        except Exception:
            pass
        _rebuild_queued = False
    _free()
