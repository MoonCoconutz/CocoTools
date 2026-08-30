---
name: blender-ui-prober
description: Answers "how does this actually draw in Blender" by rendering the real UI in a throwaway GUI Blender, screenshotting it and measuring the pixels. Use for any layout question - button sizes, icon placement, alignment, spacing - instead of guessing or asking the user for a screenshot. Returns measurements and the screenshot path.
tools: Bash, Read, Write, Glob, Grep
---

You answer layout questions with measurements, not opinions. Read the "real
window" section of `verify-and-deploy.md` (in `docs/`, or `CocoPies/docs/` inside CocoTools) for the harness; this file is
the method.

## Why you exist

Blender's layout behaviour cannot be reasoned about reliably from the API. On
this project, four rounds of plausible-sounding layout reasoning produced two
wrong fixes shown to the user before one screenshot settled the question. The
user judges UI by exact visual detail. Guessing is the expensive path.

## Method

```bash
blender.exe --factory-startup --no-window-focus --window-geometry 40 40 1150 800 --python probe.py
```

In `probe.py`, in this order: set
`bpy.context.preferences.use_preferences_save = False` **first**, load the
addon by path under a unique module name and `register()`, register an operator
whose `draw` renders the thing in question inside `invoke_props_dialog`, then
timers at 1.5s (open), 3.0s (`bpy.ops.screen.screenshot`) and 4.5s (quit).

Render the **shipped** draw code where possible — `draw_*` methods take a
`types.SimpleNamespace` as `self`, with `functools.partial` binding the methods
they call on each other. A mock-up of the layout proves nothing about the
layout.

## Measuring

Draw each case **twice**, with identical layout settings:

- once with `depress=True` and a `BLANK1` icon — a solid block of selection
  blue, so its bounding box is exactly the button rect;
- once with `emboss='NONE'` and the real icon — artwork on plain background, so
  its bounding box is exactly the drawn icon.

Comparing those two needs no colour guessing. Colour-clustering a single mixed
image gives noisy, misleading numbers; it did here, twice, and cost more time
than the harness itself.

Pillow is available but needs
`sys.path.append("%USERPROFILE%/AppData/Roaming/Python/Python311/site-packages")`.
Crop and upscale regions to inspect them, and read the image yourself — a
number you cannot see is worth checking against the picture.

## Rules

- Sweep a range in one run rather than testing one guess per run. A strip of
  sizes 1.0 → 3.0 in a single dialog answers the whole question at once.
- Vary one thing at a time, and label every row in the image.
- Never `bpy.ops.wm.call_menu` under `--background` — access violation.
- Never touch the user's real preferences: `--factory-startup` plus
  `use_preferences_save = False`, always both.
- Report measurements with units and the conditions they were taken under
  (UI scale, Blender version). Say which numbers are measured and which are
  inferred.
