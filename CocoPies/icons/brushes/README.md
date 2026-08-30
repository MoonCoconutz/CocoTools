# Sculpt brush icons

Blender's own pre-4.3 sculpt brush icons. Blender dropped these from its
built-in icon set when brushes became assets in 4.3, so there is no
`bpy.types.UILayout` icon name for any of them any more -- the whole built-in
set now has three brush icons in total.

Referenced from a pie slot as `brush:<name>`, where `<name>` is the file name
without its extension -- `draw_sharp.png` is `brush:draw_sharp`. They load
through the same `bpy.utils.previews` collection as `icons/custom/`.

## Why PNGs and not the original `.dat` geometry

They arrived here as triangle geometry (`.dat`), taken from the "3D Viewport
Pie Menus" extension shipped by the Blender Foundation
(`extensions.blender.org`, GPL-3.0-or-later), and loaded with
`bpy.app.icons.new_triangles_from_file()`. That mechanism needs no GPU, so
unlike a preview those icons still resolved under `--background`.

The catch is how Blender *draws* them. Measured in a real window at UI scale
1.0: a geometry icon is drawn 31px square, while the button it belongs to is
23px and does not grow to fit it. A built-in icon or a preview PNG is drawn
~18px and sits centred inside that button. So the geometry icons overflowed
their own buttons, which is not cosmetic -- the button is the click target and
the selection highlight, so only a corner of each icon was clickable, the
highlight on the chosen icon was hidden underneath it, and icons in a grid ran
into their neighbours no matter what spacing the layout asked for.

Rendered to PNG they draw like every other icon. The conversion, if it is ever
needed again from a fresh set of `.dat` files (the originals are in this
repository's git history):

* header `VCO\0`, then 4 more header bytes;
* then every vertex's coordinates, 2 bytes each, x and y in 0-255 with the
  origin at the **bottom left**;
* then every vertex's colour, 4 bytes RGBA each;
* vertices are consecutive triples forming flat-shaded triangles, so the file
  holds `(size - 8) / 6` of them.

Draw the triangles with any rasteriser (supersample and downsample -- they have
no antialiasing of their own), crop to the artwork, pad back to square with a
small even margin, and save at 128px.
