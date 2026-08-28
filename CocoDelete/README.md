# CocoDelete

`X` deletes straight away in mesh and curve edit mode — no delete menu, no
confirmation popup.

## What it does

| Edit mode | Select mode | Default `X` | With CocoDelete |
|---|---|---|---|
| Mesh | Vertex | "Delete" menu | Dissolves the vertices — surrounding faces merge, no hole |
| Mesh | Edge | "Delete" menu | Dissolves the edges — the two faces merge, no hole, no stray vertex |
| Mesh | Face | "Delete" menu | Deletes the faces (a lone face has no dissolve equivalent, so this leaves a hole) |
| Curve | — | "Delete" menu | Deletes the selected segment, splitting the curve |

Mesh behaviour was verified against three reference cubes in a live Blender
session — one edge deleted, one vertex, one face — and matches them exactly.

Curve deletion uses Blender's *Delete Segment*, so it needs **two neighbouring
control points** selected. With a single point selected it does nothing, same as
picking Segment from Blender's own menu.

Object mode is deliberately not covered: Blender already lets you switch that
popup off in `Preferences ▸ Keymap ▸ Object Mode ▸ object.delete (X)` by
unticking *Confirm*, so an add-on adds nothing there.

## Install

Published from the [CocoTools](https://github.com/MoonCoconutz/CocoTools)
extension repository. `Edit ▸ Preferences ▸ Get Extensions ▸` repositories
dropdown ▸ **+** ▸ **Add Remote Repository**, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

Then find **CocoDelete** in Get Extensions and install it.

Blender 2.80–4.1 predates the extensions system and cannot use that
repository, but the add-on itself still runs there since `bl_info` is kept
alongside the manifest for that reason. This repo's own release pipeline only
ships the extension path above; a legacy install for pre-4.2 Blender would need
building and packaging by hand from this folder.

## Settings

`Edit ▸ Preferences ▸ Add-ons ▸ CocoDelete ▸ ⌄` — the whole panel:

```
☑ Mesh Edit Mode    ☑ ✔ Delete  mesh.cocodelete_delete
                    ☑ ✔ X       mesh.cocodelete_delete
                    ☐   X       wm.call_menu_pie_drag_only
                    ☑   X       wm.call_menu
                    ☑   Delete  wm.call_menu

☑ Curve Edit Mode   ☑ ✔ Delete  curve.cocodelete_delete
                    ☑ ✔ X       curve.cocodelete_delete
                    ☑   X       wm.call_menu
                    ☑   Delete  wm.call_menu

☑ Use the Delete key as well as X
```

Each mode has its own checkbox, and **everything using that shortcut is listed
right beside it** — every unmodified `X` / `Delete` binding that applies in that
edit mode, read from the merged user keyconfig (the one Blender actually runs):

- **✔** marks the entry that actually fires; everything below it is shadowed
- the **left checkbox** switches a binding off, the same flag as
  `Preferences ▸ Keymap`. It is greyed out for CocoDelete's own entries, which
  the mode checkbox on the left controls instead
- entries that are switched off stay listed, greyed, so you can turn them back on

The order shown is the order Blender resolves them: the 3D View region keymap is
consulted before the mode keymap, and within a keymap add-on entries sit ahead of
Blender's defaults — which is why `wm.call_menu` (the stock delete menu) is
listed but never wins while CocoDelete is enabled.

There is no uninstall button: Blender's own extension entry already provides one
in the dropdown at the top right of the add-on's row.

## How it works

Keymap entries are registered in the **addon** keyconfig; your user keymap and
your keymap presets are never modified, so disabling the add-on restores stock
behaviour exactly. Deletion is done by Blender's own `mesh.dissolve_verts`,
`mesh.dissolve_edges`, `mesh.delete` and `curve.delete`, so undo and reports
behave normally.

## Not covered

`X` in armature, metaball, lattice and grease pencil edit mode still opens the
normal menu.
