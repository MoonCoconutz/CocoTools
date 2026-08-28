# CLAUDE.md — CocoDelete

Extension-specific notes. Shared conventions (target versions, headless
verification, the Local Repository dev install, releases) live in the repo
root `CLAUDE.md`.

## What it is

`X` / `Delete` in mesh and curve edit mode skip Blender's confirmation menu and
act immediately: dissolve for mesh vertices/edges (no hole), delete for faces,
delete-segment for curves. See the README for the full behaviour table.

## Deliberately keeps `bl_info` alongside the manifest

Unlike this repo's other extensions, **`bl_info` is not dead weight here** —
`ADDON_ID = __package__ or __name__` at the top of `__init__.py` makes the same
module work as a legacy add-on (module name `CocoDelete`) and as an extension
(module name `bl_ext.<repo>.CocoDelete`), and the manifest's
`blender_version_min = "4.2.0"` is honest: the code itself supports back to
2.80 per `bl_info["blender"]`, for the versions that predate the extension
system entirely. Don't strip `bl_info` the way it was stripped from
CocoSelections — that was a different project's deliberate choice to drop
legacy support, not a repo-wide rule.

## Keymap registration, not an operator shortcut

The core mechanism is `register_keymaps()` / `unregister_keymaps()`, not just
two operators. It inserts entries into the **addon** keyconfig (not the user's
keymap or any preset), which is what makes disabling the add-on restore stock
`X` exactly — nothing in the user's own keymap is ever touched. The
preferences panel introspects the **merged** keyconfig (`get_prefs` /
`bound_keys` and the drawing code around `KEY_LABELS`) to show every binding
that would fire for `X`/`Delete` in a given edit mode, in the order Blender
actually resolves them, so a user can see what is shadowing what.

## Verification gotcha: this extension is already really installed

**`--factory-startup` does not fully disable an already-installed Extension**
the way it disables a legacy `scripts/addons` entry. Confirmed directly on this
extension: under `--background --factory-startup`, loading a *second* copy via
`importlib.util.spec_from_file_location` under a unique module name — the
pattern the root `CLAUDE.md` recommends — silently failed to register:
`bpy.utils.register_class()` raised no exception, but the resulting class never
appeared under `bpy.types`, and `bpy.ops.mesh.cocodelete_delete.poll()` raised
`AttributeError: ... could not be found`. The real install had already claimed
that `bl_idname` at Blender's own startup, before the script's `register()` ever
ran, and something about that path leaves the operator ID dangling rather than
cleanly registered or cleanly absent — so a second registration under the same
ID neither raises nor succeeds.

The unique-module-name pattern is still correct for extensions that are *not*
already installed on the test machine. For one that is, verify against the real
install instead - drop `--factory-startup`, and check
`'bl_ext.user_default.CocoDelete' in bpy.context.preferences.addons` /
`bpy.ops.mesh.cocodelete_delete.poll()` /
`bpy.ops.mesh.cocodelete_delete()` directly. That is how the mesh dissolve
behaviour (8 verts/6 faces → 7 verts/4 faces on a cube, one vertex deleted, no
hole) was actually confirmed on both 4.5 and 5.2.

## No automated test suite

Same as the rest of this repo. Verify a change with a real cube: create it,
enter edit mode, select a vertex/edge/face, call the operator, check the
resulting vert/edge/face counts against the table in the README.
