import bpy

from .properties import COCOPIE_KeymapScope, COCOPIE_PieMenuItem, COCOPIE_PieMenuData
from .preferences import COCOPIE_AddonPreferences
from .defaults import COCOPIE_OT_restore_defaults, ensure_default_pies, sync_starter_pies
from .keymaps import register_pie_menus, unregister_pie_menus
from .utils import get_prefs
from .ui import COCOPIE_UL_pie_menus, GROUP_UILISTS
from .previews import register_previews, unregister_previews
from .operators import (
    COCOPIE_OT_execute_command,
    COCOPIE_OT_tap_toggle_direction,
    COCOPIE_OT_hold_or_tap,
    COCOPIE_OT_select_pie,
    COCOPIE_OT_add_pie_menu,
    COCOPIE_OT_remove_pie_menu,
    COCOPIE_OT_duplicate_pie_menu,
    COCOPIE_OT_remove_item,
    COCOPIE_OT_move_pie_menu,
    COCOPIE_OT_add_keymap_scope,
    COCOPIE_OT_remove_keymap_scope,
    COCOPIE_OT_save_preset,
    COCOPIE_OT_resolve_preset_conflict,
    COCOPIE_OT_load_preset,
    COCOPIE_OT_test_pie_menu,
    COCOPIE_OT_refresh_menus,
    COCOPIE_OT_edit_item_command,
    COCOPIE_OT_pick_script,
    COCOPIE_OT_refresh_icons,
    COCOPIE_OT_select_icon,
    COCOPIE_OT_set_icon_choice,
    COCOPIE_MT_add_to_cocopie,
    DIRECTION_MENUS,
    COCOPIE_OT_add_operator_to_pie,
    menu_func_context,
)


# Order matters: the property groups a later class refers to must already be
# registered, and the preferences class refers to both of them.
classes = (
    COCOPIE_KeymapScope,
    COCOPIE_PieMenuItem,
    COCOPIE_PieMenuData,
    COCOPIE_UL_pie_menus,
    COCOPIE_OT_restore_defaults,
    COCOPIE_OT_select_pie,
    COCOPIE_OT_execute_command,
    COCOPIE_OT_tap_toggle_direction,
    COCOPIE_OT_hold_or_tap,
    COCOPIE_OT_add_pie_menu,
    COCOPIE_OT_remove_pie_menu,
    COCOPIE_OT_duplicate_pie_menu,
    COCOPIE_OT_remove_item,
    COCOPIE_OT_move_pie_menu,
    COCOPIE_OT_add_keymap_scope,
    COCOPIE_OT_remove_keymap_scope,
    COCOPIE_OT_save_preset,
    COCOPIE_OT_resolve_preset_conflict,
    COCOPIE_OT_load_preset,
    COCOPIE_OT_test_pie_menu,
    COCOPIE_OT_refresh_menus,
    COCOPIE_OT_edit_item_command,
    COCOPIE_OT_pick_script,
    COCOPIE_OT_refresh_icons,
    COCOPIE_OT_select_icon,
    COCOPIE_OT_set_icon_choice,
    COCOPIE_MT_add_to_cocopie,
    COCOPIE_OT_add_operator_to_pie,
    COCOPIE_AddonPreferences,
) + DIRECTION_MENUS \
  + tuple(GROUP_UILISTS.values())  # one list class per Pie Menus section

# Set by the first register() of this Blender session. See the comment in
# register() -- this is what stops a re-enable from being read as a fresh
# install and overwriting the user's pies with starters.
_seeded_this_session = False

# Blender 5.0 renamed the button context menu; 4.x still uses the old name
CONTEXT_MENU_CLASSES = (
    'UI_MT_button_context_menu',
    'WM_MT_button_context',
)


def _scrub_context_menu_entries(menu):
    """Strip every previously-appended copy of our context-menu entry.

    Matched by name and module rather than by object identity, because
    "Reload Scripts" on a *package* addon does not necessarily reload every
    submodule (see the project's own reload notes) -- a stale draw callback
    left over from an earlier module instance can be a different function
    object with the same __name__/__module__, which plain .remove(func)
    would not find. Left unscrubbed, that stale entry keeps drawing forever,
    which is what produced the duplicate "Add to CocoPies" rows.
    """
    draw_funcs = menu._dyn_ui_initialize()
    draw_funcs[:] = [
        fn for fn in draw_funcs
        if not (
            getattr(fn, '__name__', None) == 'menu_func_context'
            and getattr(fn, '__module__', '') == menu_func_context.__module__
        )
    ]


def register():
    # Before the classes, so anything drawing a slot arrow already has it
    register_previews()

    for cls in classes:
        bpy.utils.register_class(cls)

    registered = False
    for menu_class in CONTEXT_MENU_CLASSES:
        try:
            if hasattr(bpy.types, menu_class):
                menu = getattr(bpy.types, menu_class)
                _scrub_context_menu_entries(menu)
                menu.append(menu_func_context)
                registered = True
                break
        except Exception as e:
            print(f"CocoPies: Could not register to {menu_class}: {e}")

    if not registered:
        print("CocoPies: Context menu not available - use manual Add Item button")

    # Lay down any starter pie this configuration has never been given -- all
    # of them on a fresh install, and just the new ones after an update that
    # ships more (sync_starter_pies keeps the record of which have been given,
    # so a starter deleted on purpose stays deleted).
    #
    # Guarded by a session flag, because "no pie menus" does not only mean
    # "fresh install". Disabling the addon makes Blender drop its whole entry
    # from preferences.addons, stored pie menus and all; re-enabling builds a
    # blank one -- with an empty seeded record too, so it looks exactly like a
    # first run. register() would then seed starters into what is really a
    # user's full configuration from a moment ago, overwriting their pies with
    # same-named starters -- which is exactly what looked for a long time like
    # Blender corrupting data across a reload. Their real pies are still in the
    # saved preferences on disk, so the recoverable outcome is to leave the
    # list empty and say so, rather than to write starters over the top and let
    # a later save make it permanent. Only the first register() of a session
    # may ever seed.
    global _seeded_this_session
    prefs = get_prefs()
    if prefs is not None:
        if not _seeded_this_session:
            try:
                added = sync_starter_pies(prefs)
                if added:
                    print(f"CocoPies: added {added} starter pie menu(s)")
            except Exception as e:
                print(f"CocoPies: could not create the starter pie menus: {e}")
        elif len(prefs.pie_menus) == 0:
            print("CocoPies: no pie menus in memory after a re-enable. Your saved "
                  "pies are still on disk -- restart Blender to load them. "
                  "Not recreating the starter pies, which would overwrite them.")
        # Set even when nothing was seeded: a later re-enable in this same
        # session must never be mistaken for a first run.
        _seeded_this_session = True

    register_pie_menus()


def unregister():
    for menu_class in CONTEXT_MENU_CLASSES:
        try:
            if hasattr(bpy.types, menu_class):
                _scrub_context_menu_entries(getattr(bpy.types, menu_class))
        except Exception:
            pass  # Silently ignore if not registered

    unregister_pie_menus()

    # Keep going if one class will not unregister. A class can already be gone
    # -- a second copy of the addon registering the same bl_idnames makes
    # Blender drop the first copy's -- and letting that raise here would skip
    # every remaining class, leaving the addon half-registered and unable to
    # cleanly register again.
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"CocoPies: could not unregister {getattr(cls, '__name__', cls)}: {e}")

    unregister_previews()


if __name__ == "__main__":
    register()
