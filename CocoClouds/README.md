# CocoClouds

**Experimental.** Blender add-on that makes clouds as volumes. A rough mesh
gives the shape and the add-on turns it into a billowing, eroded cloud that
you tune live. Add one ready made, another one every time, or make one out
of a mesh of your own, as plain as a box.

Requires Blender **5.2 LTS** or newer.

## Install

CocoClouds is not in the published feed. In Blender, `Edit > Preferences >
Get Extensions > repositories ▾ > + > Add Local Repository`, point it at the
CocoTools clone, then enable **CocoClouds**.

## Use

3D Viewport sidebar (`N`), **CocoClouds** tab, in Object Mode. At the top
is a picture of a cloud type under a line that says what it is for. Click
it and the pictures of the nine types open, as Blender's MatCaps do; click
one of those. What that does follows the selection:

- **Nothing selected**, it reads **Add Cloud**, over the picture of the
  type added last: a new cloud of the type clicked appears at the 3D
  cursor, the same type again as often as you like. `Add > Volume >
  Cloud` lists the types with small pictures. Each one is another cloud,
  in outline and in detail, with nothing to set. Size and Seed are in the
  panel that opens at the bottom left of the viewport; a Seed you type
  there gives that same cloud again.
- **Meshes selected** that are not clouds, it reads **Cloud from
  Selection**: each becomes a cloud of that type, its shape untouched. A
  mesh should be closed; it may be several overlapping pieces, which merge
  into one cloud.
- **A cloud selected**, it reads **Type: ...** with the type the cloud has,
  over that type's picture. Picking another gives the cloud that type's
  settings, and its heap of spheres too if the cloud is still on the heap
  it was added as. A mesh of yours, or a heap you edited by hand, keeps
  its shape. Nothing is added.
- **Back to Mesh** removes the cloud and leaves the mesh.
- `Add > Volume > Cloud` always adds a new one, whatever is selected.

To add a cloud while one is selected, click on empty space first.

A cloud is an ordinary mesh object with a modifier on it, and the mesh is
still there: Tab into Edit Mode and move, scale or add pieces, and the cloud
follows.

A cloud added from nothing is a heap of spheres of very different sizes: a
few large ones for the body, smaller ones grown out of them, and smaller
ones again out of those. That is what gives a cumulus its cauliflower
outline before any noise is added. In Edit Mode, `L` over a sphere selects
that one sphere.

Such a cloud has two seeds in its Shape panel. **Shape Seed** draws the heap
of spheres again: another outline, same settings. **Seed** moves the noise
on the heap it has. Drag Shape Seed to go through outlines without adding
a cloud each time.

### A sky full of clouds

**Add Cloud Field**, under Add Cloud while nothing is selected (also `Add >
Volume > Cloud Field`), fills a sky for the price of a few clouds. A field
holds the five kinds that come many at a time, apart from one another:
Cumulus, Puff, Sheet, Flock and Shreds. Not Tower or Anvil, which stand
alone, nor Lens, nor Layer, which is one unbroken sheet. It makes three
clouds of each kind and a plane, 1000 m above the 3D cursor, that repeats
them all over its surface, each copy turned and scaled. Area, Height, Cloud
Size, Spacing and Clouds of Each Kind are in the panel at the bottom left
of the viewport. Cloud Size is a Cumulus's width; a Puff is made 0.6 of it,
Shreds half, a Sheet and a Flock twice.

- **The plane is the sky.** Scale it, or reshape it in Edit Mode, and the
  clouds follow its faces. It is made of faces about one Spacing wide, so
  that it can be painted on: move some of its vertices with Proportional
  Editing to bend it. For a play area, make it reach as far past the area
  as clouds should be seen.
- **The fifteen clouds are ordinary clouds**, in the collection *Field
  Clouds*, hidden, a collection for each kind inside it (*Field Cumulus*,
  *Field Puff*...). Untick **Hide Its Clouds** to see them beside the
  field, a row to a kind, select one and change it as any cloud, Shape Seed
  included: every copy follows. Any other cloud linked into a kind's
  collection is repeated as that kind. The **Collections** panel under
  Field says which collection each kind is taken from.
- They are made at 48 voxels in the viewport and 128 in a render, enough
  from far (a Flock at 96 and 192). Each has its own Quality.
- A copy scaled up is also more opaque, and one scaled down thinner: keep
  Smallest and Largest near 1 and set the size with Cloud Size.

With the plane selected, the **Field** panel says where the clouds stand:

| Setting | What it does |
| --- | --- |
| **Cumulus**, **Puff**, **Sheet**, **Flock**, **Shreds** | How much of the field is of each kind, against the others: with all five alike, a fifth of the clouds each. 0 leaves a kind out; one kind alone above 0 makes the whole field of it |
| **Sorting** | 0 mixes the kinds by chance. Higher, each keeps to its part of a patch: Sheet at the heart, then Cumulus, Flock, Puff, and Shreds at the rim. The rim is where Coverage puts it and where the paint thins the clouds out |
| **Coverage** | How much of the sky has clouds. A texture cast on the plane, a soft noise, says where: at 1 there is a cloud on every place; lower, they are left in patches with gaps between, and the patches shrink from their rims. The clouds that stay do not move or change |
| **Patch Size** | Width of the patches and of the gaps. Below Spacing, the clouds go one by one, as by chance |
| **Spacing** | Least distance between two clouds |
| **Smallest**, **Largest** | The copies' scale |
| **Scatter Seed** | Other places for the clouds |
| **Patch Seed** | Other patches on the same places |
| **Mix Seed** | Another draw of which cloud stands where, turned and scaled how |
| **Paint** | The vertex group that says where clouds may stand, see below |
| **Clouds** | The collection that is repeated |

Coverage is the part of the places kept, on average: a plane has room for
only a few patches, so one field can hold rather more or fewer. Try other
Patch Seeds.

With Sorting above 0, lowering Coverage moves the rims, so some of the
clouds that stay become another kind; they stay where they are, turned and
scaled the same. At Sorting 0 they stay the same cloud.

**Paint Clouds** puts the plane in Weight Paint, with a vertex group
*Clouds* full of 1 and the brush's weight at 0: paint, and the clouds under
the brush go. Weight 1 brings them back, as far as Coverage leaves them;
between the two there are fewer.

- **Brush Weight** is in the panel while you paint, and **Done Painting**
  goes back to Object Mode.
- The plane shows only while it is painted on. The clouds show as outlines
  then.
- Any vertex group of the plane can be picked in **Paint**; clear it to do
  without.
- A plane with faces wider than the Spacing is cut finer first, and that
  moves all its clouds to other places, once. A field made before 0.9.0
  has such a plane, of one face.

Under Field, **Look** has the controls of the material the field's clouds
have (see Material): the one all clouds share, unless you gave them
another.

On the PC it was written on, a field of some 60 clouds from 15 is there in
0.7 s and renders in about 8 s in Cycles at 1600 x 900 and 64 samples.

### Types

A type is a set of the Shape settings: all of them but Puffs and Seed.
Giving a cloud a type writes every one of them, so nothing is left of the
type it had or of what you changed by hand. Density, Material and Quality
are not a type's and stay.

| Type | Real cloud | What it is |
| --- | --- | --- |
| **Cumulus** | Cumulus | A heaped fair-weather cloud with a flat base |
| **Puff** | Cumulus humilis | A small, low, soft cloud, wider than tall |
| **Tower** | Cumulus congestus | A tall, crisp cloud growing upwards |
| **Anvil** | Cumulonimbus | A thunderstorm tower flaring into a thick anvil, flat on top, spread downwind |
| **Sheet** | Stratocumulus | A low patch of rounded masses grown into one another |
| **Flock** | Altocumulus | A field of small separate cloudlets |
| **Lens** | Lenticular | A smooth lens, or a stack of them, as over mountains |
| **Shreds** | Fractus | Small ragged pieces torn by the wind |
| **Layer** | Stratus | A flat, soft, featureless sheet |

Not there: cirrus and the other high ice clouds. They are streaks and veils
and need another way of building the shape.

### Puffs

**Puffs** says how far the cloud leaves its mesh, so it depends on the mesh
and not on the type. At 0 the cloud follows the mesh, creases and all.
Raised, it rounds the shape and breaks it into round lumps of its own.

- A cloud added from nothing starts at 0: its heap of spheres is a cloud's
  shape already, and at 0 the cloud is also quickest to work out.
- A mesh made into a cloud starts at 0.6: that is what makes a cloud out of
  a box.
- Changing a cloud's type leaves it alone.

### Settings

They belong to the active cloud. Every length is a part of the cloud's own
size, so a cloud looks the same whether it is 5 m or 5 km wide.

| Panel | Setting | What it does |
| --- | --- | --- |
| Shape | **Growth** | How far the cloud has grown: nothing at 0, its whole shape at 1. A young cloud is thin, frayed shreds of haze over part of the shape; as it grows they thicken, close up and get their body, and only near 1 does the cloud fill its shape. The shreds, lumps and hollows stay the size they are. Keyframe it to have a cloud form or dissolve |
| | **Puffs** | How far the cloud leaves the mesh for round lumps of its own. 0 follows the mesh |
| | **Puff Scale** | Number of round lumps across the cloud |
| | **Billows** | How far a large, soft noise pushes the shape around |
| | **Billow Scale** | Number of those pushes across the cloud |
| | **Erosion** | How deep the small hollows eat into the surface. This is what gives the cauliflower look |
| | **Erosion Scale** | Number of small hollows across the cloud |
| | **Softness** | Thickness of the fuzzy edge |
| | **Flat Base** | Part of the height cut flat at the bottom |
| | **Seed** | Another variation of the same cloud's detail. The mesh does not change |
| | **Shape Seed** | Only on a cloud added from nothing. Draws its heap of spheres again, as the type the cloud has now and as wide as the mesh is. It replaces the mesh: whatever was edited on it is gone, until undone. Greyed out in Edit Mode |
| Look | **Density** | How opaque the cloud is across its longest side, whatever its size |
| | **Material** | The cloud's material and its controls, see below |
| Quality | **Viewport** | Voxels along the cloud's longest side while you work |
| | **Render** | The same in a render. Twice the number is four times the work or more |
| | **Set Up Render** | The least the scene needs for clouds to look right, see below |

### Material

A cloud's material is in its object's first material slot, like any
object's: it shows in the Material tab and in the Shader Editor, and it is
changed there or in the Look panel, which shows the same slot.

- All clouds share **CocoClouds Cloud**: changing it changes every cloud,
  a field's too.
- The number beside its name makes a copy for this cloud alone.
- Any volume material can be picked in its place. One without the controls
  below shows **Use Cloud Material**, which puts the shared one back.
- A mesh of yours that had a material keeps it: while it is a cloud, the
  cloud's material covers it, and **Back to Mesh** brings it back.

Under the material's name the Look panel has its controls. They belong to
the material, so every cloud that has it follows.

| Control | What it does |
| --- | --- |
| **Color** | The colour of the cloud where it is thick and lit: a tint for a sunset or a storm. Thin parts stay whiter |
| **Brightness** | How white those parts are. Lower for a grey cloud under the same light |
| **Dark Base** | Darkens the cloud towards its base, fading out six tenths of the way up |
| **Wispy Edges** | Above 0 the edges thin out into wisps; below 0 they harden. The inside stays as dense |
| **Anisotropy** | Cycles only; the Principled Volume's own Anisotropy (called Silver Lining up to 0.14.0). How much of the light goes on forwards through the cloud: higher, the rim glows against the sun and the cloud is dimmer with the sun behind you. 0.6 to begin with |
| **Glow** | Light the cloud gives off by itself, in the cloud's own shape: night skies, lightning. 1 is about a white wall in daylight |
| **Glow Color** | The colour of that light |

- **Color, Brightness and Anisotropy cost a render nothing.**
- **Dark Base, Wispy Edges and Glow make Cycles take longer to prepare
  each render** while they are away from 0: the field above went from 9 s
  to between 16 and 19 s, the same few seconds more at 8 samples as at 256.
  One cloud close up took half a second to two seconds more. EEVEE takes
  the same time either way.
- **In the Shader Editor the material is a handful of nodes**, to read
  from left to right and to change:
  - **Cloud Data** reads what the cloud says of itself: its density, how
    far from the edge towards the core a place is, how high in the cloud.
  - **Wispy Edges**, **Color** and **Glow** each do one job with that, and
    carry the controls as their sockets.
  - a **Principled Volume** for Cycles, Blender's own volume shader, takes
    what they give and does the lighting. **Anisotropy** is its
    Anisotropy. Before it, **Many Bounces** turns the colour asked for
    into the one Cycles needs.
  - **Scene Light** holds the sun and the sky as the scene has them, and
    **Preview Light** works out from them the light EEVEE's own Principled
    Volume gives off.
  - The first four are groups: Tab into one to see how it works. A group
    is shared by every cloud material; the nodes around it are this
    material's own.
- **The Look panel shows the controls the material still has.** Put nodes
  of your own between, or take one out: a control you linked something
  into, or whose node is gone, leaves the panel and the rest go on working.
- A material from an earlier version works as it did and shows **Update
  Material** under its controls, which turns it into the nodes above with
  the values it has. The shared *CocoClouds Cloud* is updated by itself the
  next time a cloud is added, if nothing was added to it.
- Dark Base and Wispy Edges need the cloud to be on this version: on one
  that shows **Update Cloud** they do nothing until it is updated.

### In EEVEE

Whatever EEVEE draws, the viewport's Material Preview, its Rendered view
with EEVEE as the engine, or an EEVEE render, answers at once when a
slider, the sun or the rough shape moves. There is no button for it: pick
Material Preview in the viewport's header (turn on Scene World in its
shading menu to see the scene's sky behind the clouds).

EEVEE cannot light a cloud as Cycles does, so in EEVEE the cloud's material
lights it by itself, to look like the Cycles render:

- bright where the cloud faces the sun, with the sun's colour and strength;
- the shade filled with the world's colour;
- brighter looked at against the sun;
- a darker base under a high sun.

It follows the scene by itself: turn the sun or change the world and the
clouds follow. What it leaves out:

- only the strongest Sun light counts; point, spot and area lights do
  nothing to a cloud in EEVEE;
- a cloud casts no shadow on itself or on another cloud, so the hollows
  between its lumps are flatter than in Cycles;
- a world with a texture or a sky linked into its colour is taken as a
  plain blue of the same strength.

A cloud made with an earlier version is flat in EEVEE until **Update
Cloud** is pressed.

The render's own settings are yours to set. What counts most for clouds is
Cycles' Light Paths > Max Bounces > Volume: with 12 the lit side of a cloud
came out half as bright as with 256, with 32 at 0.73 of it, with 64 at 0.85.

### Cycles and EEVEE

Clouds are made for **Cycles**. A cloud is white because light bounces
around inside it, and only Cycles does that, once it is allowed to: a new
scene has Volume bounces at 0, and the cloud renders dark. **Set Up Render**
raises them to 12, the least that reads as a cloud; more makes the cloud
brighter, see In EEVEE above.

**EEVEE** lights a volume once and has no bounces, so the cloud material
does the lighting itself there (see In EEVEE above): close to Cycles in
brightness and in where the light comes from, flatter in the hollows.

EEVEE also has **Volumes > Custom Range** in the render settings. While it
is on, EEVEE draws no volume farther from the camera than its End, 100 m
unless changed: move away from a cloud and it is gone, whatever the
viewport's clipping. **Set Up Render** switches it off.

The Render panel warns while the scene's settings would give a dark cloud in
Cycles, a flat one in EEVEE, or none at all past a distance.

### What Set Up Render changes

Only the current scene's render settings, and only upwards:

| Engine | Setting | Becomes |
| --- | --- | --- |
| Cycles | Light Paths > Max Bounces > Volume | at least 12 |
| Cycles | Light Paths > Max Bounces > Total | at least 12 |
| EEVEE | Volumes > Resolution | 1:2 or finer |
| EEVEE | Volumes > Steps | at least 128 |
| EEVEE | Volumes > Shadows | on, at least 32 steps |
| EEVEE | Volumes > Custom Range | off |

It touches no object, material or light, and it can be undone.

## Limits, for now

- Clouds do not move.
- A long, thin shape gets few voxels across its thin side, because Quality
  counts them along the longest one.
- Puffs measures the shape as a whole. A piece much thinner than the rest
  is rounded away as Puffs goes up.
- A cloud made with an earlier version keeps working as it was and shows
  **Update Cloud**, which gives it the new settings; its look can change.
  It also gives it the material with the controls, in place of the one of
  0.8.0 and before, unless you changed that one by hand.
- A field made with an earlier version shows **Update Field**, which leaves
  it looking as it did and updates the clouds it repeats along with it.
  Such a field has clouds of one kind: it stays all of that kind, and the
  other kinds have no collection until you give them one.
- Anisotropy does nothing in EEVEE.
- A cloud added before 0.6.0 has no Shape Seed: its heap's seed was not
  kept.
- Flock and Shreds are many small pieces in one object, and Quality counts
  voxels across the whole of it: each piece gets few. Raise Viewport to
  judge them.
- Each render works the cloud out again at the Render quality, see below.

## How long a cloud takes

Every change to a setting or to the mesh works the cloud out again. On the
PC it was written on (12 threads), a cloud 6 m wide added from nothing:

| Type | Viewport, 96 | Render, 256 |
| --- | --- | --- |
| Cumulus | 0.11 s | 0.65 s |
| Puff | 0.09 s | 0.8 s |
| Tower | 0.10 s | 0.65 s |
| Anvil | 0.10 s | 0.6 s |
| Sheet | 0.07 s | 0.25 s |
| Lens | 0.06 s | 0.23 s |
| Flock | 0.05 s | 0.19 s |
| Layer | 0.06 s | 0.15 s |
| Shreds | 0.05 s | 0.12 s |

A step of Shape Seed adds a few thousandths of a second to that.

The time follows the volume of the cloud and the Quality, not the size in
metres nor the number of vertices of the mesh. What costs:

- **Quality.** Twice the voxels across is eight times the voxels.
- **Puffs above 0** adds a second noise and a blurred copy of the shape: a
  box at Puffs 0.6 takes about twice a heap as wide.
- **A field** costs its few clouds, not its copies.
- **Billows** at 0 costs nothing. Above 0 the large noise is worked out on
  a coarse grid, for next to nothing, once the cloud has 64 voxels across
  for each unit of Billow Scale: 128 at scale 2, 256 at scale 4. With fewer
  voxels than that the grid would turn the billows into flat facets, so the
  noise is worked out on every voxel: up to half as much time again at 256.
