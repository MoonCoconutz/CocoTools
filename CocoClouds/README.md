# CocoClouds

Procedural volume clouds for Blender 5.2+: pick a real cloud
genus, get a cloud. Its rough shape is an ordinary mesh you can edit, or a mesh
of your own; a Cirrus is strokes you can draw. A Geometry Nodes modifier fills
the shape with soft balls of cloud and a volume material shades it.

Clouds made before 0.20.0 keep working as they were, and show **Update
Cloud**, which moves them to the new way and changes their look.

## Install

CocoClouds is in the CocoTools feed. For development, in Blender
`Edit > Preferences > Get Extensions > repositories ▾ > + > Add Local
Repository`, point it at the CocoTools clone, then enable **CocoClouds**.

## Use

3D Viewport sidebar (`N`), **CocoClouds** tab, in Object Mode. At the top is a
small picture of a cloud genus under a line that says what it is for. Click
the picture and the eight genera open as pictures, three to a row, with a
search field under them; click one. What that does follows the selection:

- **Nothing selected**, it reads **Add Cloud**: a new cloud of that genus
  appears at the 3D cursor, another one every time. `Add > Volume > Cloud`
  lists the genera too.
- **Meshes or curves selected** that are not clouds, it reads **Cloud from
  Selection**: each becomes a cloud of that genus, its shape untouched. A mesh
  should be closed; it may be several overlapping pieces. A curve's strokes
  are made tubes.
- **A cloud selected**, it reads **Genus: ...**: another genus gives the cloud
  that genus's settings, and a cloud from the generator is drawn again as one
  (to or from Cirrus it becomes a new object in its place, the same in
  everything else).
- **Back to Mesh** removes the cloud and leaves the mesh.

| Genus | What it is |
| --- | --- |
| Cumulus | A heaped fair-weather cloud with a flat base |
| Stratocumulus | A low layer of large rounded masses in loose rolls |
| Altocumulus | A mid-level layer of small rounded cloudlets |
| Cirrocumulus | A thin high sheet of tiny grains in ripples |
| Stratus | A low, flat, featureless grey sheet |
| Altostratus | A thin, even mid-level sheet |
| Nimbostratus | A thick dark rain layer, ragged underneath |
| Cirrus | Thin high strokes and hooks of ice, drawn as curves |

A cloud's settings are in four panels, in the order a cloud is made.

### Geometry

The cloud's rough outline. A cloud added from nothing is drawn by the
generator: primary spheres over its footprint, then rounds of smaller ones
grown on them, always in one piece. Every setting draws it again; it replaces
the mesh, so what you edited on it is gone (Ctrl+Z brings it back). Greyed out
in Edit Mode.

| Setting | What it does |
| --- | --- |
| **Show Geometry** | The rough shape in place of the cloud in the viewport, as if the cloud were off: the mesh, or a Cirrus's strokes as tubes. A render still shows the cloud |
| **Length**, **Width**, **Height** | The size of the cloud in metres |
| **Height ±** | How far the tops rise above Height or sink below it, from place to place, at most half of Height; the base stays flat |
| **Shape Seed** | Another heap of the same genus |
| **Lumps** | Rounds of smaller spheres grown on the larger ones |
| **Spread** | Which way they grow: upwards at 0, every way at 1 |
| **Random Size** | How unequal the spheres are |
| **Distortion**, **Distortion Scale** | A noise on the ground plane that breaks up the footprint, and how many bends it has |

A mesh of your own made into a cloud has no generator: edit it in Edit Mode.

**Cirrus** is a curve object: each stroke becomes a streak of cloud, thickest
near its start and thinning to its end.

| Setting | What it does |
| --- | --- |
| **Stroke Thickness** | How thick a stroke is at its thickest, in metres; a stroke's own radius (the Draw tool's pressure) scales it |
| **Draw Strokes** | Edit Mode with the Draw tool: draw more strokes. The strokes become yours, no longer redrawn by the settings above |
| **Draw New** | The same, the cloud's strokes removed first |
| **Length**, **Width**, **Height**, **Height ±**, **Shape Seed** | As above, for the generator's strokes |

### Deform

The modifier fills the mesh with points and makes each a ball of cloud. One
noise moves the balls and sets their size, more towards the top of the cloud,
so the base stays where it is.

| Setting | What it does |
| --- | --- |
| **Puff Size** | Size of the largest balls, as a part of the cloud's longest side, 0.005 to 0.1. Smaller is finer and slower; a ball is never smaller than a voxel, so the viewport stays quick |
| **Noise Strength** | How far the noise moves the balls |
| **Noise Scale**, **Detail**, **Roughness**, **Distortion** | The noise itself |
| **Seed** | Another variation of the same cloud: the noise, not the shape |
| **Flat Base** | Part of the cloud's height cut flat at the bottom |
| **Growth** | Nothing at 0, the whole cloud at 1: it fills in from the middle of its base outwards, in scattered puffs that swell and join. Keyframe it |

### Material

| Setting | What it does |
| --- | --- |
| **Density** | How opaque the cloud is across its longest side, whatever its size. The thick genera start at 90: lower, a cloud lit from behind looks veiled instead of dark with a bright rim |
| **Color** | The cloud's colour; white is a white cloud |
| **Dark Base** | Darker towards the base |
| **Glow**, **Glow Color** | Light of its own, for night skies and lightning |
| **Anisotropy** | Cycles only: how much light a first bounce throws forwards. At 1 the edges glow against the sun |

The material is the object's first material slot, shared by every cloud;
the number beside its name makes a copy for one cloud. In Cycles it is two
Principled Volumes: one throwing light forwards, one whose anisotropy halves
at every bounce, standing in for light bounced many times. In EEVEE the
material lights the cloud by itself from the scene's strongest Sun light and
its world, close to the Cycles look and at once; a scene without a Sun gets
one from the upper left.

- Dark Base and Glow above 0 make Cycles take a few seconds longer to prepare
  a render; at 0 they cost nothing.
- EEVEE leaves out lights other than one sun, a cloud's shadow on itself and on
  other clouds, and a world with a texture (taken as a plain blue). Lit from
  the side it is softer than Cycles; lit from behind it shows the dark body
  and the bright rim as Cycles does.
- Cycles needs many volume bounces for a cloud to be as bright as it should.
  Set Up Render's 32 are as good as 128 under an HDRI sky; under a single sun
  and a plain sky a cloud lit from the side is darker at 32.

### Render

| Setting | What it does |
| --- | --- |
| **Viewport**, **Render** | Voxels along the cloud's longest side in the viewport and in a render |
| **Set Up Render** | Cycles: at least 32 bounces, volume and total; Fast GI on from bounce 32; OpenImageDenoise on the GPU. Samples and the noise threshold are left alone. EEVEE: finer volumes with shadows and no Custom Range. Higher bounces and EEVEE settings are left alone |

The panel warns while the scene would render clouds dark or grey (Cycles: too
few bounces, or Fast GI from fewer than 32 bounces, which turns a cloud into
grey smoke), flat or cut off far from the camera (EEVEE).

Every setting is held between the values where it still makes a cloud: past
them a cloud turned to a few bubbles, a sliver, a dark lump, or only took
longer.

## Known limits

- Each change to a setting works the cloud out again: a tenth to a quarter of a
  second for one cloud at the viewport's voxels.
- A Cirrus streak is a tube of balls, not true filaments.
- The pictures to click are images the add-on loads into the file while it is
  on. They are never saved with it, and are removed with the add-on, but the
  Image Editor lists them meanwhile.
