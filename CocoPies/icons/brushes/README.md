# Sculpt brush icons

Blender's own pre-4.3 sculpt brush icons, as triangle geometry (`.dat`), taken
from the "3D Viewport Pie Menus" extension shipped by the Blender Foundation
(`extensions.blender.org`, GPL-3.0-or-later). Blender dropped these from its
built-in icon set when brushes became assets in 4.3, so there is no
`bpy.types.UILayout` icon name for any of them any more -- the whole built-in
set now has three brush icons in total.

Loaded with `bpy.app.icons.new_triangles_from_file()`, which is a different
mechanism from the PNG previews in `icons/custom/`: it needs no GPU, so unlike
a preview these still resolve under `--background`.

Referenced from a pie slot as `brush:<name>`, where `<name>` is the last
dot-separated part of the filename -- `brush.sculpt.draw_sharp.dat` is
`brush:draw_sharp`.
