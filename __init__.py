bl_info = {
    "name": "CocoPie",
    "author": "Custom",
    "version": (1, 8, 0),
    "blender": (4, 5, 0),
    "location": "Preferences > Add-ons > CocoPie",
    "description": "Create and manage custom pie menus from addon preferences",
    "category": "Interface",
}

import bpy

from .properties import COCOPIE_PieMenuItem, COCOPIE_PieMenuData
from .preferences import COCOPIE_AddonPreferences
from .defaults import COCOPIE_OT_restore_defaults, ensure_default_pies
from .keymaps import register_pie_menus, unregister_pie_menus
from .utils import get_prefs
from .ui import COCOPIE_UL_pie_menus
from .previews import register_previews, unregister_previews
from .operators import (
    COCOPIE_OT_execute_command,
    COCOPIE_OT_select_pie,
    COCOPIE_OT_add_pie_menu,
    COCOPIE_OT_remove_pie_menu,
    COCOPIE_OT_duplicate_pie_menu,
    COCOPIE_OT_remove_item,
    COCOPIE_OT_move_pie_menu,
    COCOPIE_OT_save_preset,
    COCOPIE_OT_resolve_preset_conflict,
    COCOPIE_OT_load_preset,
    COCOPIE_OT_test_pie_menu,
    COCOPIE_OT_refresh_menus,
    COCOPIE_OT_edit_item_command,
    COCOPIE_OT_pick_script,
    COCOPIE_OT_select_icon,
    COCOPIE_OT_set_icon_choice,
    COCOPIE_OT_add_to_pie_from_context,
    COCOPIE_OT_add_operator_to_pie,
    menu_func_context,
)


# Order matters: the property groups a later class refers to must already be
# registered, and the preferences class refers to both of them.
classes = (
    COCOPIE_PieMenuItem,
    COCOPIE_PieMenuData,
    COCOPIE_UL_pie_menus,
    COCOPIE_OT_restore_defaults,
    COCOPIE_OT_select_pie,
    COCOPIE_OT_execute_command,
    COCOPIE_OT_add_pie_menu,
    COCOPIE_OT_remove_pie_menu,
    COCOPIE_OT_duplicate_pie_menu,
    COCOPIE_OT_remove_item,
    COCOPIE_OT_move_pie_menu,
    COCOPIE_OT_save_preset,
    COCOPIE_OT_resolve_preset_conflict,
    COCOPIE_OT_load_preset,
    COCOPIE_OT_test_pie_menu,
    COCOPIE_OT_refresh_menus,
    COCOPIE_OT_edit_item_command,
    COCOPIE_OT_pick_script,
    COCOPIE_OT_select_icon,
    COCOPIE_OT_set_icon_choice,
    COCOPIE_OT_add_to_pie_from_context,
    COCOPIE_OT_add_operator_to_pie,
    COCOPIE_AddonPreferences,
)

# Blender 5.0 renamed the button context menu; 4.x still uses the old name
CONTEXT_MENU_CLASSES = (
    'UI_MT_button_context_menu',
    'WM_MT_button_context',
)


def register():
    # Before the classes, so anything drawing a slot arrow already has it
    register_previews()

    for cls in classes:
        bpy.utils.register_class(cls)

    registered = False
    for menu_class in CONTEXT_MENU_CLASSES:
        try:
            if hasattr(bpy.types, menu_class):
                getattr(bpy.types, menu_class).append(menu_func_context)
                registered = True
                break
        except Exception as e:
            print(f"CocoPie: Could not register to {menu_class}: {e}")

    if not registered:
        print("CocoPie: Context menu not available - use manual Add Item button")

    # Fresh install: no saved configuration at all, so lay down the starter
    # pies. Deliberately only when there is nothing, so a user who deletes or
    # renames one never finds it back on the next startup.
    prefs = get_prefs()
    if prefs is not None and len(prefs.pie_menus) == 0:
        try:
            added = ensure_default_pies(prefs)
            if added:
                print(f"CocoPie: added {added} starter pie menu(s) on first run")
        except Exception as e:
            print(f"CocoPie: could not create the starter pie menus: {e}")

    register_pie_menus()


def unregister():
    for menu_class in CONTEXT_MENU_CLASSES:
        try:
            if hasattr(bpy.types, menu_class):
                getattr(bpy.types, menu_class).remove(menu_func_context)
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
            print(f"CocoPie: could not unregister {getattr(cls, '__name__', cls)}: {e}")

    unregister_previews()


if __name__ == "__main__":
    register()
