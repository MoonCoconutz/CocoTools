# CocoPies

Build custom Blender pie menus without writing an addon. Everything — the
shortcut, the eight slots, the icons, the commands each slot runs — is
configured from the addon preferences, and the menus are registered live as
you edit them.

Requires **Blender 4.5 or newer**. Tested on 4.5.8 LTS and 5.2 LTS.

---

## Install

Add the CocoTools repository to Blender: **Edit → Preferences → Get
Extensions →** repositories dropdown **→ + → Add Remote Repository**, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

CocoPies then shows up as an installable/updatable extension there — enable
it. (This addon used to be its own single-extension repository at
`MoonCoconutz/CocoPies`, which no longer exists; it moved into the CocoTools toolbox
repository, same code, new home.)

The editor lives in the addon's own preferences panel — expand CocoPies in
the Add-ons list to get to it.

## Creating a pie menu

**Add Pie Menu** creates one. Each menu has:

| Setting | What it does |
| --- | --- |
| **Name** | Title shown when the pie opens |
| **Editor** | Where the shortcut is active — *Window (Global)*, a single **mode** (Object, Mesh edit, Sculpt, the paint modes, UV Editor…), or a whole **editor** (3D View, Node Editor, Sequencer…) |
| **Key** + **Any / Shift / Ctrl / Alt / OS** | The shortcut. Letters are upper-cased automatically |
| **Trigger** | *Any*, *Press*, *Release*, *Click*, *Double Click*, *Drag*, or *Nothing* — the same set, same names, as Blender's own keymap editor |
| **Enabled** | Unregisters the menu and its shortcut when off |

The modifier row (**Any / Shift / Ctrl / Alt / OS**) is the same one Blender's
own keymap editor draws for a shortcut, in the same order, doing the same
thing: **Any** means the shortcut fires regardless of which modifiers are held,
overriding the other four whatever they show — that is not a CocoPies
convention, `wm.keymap_items.new(any=True)` forces this in Blender itself.

CocoPies warns you when two **enabled** menus would fight over the same
shortcut, including the case where one is global and the other is
editor-specific, and the case where one has **Any** set and would swallow the
other's more specific combination.

The ▲/▼ buttons beside **New Pie Menu** reorder the list. That ordering is
purely cosmetic — it changes nothing about shortcuts or registration, it is
only how the menus are listed in the editor.

> *Window (Global)* is not literally global. It registers the shortcut into the
> nine 3D viewport mode keymaps — Object Mode, Mesh, Curve, Armature, Pose,
> Sculpt and the three paint modes — and **nowhere else**. A global pie
> therefore never fires in the UV editor, the node editor, or any other editor.
> Scope a menu to a **mode** when you want one key to mean different things in
> different contexts: two pies can share a key freely as long as the modes they
> are scoped to don't overlap.

## What you get on install

A fresh install lays down starter pie menus, so CocoPies is useful before you
configure anything:

| Pie | Shortcut | Scope | What it does |
| --- | --- | --- | --- |
| **Workspace Menu** | `Shift + T` | Global | Jump to Shading, Layout, UV Editing, Geometry Nodes, Sculpting or Scripting |
| **Edge Info** | `Alt + 2` | Global | Toggle the sharp / seam / crease / bevel-weight overlays |
| **UV Unwrap** | `Shift + F` | UV Editor | Mio3 unwrap and axis unwraps, align X/Y, rectify, gridify, classic unwrap |
| **UV Transform** | `Shift + D` | UV Editor | Flip, rotate, stack, sort and orient islands |
| **UV Select** | `Shift + A` | UV Editor | Select similar, overlapping, zero-area, flipped, boundary |

UV Transform is mostly [Zen UV](https://zenuv.rocks) — Flip X/Y and Rotate 90
are stock Blender (`transform.resize` / `transform.rotate`, the same as
`S X -1` and `R -90`) so those three work regardless. UV Select mixes Zen UV
with [Mio3 UV](https://github.com/mio3io/mio3-uv), except **Boundary**, which
runs a bundled script — Blender has no operator that selects island borders,
so CocoPies ships one (see below). UV Unwrap is all Mio3. Without the addon a
slot depends on, it simply reports a missing operator; install it and that
slot starts working with no edit needed.

Starter pies are only created when there is **no** configuration at all, so one
you delete or rename never comes back on the next startup. **Restore Starter
Pies**, under Presets, adds back any that are missing and leaves everything
else alone.

### The bundled example scripts

The Workspace pie runs script files rather than inline commands, as a worked
example of `execute_script()`. They ship inside the addon at
`CocoPies/scripts/workspaces/`.

Open one to see the shape a script slot expects, then copy it for your own.

`CocoPies/scripts/uv/` holds scripts that exist because Blender has no operator
for the job at all. **SelectUVBoundary.py** selects the border edges of every
UV island: it counts how many faces use each edge *in UV space*, and an edge
used only once is a border. That finds real mesh boundaries and UV seams in one
pass, without needing to tell them apart — a closed cube has no open mesh edges
at all, yet still has island borders wherever its UVs were cut.

The path a slot stores is resolved from the addon's own location when the
starter pies are created, so it points at wherever CocoPies was installed. This
matters: pie items store **absolute** paths, and an absolute path written on one
machine — or under one Blender version — does not survive being carried to
another. Resolving at creation time is what keeps the starter pie working
everywhere.

## Slots

A pie has eight slots, laid out as a compass:

```
↖  ↑  ↗
←     →
↙  ↓  ↘
```

The arrows are custom icons shipped in `CocoPies/icons/`. Blender's own arrow
icons are cardinal only — there is no diagonal arrow anywhere in its 1000-odd
icons — so four of a pie's eight directions have nothing built in to point at.
If those PNGs are ever missing, the arrows quietly fall back to text glyphs.

**The Menu Items table always shows all eight directions, in that fixed order.**
The row *is* the slot: the first row is always ←, the second always →, and so
on. There is nothing to add, remove or move.

A direction is in use once it has a label or a command, and the pie shows only
the ones in use. The **✕** on a row clears that direction and leaves the row
behind, empty and ready to fill again.

## What a slot can run

The **Command** field accepts four forms, and CocoPies picks how to draw the
button based on which one it sees:

**Operator** — drawn as a native Blender operator button, so it inherits the
real tooltip and enabled/disabled state:

```python
bpy.ops.mesh.subdivide()
```

**Property assignment** — if the left side resolves to a boolean, the slot is
bound directly to that property and draws as a **live toggle**, lit when the
value is `True`, the way Blender's own overlay buttons behave:

```python
bpy.context.space_data.overlay.show_wireframes = True
```

**Submenu** — opens an existing Blender menu instead of running a command:

```python
bpy.ops.wm.call_menu(name='VIEW3D_MT_snap')
```

**Script file** — runs a `.py` file. The **Pick Script** button fills this in
for you and names the item after the file:

```python
execute_script("C:/scripts/my_tool.py")
```

Anything else is executed as plain Python.

> Commands are run with `exec()`. A pie menu is therefore as trusted as any
> script you run in Blender — be as careful with imported presets as you would
> be with a `.blend` containing scripts.

## Adding items by right-clicking

You don't have to type commands by hand. **Right-click almost any button in
Blender → Add to Pie Menu**. This works on operator buttons and on property
toggles (overlay switches and the like), and fills in the command, a label,
and a sensible icon.

## Icons

The icon button opens a browser for every icon Blender ships, filtered by
category — Mesh, Object, Modifier, Shading, Anim, Color, File, Input, UI, and
Other — with a search box.

### Custom icons

The **Custom** tab holds your own. Drop PNG or JPG files into the addon's own
icons folder (inside wherever this extension is installed —
`CocoPies/icons/custom/`), and they appear there named after the file —
`flatten.png` becomes `flatten`.

Custom icons are read from disk once, so a file added while Blender is running
will not appear on its own. **Reload icons from folder**, at the top of the
Custom tab, re-reads it without restarting.

It has to be a real PNG or JPG: renaming a `.ico` to `.png` leaves it an ICO
inside, which Blender loads as a blank preview. CocoPies checks each file's
header and skips mismatches, naming the real format in the console.

Square images around 64×64 work best. A white shape on transparency matches
Blender's own icons on a dark theme, since custom icons are drawn as-is and are
**not** tinted by the theme the way built-in ones are.

The picker prints that path when the Custom tab is empty, so you never have to
look it up.

> Everything CocoPies owns lives inside its own folder, which means reinstalling
> the addon replaces your custom icons along with the rest of it. Keep a copy
> elsewhere, or commit them alongside the addon, if they matter.

An item stores a custom icon as `custom:<name>`. If that file later goes missing
the slot falls back to a blank icon rather than breaking the menu.

## Presets

**Export** / **Import** write and read plain JSON, so configurations
are easy to share or keep in version control.

Loading never wipes what you already have. If an incoming menu's name matches
one of yours, CocoPies asks whether to **replace** the matching menus or
**skip** them; menus with new names are always added.

## Troubleshooting

**A shortcut does nothing.** Check the menu is enabled, and look for a conflict
warning — another enabled menu, or one of Blender's own keymaps, may already
own that combination. `Q` in particular is taken by default in several editors.

**A menu looks stale after editing.** **Refresh Menus** re-registers
everything from scratch.

**Tracing registration.** Set `DEBUG = True` in `CocoPies/utils.py` to
log every menu class and keymap as it registers. It's off by default because
registration is rebuilt on every settings change, which makes it noisy while
typing. Errors are always reported regardless.

## Repository layout

```
CocoPies/                    the addon (a folder in the CocoTools monorepo)
  blender_manifest.toml     Blender Extension manifest: id, version, license, permissions
  __init__.py               class registry, register/unregister
  items.py                  constants: slot geometry, sizing, keymap table
  utils.py                  preferences lookup, shortcut and conflict helpers
  icons.py                  Blender's icon catalogue, grouped for browsing
  properties.py             the stored data: a pie, and an item in it
  menus.py                  builds the Menu class that draws a pie
  keymaps.py                registers pie classes and their shortcuts
  presets.py                preset merging and collision handling
  defaults.py               starter pies, and the scripts they run
  previews.py               loads the custom slot arrow icons
  preferences.py            the pie editor panel
  operators/                everything the buttons call
  ui/                       list widgets
  icons/                    the eight slot arrows, plus shipped custom icons
  scripts/workspaces/       the bundled example scripts
  scripts/uv/               UV helpers Blender has no operator for
```
