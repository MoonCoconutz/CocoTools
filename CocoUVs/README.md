# CocoUVs

Blender add-on for managing UV maps and texel density from the UV Editor.

Requires Blender **5.2 LTS** or newer.

## Install

CocoUVs is a Blender **Extension**, published from the
[CocoTools](https://github.com/MoonCoconutz/CocoTools) repository.

`Edit > Preferences > Get Extensions > repositories ▾ > + > Add Remote
Repository`, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

Then find **CocoUVs** in Get Extensions and install it.

## Use

UV Editor sidebar (`N`), **CocoUVs** tab.

### UV Maps

The list shows every UV map found on **any** selected object, each name once,
whichever object is active. Every command applies to every selected object
that has that UV map:

| Control | Action |
| --- | --- |
| **Pen icon** (under the arrows) | Opens a small panel under the button to rename UV maps on every selected object, either by position (the name you type plus 1, 2, 3 ...; empty gives map1, map2, ...) or with Find/Replace (optionally case sensitive, like Blender's batch rename). **Selected** renames only the highlighted map, **All** every map |
| **Seams Update** (panel header) | The seams follow the active UV map's island borders: when you pick a map or remove one, and in Edit Mode after anything that changes the islands (Rip, Unwrap, Stitch, another add-on's tools). A seam you mark by hand stays until the islands change, so you can still mark seams and unwrap |
| **Click a row** | Make that UV map active on every selected object that has it |
| **N/total** next to a name | With several objects selected: how many of them have that UV map active |
| **Red N/total box** | That many objects are still on this UV map because they do not have the one you clicked. Hover it for details |
| **Double-click a name** | Rename it on every selected object that has it |
| **Camera icon** | Use that UV map for rendering and for the textured model in Material Preview and Rendered view. It does not change the UV map you are editing. Solid mode always shows the active (highlighted) UV map; that is Blender's behaviour |
| `+` | Add a UV map (copied from the active one) to every selected object |
| `-` | Remove the highlighted UV map from every selected object that has it |
| `▲` / `▼` | Move the highlighted UV map up or down |

Moving a UV map only changes its position in the list. Its name and its UVs
travel together, so modifiers and material nodes that refer to it by name
keep working.

### Texel Density

Texel density is measured in real-world size, so object scale counts.

| Control | Action |
| --- | --- |
| **Texture** | Resolution of the (square) texture the density is measured against |
| **Density** + unit | The density to assign, in px/m, px/cm or px/mm |
| **Arrow icon** (next to the unit) | Select every island whose density matches the field, within 1% (changeable in the redo panel). Shift-click adds to the current selection |
| **Pick Texel Density** | Measure the average density of the selected islands and put it in the field |
| **Apply: Islands** | Scale each selected island on its own, about its own centre, so each one gets the density |
| **Apply: Average** | Scale the selected islands together as one block, so their average gets the density. Their sizes relative to each other and their layout are kept, the same as pressing S on the selection |
| **Show Heatmap** | Colour every island by its density, from red (lowest) to green (highest) |

A partly selected island is treated as the whole island.

The heatmap is drawn over the UVs in the UV Editor and over the model in the
3D Viewport. It does not change the mesh. It shows the objects in Edit Mode,
or the selected meshes in Object Mode, and the panel lists the lowest and
highest density being shown. When every island is within 1% of the same
density, they are all shown green and the panel says **Uniform**.

While you move, scale or otherwise edit, the heatmap hides. It comes back,
updated, a quarter of a second after you stop.

### Checker Map

**Alt+T** (in the 3D Viewport and the UV Editor), or the checker button,
shows a checker map on the selected objects; press again to put their
materials back. It works in Object and Edit Mode: the objects' materials are
swapped for a checker material while it is on (the originals are stored on
the objects, so they come back even after saving and reopening the file),
Solid viewports switch to Texture colour, and the UV Editor shows the checker
behind the UVs.

Next to the button: the size, 256 to 8192 px, and the folder button to import
an image. Below them: the map (Blender's UV Grid or Color Grid, or any image
you imported). Size and map can be changed while the checker is on.
Objects sharing a mesh get their materials back too.

### Trims

Areas of the UV space where the strips of a trim sheet are. Every **material**
has its own list: the list shows the active material (the one highlighted in
the Material tab; in Edit Mode clicking a face makes its material active).
Areas are saved in the .blend.

| Control | Action |
| --- | --- |
| **Eye icon** (panel header) | Show or hide the areas in the UV Editor, each in its own colour with its name |
| **Click a row** | Pick the area the buttons below send UVs to |
| **Double-click a name** | Rename the area. The colour swatch changes its colour |
| `+` | Start drawing: the next drag on the UV Editor makes a new area |
| **Dotted box** | Add one area per selected UV face, around its UVs (a trim sheet modelled as a strip of quads gives one area per quad). Faces giving the same area as another, or as one already in the list, add it once |
| `-` / `▲` `▼` | Remove the picked area, move it up or down the list |
| **Trash bin** | Delete all the material's areas (asks first; Ctrl+Z brings them back) |
| **Export / Import arrows** | Save the material's areas to a file, or load them into the material (in the file browser, **Replace Existing** removes the current ones first; off, they are added) |
| **Draw Areas** | Draw and edit areas (see below). Press again to finish |
| **Tiling** | Which way the picked area repeats: Horizontal, Vertical or None |
| **Fit + Tile** | Scale the islands to the area's height (width for a vertical trim), keeping proportions. They may run past the area's end, where the trim repeats. On an area that does not tile it works as Fit Inside |
| **Fit Inside** | Scale the islands, keeping proportions, until each fits inside the area |
| **Fill** | Stretch the islands to exactly the area's size |
| **Move** | Move the islands into the area without scaling them |
| **Auto-rotate** | Turn islands 90° when needed so their long side runs along the trim |
| **Randomize** | Shift each island a random amount along a repeating trim, so repeated pieces show different parts of it. Change **Seed** in the redo panel for another layout |

Several selected islands are lined up side by side from the start of the area
(left, or bottom for a vertical trim), in the order they already sit, and
keep going past the end if they are longer than the area. Across the area they
are centred.

**Draw mode** (Draw Areas or `+`), in the UV Editor:

- Drag on empty space: a new area. It tiles along its long side.
- Click an area: pick it. Drag its edges or corners: resize it. Drag its
  inside: move it.
- Hold **Ctrl** while dragging to snap to **UV vertices**: hovering a vertex
  snaps whatever you are dragging to it (even a single edge, if the vertex is
  beside the area), and an edge also lines up with a vertex along it. A moved
  area lines its edges up with vertices along them. An orange square marks
  the vertex.
- Hold **Shift** to snap to the **grid**: whole texture pixels (the Texture
  size of the Texel Density section), in steps of 1, 2, 4 ... pixels that
  follow the zoom, so the grid is always big enough to see. It is drawn
  faintly while you snap. Ctrl+Shift: vertices first, the grid otherwise.
- **X** or **Delete** removes the picked area.
- **Esc**, right-click or the Draw Areas button finishes. Esc or right-click
  during a drag cancels just that drag.
- Zooming and panning work as usual; the sidebar and toolbar keep working.
- **Ctrl+Z** undoes area changes too, in Edit Mode as in Object Mode. Each
  change (a rename, a colour, a tiling, picking a row) is its own undo step,
  so undoing something else, or changing a setting in the Adjust Last
  Operation panel, never undoes it.

### Debug

Each row has a toggle that shows the problem in its own colour (the icon on
the toggle is the colour), and an arrow on its left that selects it
(Shift-click adds to the selection). With a toggle on, the number of islands
found (faces, for Self-Intersecting) is shown next to its name.

| Row | Shows |
| --- | --- |
| **Add Done** / **Remove Done** | Mark the selected UV islands as done, or not done. Marks are kept per UV map and saved in the .blend |
| **Done** | Islands marked as done |
| **Flipped** | Islands whose UVs are mirrored compared with the 3D surface |
| **Overlapping** | Islands that overlap a different island (also across objects in Edit Mode) |
| **Self-Intersecting** | Faces that fold over another face of their own island |
| **Seams / Crease / Sharp / Bevel** | Edges with a seam, crease, sharp mark or bevel weight, in the UV Editor, in the colours the 3D Viewport uses for them. Its arrow selects those edges and switches to edge select mode if needed |

The face checks are drawn in the UV Editor and on the model in the 3D
Viewport; the edge marks only in the UV Editor (the 3D Viewport already shows
them in Edit Mode). Islands that only touch along an edge do not count as
overlapping. Like the heatmap, the overlays hide while you edit and come back
updated a moment after you stop.

### In a pie menu

Every CocoUVs button is its own command, so it can go in a
[CocoPies](../CocoPies/README.md) pie (right-click it > **Add to CocoPies**)
and does the same there as in the sidebar: the Flipped row's arrow becomes
`bpy.ops.cocouvs.select_flipped()`, labelled "Select Flipped". The Debug row
toggles themselves are not offered.

## Preferences

**Sidebar Tab** sets the name of the sidebar tab the panels are in. Clear it
to remove the panels from the sidebar (Alt+T keeps working).
