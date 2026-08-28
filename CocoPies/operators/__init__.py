"""Every operator CocoPies registers, grouped by what it acts on."""

from .pies import (
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
)
from .presets import (
    COCOPIE_OT_save_preset,
    COCOPIE_OT_resolve_preset_conflict,
    COCOPIE_OT_load_preset,
)
from .tools import (
    COCOPIE_OT_test_pie_menu,
    COCOPIE_OT_refresh_menus,
    COCOPIE_OT_edit_item_command,
    COCOPIE_OT_pick_script,
    COCOPIE_OT_refresh_icons,
    COCOPIE_OT_select_icon,
    COCOPIE_OT_set_icon_choice,
)
from .context_menu import (
    COCOPIE_MT_add_to_cocopie,
    DIRECTION_MENUS,
    COCOPIE_OT_add_operator_to_pie,
    menu_func_context,
)

__all__ = [
    "COCOPIE_OT_execute_command",
    "COCOPIE_OT_tap_toggle_direction",
    "COCOPIE_OT_hold_or_tap",
    "COCOPIE_OT_select_pie",
    "COCOPIE_OT_add_pie_menu",
    "COCOPIE_OT_remove_pie_menu",
    "COCOPIE_OT_duplicate_pie_menu",
    "COCOPIE_OT_remove_item",
    "COCOPIE_OT_move_pie_menu",
    "COCOPIE_OT_add_keymap_scope",
    "COCOPIE_OT_remove_keymap_scope",
    "COCOPIE_OT_save_preset",
    "COCOPIE_OT_resolve_preset_conflict",
    "COCOPIE_OT_load_preset",
    "COCOPIE_OT_test_pie_menu",
    "COCOPIE_OT_refresh_menus",
    "COCOPIE_OT_edit_item_command",
    "COCOPIE_OT_pick_script",
    "COCOPIE_OT_refresh_icons",
    "COCOPIE_OT_select_icon",
    "COCOPIE_OT_set_icon_choice",
    "COCOPIE_MT_add_to_cocopie",
    "DIRECTION_MENUS",
    "COCOPIE_OT_add_operator_to_pie",
    "menu_func_context",
]
