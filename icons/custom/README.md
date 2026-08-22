# Custom icons

Any PNG (or JPG) dropped in here appears under the **Custom** tab of CocoPie's
icon picker, named after the file: `flatten.png` becomes `flatten`. Reload the
addon, or restart Blender, to pick up newly added files.

Square images around 64x64 work best — Blender scales them down to icon size.
A white shape on transparency matches the look of Blender's own icons on a dark
theme, since preview icons are drawn as-is and are not tinted.

Note that reinstalling CocoPie replaces its whole folder, this one included.
Keep a copy of anything you would not want to redraw.

## It has to be a real PNG

Renaming a file does not convert it. A `.ico` renamed to `.png` is still an ICO
inside, and Blender loads it as a blank preview — the icon appears in the grid
with nothing in it. CocoPie now checks each file's header and skips one whose
contents do not match its name, printing what it actually is to the console.

Many `.ico` files contain a PNG already, so converting is often just a matter of
exporting it as PNG from any image editor.
