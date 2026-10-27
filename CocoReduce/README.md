# CocoReduce

Blender add-on that reduces meshes into LODs and keeps the things a game
mesh cannot lose: UV seams stay seams, sharp edges stay sharp, and normals,
vertex colors, vertex groups and materials carry over. The original is never
changed.

Requires Blender **5.2 LTS** or newer.

## Install

CocoReduce is a Blender **Extension**, published from the
[CocoTools](https://github.com/MoonCoconutz/CocoTools) repository.

`Edit > Preferences > Get Extensions > repositories ▾ > + > Add Remote
Repository`, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

Then find **CocoReduce** in Get Extensions and install it.

## Use

3D Viewport sidebar (`N`), **CocoReduce** tab, in Object Mode (a reduced
copy of whole meshes) or Edit Mode (only the faces you select).

1. Select the meshes to reduce.
2. Pick **Hard Surface** or **Organic**, the **Size** (the share of
   triangles to keep), **Small Parts** and **Min Sides** (below). The line under the
   button shows the active mesh's triangles and the count the Size aims for.
3. **Make LOD**. Each selected mesh gets a reduced copy next to it, named
   `<name>_LOD1`; reducing `<name>_LOD1` makes `<name>_LOD2`, and so on. The
   originals are hidden and the LODs selected. Ctrl+Z undoes it. The report
   gives the real count and how many small parts were removed.

In **Edit Mode** the button is **Reduce Selection**: only the selected faces
are reduced, in place, to the Size of their triangles (the line under the
button counts the selected ones). Only selected vertices merge, and only
into one another: the faces right beside the selection follow its corners
(the caps of a selected tube lose the corners its sides lose), and every
face further away stays exactly as it was. The rest of the mesh still
counts for shading and the surface behind, and Small Parts only removes
parts wholly selected. What is left of the selection stays selected, so you can reduce
it again or go on with another area. It works on the mesh itself, without
its modifiers, on every mesh in Edit Mode at once. Ctrl+Z undoes it.

The LOD is made from the mesh as you see it, modifiers included, and has no
modifiers of its own. It keeps the original's parent, place and collections.
A large mesh takes a while (in Hard Surface about 20 s for 63,000
triangles, 65 s for 250,000; Organic about half that); the progress shows
in the status bar.

Every vertex of the LOD is a vertex of the original: points are only ever
merged into a neighbour, never moved. Points go where they change the shape
least first, and a change that would break something is never made:

- **Round things** (tubes, wheels, arcs, rounded edges) keep at least half
  their sides down to a Size of 50%, and never fewer than 8 around. Where
  faces are quads, a whole edge loop goes at once, so a tube loses whole
  sides and stays straight.
- **Min Sides** (8) is the fewest sides a round part keeps. Lower it to go
  further: at 6 a 12-sided tube loses every other side, at 4 an 8-sided
  one does. The shape may then stray from the original by as much as that
  many sides needs (at 6, 7% of the part's size).
- **Every other side** (Hard Surface): a round part made of quads is
  recognised, capped or open, and loses every other side at once, as you
  would by hand: a 32-sided wheel becomes 16 evenly spaced sides, never two
  neighbours gone. Round parts are halved before small parts are removed:
  a pipe is halved and keeps its bolts.
  Seams and hard edges along it stay. A part with fewer than twice Min
  Sides keeps its sides (at 8, fewer than 16), since halved it would drop
  under Min Sides.
- **Corners stay corners**: a box never becomes a wedge, a plate never folds
  shut, a part never moves by more than 5% of its own size.
- **Shading stays**: every change is checked against the original's
  shading, which may differ by 10° at most, so rounded edges do not smear
  over flat panels.
- **No see-through**: a surface never moves more than half the way to its
  own surface behind it (the underside of a thin plate), and two parts
  meeting edge to edge keep meeting, so no cracks open between them.
  Another part close behind (a support a pipe rests on) does not hold it.

### Small Parts

A small loose part (a bolt, a handle, a bracket) often cannot lose a single
triangle without breaking. Rather than break it, CocoReduce removes it whole
when the Size needs the triangles: the smallest first, and every copy of a
part at once (same triangles, same area and size, however each is turned),
so all the bolts of a flange go or none. A kind of part whose removal
would leave the LOD farther below the Size than it is above stays.
**Small Parts** (2%) is the largest part that may go, as a share of the
whole mesh's size; 0 keeps every part. A part that fills an opening, like a
window or a door, is never removed.

### When the Size is not reached

If nothing more can go without breaking a shape or removing a part larger
than Small Parts, the LOD stops there and the report says so: lower Min
Sides or raise Small Parts to go further. A game asset
full of seams, hard edges and round parts can stop well above the Size: a
33,000-triangle locomotive asked for 50% gives 81% with Small Parts at 0
and 64% at 2% (at 2% its bogies lose their dampers); a pipe rack whose
boxes (ladder, trusses) have hard edges and seams on every edge stops at
79% with Small Parts at 0. What is left there is box corners, junctions
of seams and hard edges, and curves already at half their sides.

### What is kept

| | |
| --- | --- |
| **UV seams** | Every UV island stays the same island, with its border where it was (unless its whole part was removed). A long border can lose points where it runs straight, in 3D and in UV, so low LODs can still go low |
| **Sharp edges** | Edges marked sharp, and in Hard Surface mode every edge bent past the Sharp Angle, are kept as lines the same way |
| **Borders** | Open borders, and borders between materials |
| **Normals** | Each corner keeps the original's custom normal, and the shading stays within 10° of the original's, so the support loop beside a rounded edge stays |
| **Data** | Vertex colors, vertex group weights, materials and every UV map |

### Modes

| Mode | For | What it does |
| --- | --- | --- |
| **Hard Surface** | Panels, bevels, sharp edges | Edges bent past the **Sharp Angle** (30°) are kept as lines. In fairly flat areas, faces within the **Flat Angle** (5°) of each other, the triangles and n-gons left join into one n-gon; quads stay quads, so edge loops are kept |
| **Organic** | Sculpts, scans, curved surfaces | Only seams, edges marked sharp and borders are kept as lines. No n-gons |

The faces follow the original: a triangulated mesh stays triangles,
otherwise nearly flat triangle pairs are joined back into quads. Edge loops
stay: a halved flange keeps a quad for every side left.

## Preferences

**Sidebar Tab** (Preferences ▸ Add-ons ▸ CocoReduce) sets the name of the
sidebar tab the panels are in. Clear it to remove the panels from the
sidebar. The button beside it puts the default name back.
