# CLAUDE.md — CocoUVs

Extension-specific notes. Shared conventions (headless verification, the
Local Repository dev install, releases) live in the repo root `CLAUDE.md`.

**Target: Blender 5.2 and later only** (`blender_version_min = "5.2.0"`), at
the user's request. The 4.5 run from the root `CLAUDE.md` does not apply.

## What it is

A **CocoUVs** tab in the UV Editor sidebar (`IMAGE_EDITOR` / `UI`, panels poll
`space.mode == 'UV'`): a UV map list, and texel density tools with a heatmap.

## Layout

- `common.py`: no classes. Which objects and meshes a command acts on
  (`target_objects`, `target_meshes`, `edit_objects`, `has_targets`), what the
  overlays show (`source_objects`), the overlays' shared mesh read
  (`read_mesh`, cached), their 3D drawing (`draw_on_surface`), UV visibility
  and selection rules, the island finders, the area and density maths,
  `scale_island`, `scale_islands_together`.
- `properties.py`: `Scene.cocouvs` settings, and `WindowManager.cocouvs_heatmap`
  (on the WM so it is never saved into a .blend).
- `uv_sets.py`: the name list (`WindowManager.cocouvs_uv_list`), highlighted
  row, counts, add/remove/move operators and the `UIList`.
- `texel.py`: `selected_islands()`, Calculate and Assign.
- `heatmap.py`: cache, GPU batches and the two draw handlers.
- `debug.py`: the Debug overlays (analysis, draw handlers), the select
  operators (one per kind, `SELECT_OPERATORS`) and Add/Remove Done.
- `checker.py`: the Checker Map toggle, material swap, image and Alt+T keymap.
- `trims.py`: trim areas per material, the fit operator, draw mode (modal)
  and the area overlay.
- `prefs.py`: add-on preferences (sidebar tab name).
- `ui.py`: the five panels, in the user's order (UV Maps, Texel Density,
  Checker Map, Trims, Debug: registration order is sidebar order) and
  their registration under the tab name.

## One operator per button

A panel button never passes a setting (`.kind = ...`, `.method = ...`):
each button is its own operator, and what it does is in the name. CocoPies'
right-click "Add to CocoPies" keeps only the operator's name
(`context.button_operator.bl_rna.identifier`), so before 1.2.0 every Debug
arrow became `bpy.ops.cocouvs.debug_select()` labelled "Debug Select", and
it selected Done (user report, 2026-09-28). The same held for Add/Remove Done,
Islands/Average, the four trim fits and both lists' up/down arrows.

- The shared code is a **mixin** (a plain class: `_DebugSelect`, `_DoneMark`,
  `_Assign`, `_TrimFit`, `_TrimMove`, `_UVMove`) with the variant as a class
  attribute (`kind`, `add`, `method`, `step`). Each button is a small subclass
  `(Mixin, Operator)`. Settings in the mixin's annotations are registered on
  every subclass (checked: Extend on the selects, Auto-rotate/Randomize/Seed
  on the fits).
- **Name the idname for its CocoPies label.** CocoPies title-cases the part
  after the dot: `cocouvs.select_flipped` -> "Select Flipped". The `cocouvs.`
  prefix is this add-on's namespace and never shows in a pie.
- What is a real setting stays a property and shows in the redo panel
  (Extend, Auto-rotate, Randomize, Seed). The method of a fit or of Assign is
  the button, so the redo panel no longer switches it.
- One exception: Trims' `+` passes `toggle=False` to `trim_draw`. In a pie it
  becomes the Draw Areas toggle, which is harmless.
- WindowManager toggles (the Debug rows, Show Heatmap) get no "Add to
  CocoPies" entry at all. Seen in a real window: the Flipped toggle's menu
  has no entry. CocoPies skips a property whose owner gives no data path.
- Verified on 5.2 (2026-09-28): `split_checks` draws every panel into a
  recording layout and fails on any button that sets a property, runs each
  operator through CocoPies' own `_write_capture` (command and label), and
  checks each variant reaches the right code path. In a real window,
  right-clicking the Flipped arrow captured `COCOUVS_OT_select_flipped`,
  added it to a new pie, and picking that slot ran it.

## UV maps act on every selected mesh, by name

`target_objects()` = active + selected + anything in Edit Mode, each once,
active first; `target_meshes()` = their meshes, one per data block. Every
command works on a UV map **name**, on every target that has it.

**Only scan the view layer while editing.** Finding the objects in Edit Mode
means looking at every object, and the sidebar did that about ten times per
redraw (five panel polls, the list, each row's camera): 6.5 ms per redraw in
a 5000-object scene. Blender keeps objects in Edit Mode only alongside an
active one that is, so `common._editing()` returns at once unless the active
object is in Edit Mode, and the panels poll `has_targets()` (active or a
selected mesh). Now 0.6 ms (2026-09-28).

- **The list is the union of names, not the active mesh's `uv_layers`.** The
  user wants every UV map on any selected object listed, whichever object is
  active. A `UIList` can only draw a real collection, so the names live in
  `WindowManager.cocouvs_uv_list` (`COCOUVS_UVMapItem`, never saved). A draw
  call may not write ID data, so the panel draw compares the names
  (`union_names`) with the collection and, if they differ, `request_sync`
  schedules a one-shot `bpy.app.timers` timer that rewrites it
  (`sync_list`) and tags a redraw. Operators call `sync_list` directly.
  Headless tests must call `sync_list(context)` themselves: in background
  there is no window for the timer path.
- **Which row is highlighted** (`chosen_name`): the last clicked or added name
  (`_chosen`, Python-only) while any target still has it active, otherwise
  the name active on the most targets (the active object's map wins a tie).
  `Scene.cocouvs.uv_index` is a get/set with no storage: the getter returns
  that row, and the setter (a row click) makes the name active on every mesh
  that has it (`make_active`). Remove and Move act on this name.
- **Red rows:** a row whose map is still active on some target but is not the
  highlighted one marks objects that lack the clicked map and stayed where
  they were. Its N/total is drawn as a **solid red box**: an embossed button
  (`cocouvs.uv_map_mismatch`, a no-op whose tooltip explains the mismatch)
  inside an `alert` row. Do not rely on `alert` alone on emboss-less text: in
  the user's theme that is only a faint tint (measured RGB (0.89, 0.80, 0.84)
  against (0.91, 0.93, 0.95)), and the user reported "no red". The factory
  theme shows it clearly red, which is why a `--factory-startup` probe missed
  it. The camera is never red.
- **Row counts (N/total)** are per *object*, not per mesh, so instances each
  count, as the user counts. The panel computes counts and the highlighted
  name once and hands them over through `set_row_state` right before
  `template_list()`, which draws every row during that call. Counts show
  only with more than one object, and only for maps active somewhere.
- **Rename** is the item's `name` update callback: `stored_name` holds the
  old name and every mesh's layer with it is renamed (unless that mesh
  already has the new name). `_syncing` stops `sync_list`'s own writes from
  firing it. No msgbus: renames made in Blender's own UV Maps panel are no
  longer copied to other objects; the list simply resyncs.
- **Camera** is the item's `render` get/set: on when every target that has
  the name renders with it; setting it sets `active_render` on each of them.
- **Reordering has no API.** `_swap_uv_maps` swaps two layers' UV and pin data
  through BMesh, then swaps their names. Nothing is deleted, and anything that
  refers to a UV map by name (modifiers, UV Map nodes) still points at the
  same UVs.
- **`uv_layers.new()` returns `None` in Edit Mode** on 5.2, even though it
  adds the layer (verified headless). Look the new layer up by name afterwards.
- **The camera icon sets the render map only, never the active map.** The
  user wants it to swap what the 3D Viewport shows without changing the map
  being edited. One version also made it the active map, and the user
  rejected that. Which map the viewport shows (screenshot-verified on 5.2):
  - **Material Preview / Rendered** show the **render** map (Image Texture
    nodes with no UV Map node use it). The camera alone swaps the tiling,
    and the active map is untouched.
  - **Solid mode, Texture colour** always shows the **active** map and
    ignores the render one, in Object and Edit Mode. There is no setting for
    this. Supporting it in Solid mode would take an overlay of our own.

## Texel density

- `density_ppm = texture_size * sqrt(uv_area / world_area_m2)`. World area
  uses `matrix_world` (real-world size, object scale included) and
  `scene.unit_settings.scale_length`. The value is always stored in **px/m**
  (`density_ppm`). `density` is a get/set view in the chosen unit, so
  switching units converts the value.
- "Average" everywhere means **area-weighted**: total UV area over total world
  area, not the mean of the per-island values.
- **Assign Average scales the selection as one block** about the centre of
  the combined UV bounding box of every selected island, across all objects
  in Edit Mode (`common.scale_islands_together`), like pressing S. The first
  version scaled each island about its own centre by the shared factor. That
  kept the density ratios, but on islands of near-equal density it looked
  identical to Per Island, and the user rejected it. Per Island still scales
  each island about its own centre.
- Islands are vertex-connected with matching UVs (Blender's own definition,
  `UV_CONNECT_LIMIT` 1e-4), grown only through faces the UV Editor shows.
  `bpy_extras.bmesh_utils.bmesh_linked_uv_islands` was not used because it
  ignores hidden and unselected faces.
- **UV selection since 5.0 is `BMFace.uv_select`.** With sync selection on it
  only counts while `bm.uv_select_sync_valid`; otherwise `face.select` is used.
  See `common.uv_face_selected`.
- **Selecting islands (`select_by_density`) must not flush from vertices.**
  In vertex select mode, `select_flush_mode()` after selecting some faces also
  selects any face whose corners are all selected. Across a seam, that is a
  face of another island. So the operator sets face flags directly:
  `select_set` plus `uv_select_set`, which flushes down to that face's own UV
  corners only (corners are never shared between faces). In sync mode it then
  sets `bm.uv_select_sync_valid = True`, since the UV-level selection now
  matches the mesh one face for face. `bm.uv_select_foreach_set()` raises
  unless `uv_select_sync_valid` is already true, even with sync off, so it is
  not used. Tolerance is relative (default 1%, in the redo panel);
  Shift-click extends the selection.

## Heatmap

- Colour per **island**, not per face (per face is noisy). The hue runs from
  red (0°) to green (120°) instead of blending RGB, so the midpoint is yellow
  and not olive. The range is the min..max of what is shown. When the spread
  is within `UNIFORM_SPREAD` (1%) of the highest value, everything is green
  and the legend says "Uniform". Without that, float noise after Per Island
  stretched near-equal islands across the full red-to-green range.
- Sources: objects in Edit Mode, otherwise the selected meshes (Object Mode).
  It uses the base mesh, not the evaluated one, so with a Subdivision modifier
  the 3D overlay follows the cage.
- **Never recompute from a draw callback, and never per depsgraph update.**
  The first version rebuilt in the draw callback whenever dirty. During a drag
  the depsgraph updates on every mouse move, so it rebuilt every frame
  (0.6 s per frame on a 31k-face mesh), and Blender stopped responding. That
  writes no crash log. Now `depsgraph_update_post` only marks it dirty and
  (re)starts a `bpy.app.timers` timer (`DEBOUNCE`, 0.25 s). While dirty the
  draw callbacks draw nothing, because the data would be in the wrong place.
  The timer recomputes plain numpy arrays, and the next draw turns them into
  GPU batches (that needs a draw callback's GPU context).
- **The recompute only reads the mesh.** It may run while a transform is
  still in progress. Vertices are identified by `hash(BMVert)` (their
  address), never `BMVert.index` or `index_update()`. Faces are fan-split in
  numpy, not with `calc_loop_triangles()`. A headless test checks that
  vert/face/loop indices are untouched.
- **One read for both overlays.** The heatmap and the Debug overlays read
  the mesh through `common.read_mesh()`, which caches each object's arrays
  until the next depsgraph update (both handlers call `forget_reads()`; so do
  switching either on or off). Their timers fire together after an edit, so
  with both on the mesh is read once instead of twice (7.9k faces: 0.164 s ->
  0.125 s for both recomputes). The cached dict is shared: `analyze()` adds
  its masks to it, which the heatmap ignores. The select operator
  (`keep_faces=True`) always reads fresh, since it needs live BMFaces.
- **The switch survives a file opened without its UI.** `cocouvs_heatmap`
  lives on the WindowManager: a normal open or File > New resets it, but with
  Load UI off it keeps this session's value. `_load_post` therefore re-applies
  the switch (`set_enabled(wm.cocouvs_heatmap)`) instead of switching off,
  which left it showing "on" with nothing drawn.
- **Speed:** one Python pass reads each corner's UV and `hash(loop.vert)`.
  Everything else is numpy: vertex lookup by `searchsorted`, the corner key
  packed into one int64, islands by min-label propagation with pointer
  jumping (`_components`), areas via `bincount`. A 31k-face mesh takes about
  0.25 s, down from 0.6 s. Most of what is left is Blender's Python access to
  BMesh UVs (about 70 ms just to read 125k UVs); there is no bulk accessor on
  an edit BMesh. `BMesh.to_mesh()` into a temporary mesh would be C speed, but
  it writes indices on the edit BMesh.
- **Real-input test:** `--enable-event-simulate` plus `Window.event_simulate`
  drives real G/S/R drags, confirm, cancel, Ctrl+Z / Ctrl+Shift+Z and Tab in a
  real window. That is the only way to exercise modal transforms. It passed
  with the heatmap on and recomputing after every action.
- **UV Editor**: `POST_PIXEL`. The batch holds UV coordinates, and one
  translate + scale from `view2d.view_to_region` of (0,0) and (1,1) maps them
  to the region. A screenshot confirms it lines up with the UVs.
- **3D Viewport**: `POST_VIEW` with depth test, and the projection nudged
  towards the camera (`proj[2][3] *= 1 + 1e-4` in perspective) to avoid
  z-fighting. A screenshot shows no z-fighting at normal zoom.

## Debug section (`debug.py`)

- Kinds: Done, Flipped, Overlapping, Self-Intersecting (faces; drawn in the
  UV Editor and the 3D Viewport) and one combined edge-marks row
  (seam/crease/sharp/bevel; UV Editor only, since the 3D Viewport already shows
  them). The user chose each of these, and the arrow sits on the left of each
  row, as on the Density row. Toggles are `WindowManager.cocouvs_debug_*`.
- Same overlay rules as the heatmap: debounced timer recompute, hidden while
  dirty, read-only mesh access in `_read` (vertex and edge identity by
  `hash()`, never `.index`). `_read` + `analyze` are also what the select
  operator runs, so what is drawn and what is selected cannot drift apart.
- **Flipped** = island with negative total signed UV area (mirrored).
  **Overlapping** = island with a triangle overlapping a triangle of *another*
  island, across all objects in Edit Mode (shared UV space); the whole island
  is flagged, as the user asked. **Self-Intersecting** = faces overlapping
  another face of the *same* island.
- **Overlap detection** (`overlapping_pairs`): grid broad phase (cell ~2x the
  median triangle size) + exact separating-axis test in numpy. Overlap must
  exceed `OVERLAP_EPS` (1e-6 UV), so triangles sharing an edge, and islands
  only touching, do not count. A pair spanning several cells is kept only in
  the lowest shared cell. The earlier `np.unique` over all pairs was half the
  run time. **Checked against Blender's own `uv.select_overlap`:** the same
  218 faces on a smart-projected 31k-face mesh; with islands pushed onto
  each other, every face Blender finds is found here too, except 16 that
  overlap by <= 1e-6 UV (touching), which Blender counts and this
  deliberately does not. Timing on 31k faces: read ~0.22 s + analyze ~0.38 s.
- **Done** = hidden bool face attribute `.cocouvs_done.<UV map name>`
  (`common.done_layer_name`), so it is per UV map and saved in the .blend.
  Renames via the list and Rename-by-index carry it (`common.rename_uv_map`),
  Remove deletes it, and Move keeps it (names swap with the data). Renaming a
  map in Blender's own panel orphans it.
- **Adding a BMesh layer invalidates the Python BMFace references you already
  hold** (`ReferenceError: BMesh data of type BMFace has been removed`, seen on
  5.2). Add Done (`_DoneMark`) therefore creates the layer before collecting
  islands.
- Edge selection sets the edge's UV corners directly (`uv_select_edge_set`
  plus both vertices), with no flush. It switches face select mode to edge
  mode, otherwise nothing would show.
- Colours: face kinds use the theme's strip colours
  (`themes[0].strip_color[slot]`), which are the colours of the legend icons
  (`STRIP_COLOR_0x`) on the toggles, so icon and overlay always match. Edges
  use `themes[0].view_3d.seam/sharp/crease/bevel`.

## Rename

`cocouvs.uv_rename`, a pen icon (`GREASEPENCIL`) under the move arrows (the
user swapped it with the Seams Update checkbox), opens `COCOUVS_PT_rename` as a
popover anchored under it, like CocoBackup's menu (fields in
`WindowManager.cocouvs_rename`, a Rename button runs `cocouvs.uv_rename`):
mode **By Index** (the typed name plus 1, 2, 3; empty gives `map1, map2, ...`,
`RENAME_BASE`, the user's choice) or **Find/Replace** (`_find_replace`: Blender batch-rename semantics, with
optional case sensitivity; regex was removed at the user's request), and scope **Selected** (only the
highlighted map) or **All**. Every target mesh goes through temporary names,
so "map2" -> "map1" cannot collide with an existing "map1". A result that
would be empty keeps the old name. The highlighted row follows the rename.

## Update Seams

`Scene.cocouvs.update_seams`, a "Seams Update" checkbox drawn with `draw_header_preset` (the
right-hand end of the UV Maps header, the user's placement). When on, `make_active` (a row click) calls
`common.seams_from_uv_map` on every target mesh that has the map: an edge is
a seam where the faces on either side do not share UVs at both ends, and
mesh boundaries stay unmarked. That gives the default cube's 7 seams.
Existing seams are replaced.

## Checker Map (`checker.py`)

- Alt+T (addon keymaps "3D View" and "Image") or the panel button toggles
  it. It is a **temporary material swap** (the user's choice over an
  overlay): every slot of each target object gets the "CocoUVs Checker"
  material, and objects with no slots get one. The originals are stored as a
  JSON string in the object ID property `cocouvs_checker_orig` (slot link,
  material name, whether a slot was added), so they survive saving the file
  with the checker on. "On" means any object carries that property.
- While on, Solid 3D views in Material colour switch to Texture colour (the
  material's image node is kept active for that), and UV Editors show the
  image. Both are restored when it goes off; the view state is Python-only.
- **Every original is stored before any slot is changed.** Objects sharing
  a mesh share its slots (link DATA): storing and assigning one object at a
  time made the second one record the checker as its own material, and
  depending on the order objects are restored in (alphabetical), turning the
  checker off left it on the mesh. Found and fixed 2026-09-28.
- New materials come with a node tree on 5.x; `Material.use_nodes` is
  deprecated (a DeprecationWarning, removal planned for 6.0), so it is not set.
- **Removing the added slot must use `mesh.materials.clear()`, not
  `pop()`**: on 5.2, `pop()` leaves the object's `material_slots` count
  stale (an empty slot stays in the Material tab), even after
  `view_layer.update()`. Measured in a headless run.
- Maps: Blender's generated UV Grid and Color Grid in the chosen size
  (256-8192), or imported images (tagged `cocouvs_checker_import`, listed by
  the dynamic enum `_map_items`). Changing either while on updates the image
  in place.

## Trims (`trims.py`)

- **Areas live on the material**: `Material.cocouvs_trims` (a collection of
  `COCOUVS_TrimArea`: name, `rect` = (u0, v0, u1, v1), `tiling`, `color`) and
  `Material.cocouvs_trim_index` (the picked one). The list shows
  `material()`: the active object's `active_material` (the user's choice). No
  material: the panel says so and nothing else draws.
- **Fit** (`fit_islands`, pure numpy, tested directly): islands go side by
  side along the area's length from its start (left, or bottom), sorted by
  where they already sit, and keep going past the end (the user's choice:
  the trim repeats there). Across the area they are centred. TILE scales to
  the cross size, FIT to fit inside, FILL stretches per axis, MOVE keeps the
  size. TILE on a non-tiling area falls back to FIT. Auto-rotate turns an
  island 90 degrees when its long side is across the trim. Randomize adds
  `uniform(0, area length)` per island from a seeded `random.Random`; the
  panel checkboxes only seed the operator's own properties in `invoke`, so
  the redo panel can change them.
- **Keep the BMesh wrapper alive while using its loops.** `_selected_island_loops`
  returns the `bm` with the loops: when the Python `BMesh` from
  `bmesh.from_edit_mesh` is freed (the helper returned), every `BMLoop` taken
  from it raises `ReferenceError: BMesh data of type BMLoop has been removed`
  (5.2, found by the headless test).
- **Draw mode** (`COCOUVS_OT_trim_draw`) is a modal operator on the UV
  Editor's WINDOW region, found from `context.area` because the buttons that
  start it live in the UI region. Module state `_state` (running, drag,
  preview) is shared with the overlay and the panel. The Draw Areas button
  toggles (a second invoke sets `stop`); `+` passes `toggle=False` so it only
  starts. Hit test in pixels: the picked area's edges/corners first
  (`HANDLE_PX`), then the smallest area under the mouse, else a new area.
- **Region overlap:** the sidebar, toolbar and tool header lie *on top of*
  the WINDOW region, so "inside WINDOW" is not "on the canvas". `_in_canvas`
  excludes every other visible region of the area (hidden ones report a
  1x1 size); without it the modal ate clicks meant for the Trims panel's own
  buttons (seen in a real-window probe).
- **Snapping (the user's keys): Ctrl = UV vertices, Shift = grid**, both =
  vertices first. Vertex: a vertex within `SNAP_PX` of the mouse sets every
  dragged axis, even for a single-edge drag (the user resizes an area
  vertically by hovering a vertex beside it); otherwise `_align` lines each
  moving edge up with a vertex along it (within its span on the other axis).
  A move aligns either edge per axis. Grid: whole pixels of the Texel Density
  texture size, the step a power of two of pixels at least `GRID_MIN_PX`
  apart on screen (`_grid_step`; single pixels, about 0.2 screen pixels at
  2048, looked like no snapping). `_state["snap"]` makes the overlay draw
  the grid (alpha 0.05: the user found 0.12 too strong), orange squares on
  the vertices used and a cross on a grid point. Vertices are read on each
  press (visible faces, active UV map, Edit Mode only).
- **Overlay:** one `POST_PIXEL` handler on `SpaceImageEditor`, registered for
  the add-on's lifetime; it returns at once unless `cocouvs_trims_show` (the
  header eye, default on) or draw mode is on. Few rectangles, so batches are
  built per draw.
- **Undo in Edit Mode.** Areas are material data and an Edit Mode undo step
  stores only the mesh, so Ctrl+Z did nothing to them (user report). Every
  change calls `record_change()`: it stores `_snapshot()` (all materials'
  areas) under a new number and writes that number to the first vertex of
  the active edit mesh in a hidden int attribute `.cocouvs_trims_undo`,
  which the undo step does store. `_undo_post` (also on redo) reads it back
  and `_restore`s that snapshot. The mesh's first change also stores the
  state before it (`_last_seen`, taken on every UV Editor redraw outside a
  drag) under `_base`, for undoing past the step that added the attribute.
  Property updates record through `_index_changed` (the UI then pushes its
  own step); list operators record at the end of `execute`; draw mode, which
  has no undo flag, calls `commit()` on release and on X (`ed.undo_push`).
  Nothing is recorded mid-drag. `add_area()` sets its fields under `_quiet`
  and its caller records once: each field's update used to record, 26
  snapshots of every material for an import of five areas.
  `_last_seen` (the redraw snapshot) is taken only in Edit Mode, and only
  while the edit mesh has no undo attribute yet; before, every UV Editor
  redraw copied every material's areas, in any mode. Snapshots are Python-only, so after
  reopening a file undo only reaches steps made since. Object Mode needs
  none of it (memfile undo holds materials). The attribute stays on the mesh.
- **Areas from Selection is one area per selected face** (its UV bounding
  box), skipping boxes equal to another new one or an existing area, sorted
  top to bottom, left to right (the user's choice over one area around the
  whole selection).
- Real-window test: `--enable-event-simulate` drags create, Ctrl-snap an edge
  to a vertex (0.625 on the default cube), Shift-snap a move and a new area to
  the grid, Ctrl-snap a top edge to a vertex beside the area, Ctrl-align a
  move, click to pick, X to remove, Ctrl+Z / Ctrl+Shift+Z, a drag over the
  sidebar left alone, Esc to exit.

## Sidebar tab name

`prefs.py` holds `COCOUVS_Preferences.tab_name`. Its update calls
`ui.update_tab()`, which unregisters the panels and registers them again
with `bl_category` set to the new name, or leaves them unregistered when the
name is empty. `ui.tab_name()` falls back to "CocoUVs" when the add-on has no
preferences entry, which is the case for the verification loader.

## Gotchas found on 5.2

- The `SEQUENCE_COLOR_*` icons are now `STRIP_COLOR_*`.
- `Region.active_panel_category` is read-only, so a probe cannot switch the
  sidebar tab. Draw the panel's `draw()` into an `invoke_props_dialog` instead
  (see the root `CLAUDE.md`).

## Verifying

The headless scripts (8 of them, 132 checks, plus 26 for the 2026-09-28
cleanup: shared read, Edit Mode targets, checker on instances, heatmap after
an open without UI, trims recording) cover:

- add, remove and move, in Object and Edit Mode;
- row clicks, renames and the camera through the list's own properties;
- the name list and red rows with five objects where the active one lacks a
  map, including a map on a single non-active object;
- measure and assign values, against planes of known size;
- Average keeping both the density ratios and the layout;
- the heatmap finding the same islands and densities as the operators, not
  touching indices, reporting "uniform" after Per Island, and its speed on a
  31k-face mesh;
- each Debug kind on hand-built meshes with a known answer, including the
  negative cases (islands apart, touching exactly, a clean grid), a
  cross-object overlap, Done marks per UV map through rename, rename-by-index
  and remove, and edge selection.

It cannot reach the timer that fills the list, a real double-click rename, or
the draw handlers. Use a real window for those: screenshots for the drawing
(a probe can register a copy of a panel under the sidebar's default "Image"
tab, since it cannot switch tabs), and `--enable-event-simulate` for modal
tools (see Heatmap above).
