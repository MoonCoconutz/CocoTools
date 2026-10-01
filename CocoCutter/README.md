# CocoCutter

Blender add-on that cuts meshes in two along a line you draw in the
viewport, with a noisy, broken-looking cut surface. You see the cut live
while you tweak it, and apply it when it looks right.

Requires Blender **5.2 LTS** or newer.

## Install

CocoCutter is a Blender **Extension**, published from the
[CocoTools](https://github.com/MoonCoconutz/CocoTools) repository.

`Edit > Preferences > Get Extensions > repositories ▾ > + > Add Remote
Repository`, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

Then find **CocoCutter** in Get Extensions and install it.

## Use

3D Viewport sidebar (`N`), **CocoCutter** tab, in Object Mode.

1. Select the meshes to cut. Switch to an **orthographic** view looking
   straight at the cut (Numpad 1, 3 or 7): the cut goes straight through the
   objects along the view direction.
2. **Draw Cutter**, then drag across the objects.

   | While drawing | Action |
   | --- | --- |
   | **Drag** | Draw the line. A new drag replaces the last one |
   | **Ctrl** while dragging | Straight line from where the drag started |
   | **Enter** / **Space** / **Q** | Confirm the line |
   | **Esc** / **Right Mouse** | Cancel |
   | Middle mouse, wheel, numpad | Move the view between strokes |

   An end that stops inside the objects is carried straight on until it is
   out, so a line drawn a little short of an edge still cuts right across.
   A line whose ends meet becomes a closed loop (**Cyclic**), which cuts a
   core out.
3. The objects now show the cut live, and the cutter is the active object.
   Every setting below changes the result as you drag it.
4. **Cut** applies it; **Cancel** deletes the cutter and leaves the objects
   as they were. Ctrl+Z undoes a Cut.

The cutter is an ordinary curve object: Tab into Edit Mode to move its
points, and the cut follows. Several cutters can live in a scene; the panel
shows the one belonging to the active object, so selecting a cut object
brings its cutter's settings back.

### Settings

| Panel | Setting | What it does |
| --- | --- | --- |
| Cutter | **Resolution** | Grid cells along the longer side of the cut surface. More is finer noise and a slower cut |
| | **Length** / **Offset** | How far the cut reaches along the view direction, and where it is centred. Set on drawing to pass through every selected object |
| | **Cyclic** | Close the line into a loop |
| Noise | **Strength** | How far the surface is pushed in and out |
| | **Scale** | Size of the bumps: higher is smaller |
| | **Detail** / **Roughness** / **Distortion** | Layers of finer noise, how strong they are, and warping |
| | **Seed** | Another variation of the same noise |
| Image | **Image** (folder icon to load one) | A height map: bright pushes out, dark pushes in |
| | **Image Strength** / **Size** / **Rotation** | How far, the size of one image tile on the surface, and its turn |
| Result | **Keep** | **Both** sides as two separate objects, or only side **A** or **B** |
| | **Preview Gap** | Pulls side B away while you work, to see the cut. Cut puts it back |
| | **Cut Material** | Material of the new faces. The next cutter starts with the last one used |
| | **Solver** | **Exact** works on any mesh. **Manifold** is much faster, for closed meshes without holes. **Float** is the fastest and least accurate |
| | **Delete Cutter after Cut** | Off keeps the cutter for another cut |
| Utilities | **Split Loose** | Separate every disconnected piece of the selected meshes |

A new cutter starts with the last cutter's Resolution, Detail, Roughness,
Distortion, Seed, Keep, Solver, Image and Image Rotation, and its Cut
Material. The settings measured in metres (Strength, Scale, Length, Preview
Gap, Image Strength and Size) are worked out again from the size of the new
objects, so the noise looks the same on a pebble and on a column; Cyclic
follows the line you draw.

The new faces get UVs in metres, laid out along the line and across it, on
the object's active UV map.

Cut applies every modifier above the cut too, so the result matches what
you saw; modifiers below it stay. An object with shape keys cannot have
modifiers applied: Cut skips it with a warning and keeps the cutter.
