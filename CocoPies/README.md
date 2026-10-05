# CocoPies

Build custom Blender pie menus without writing an addon. Everything — the
shortcut, the eight slots, the icons, the commands each slot runs — is
configured from the addon preferences, and the menus are registered live as
you edit them.

Requires **Blender 5.2 or newer** (since 1.13.0; 1.12.7 was the last version
for 4.5).

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
the Add-ons list to get to it. The left column lists your pies, grouped in
sections by editor; the right column edits the selected one.

The toolbar above the list has **New**, **Duplicate**, **Delete**, **▲▼**
(move the selected pie within its section) and a **Presets** menu: Export,
Import, Restore Starter Pies, Refresh All Keymaps and Delete All Pie Menus.
Click a pie's name to select it; click it again, or double-click, to rename
it. The tick beside the name turns the pie on or off.

## Creating a pie menu

**New** creates one. Each menu has:

| Setting | What it does |
| --- | --- |
| **Name** | Title shown when the pie opens |
| **Style** | *Pie* (eight directions) or *List* (a plain dropdown, in slot order) |
| **Editor** | Where the shortcut is active — *Window (Global)*, a single **mode** (Object, Mesh edit, Sculpt, the paint modes, UV Editor…), or a whole **editor** (3D View, Node Editor, Sequencer…). The **Editors** button opens a list of checkboxes, so one pie can live in several; it shows the editor's name, or *Multiple* |
| **Key** + **Any / Shift / Ctrl / Alt** | The shortcut. Click the Key field and press it, modifiers included — the text follows live, like Blender's own keymap editor (*Alt + …*, then *Alt + R*). Esc or a mouse click cancels. A pie with no key is only opened from another pie |
| **Trigger** | *Any*, *Press*, *Release*, *Click*, *Double Click*, *Drag*, or *Nothing* — the same set, same names, as Blender's own keymap editor |
| **Quick Tap** | Press and drag opens the pie, a quick tap does something else instead: alternate between two chosen directions, or run a command. It sets the Trigger to *Drag*; turning it off puts back the Trigger you had |
| **Enabled** | Unregisters the menu and its shortcut when off |

The modifier row (**Any / Shift / Ctrl / Alt**) is the same one Blender's own
keymap editor draws for a shortcut, in the same order, doing the same thing:
**Any** means the shortcut fires regardless of which modifiers are held,
overriding the other three whatever they show — that is not a CocoPies
convention, `wm.keymap_items.new(any=True)` forces this in Blender itself.
There is no Win/Cmd toggle: the operating system takes those combinations
before Blender sees them.

When a shortcut is also bound elsewhere, a yellow box lists who owns it. Tick a
row to have CocoPies switch that binding off while CocoPies is enabled; it is
switched back on when you untick it or disable CocoPies.

CocoPies warns you when two **enabled** menus would fight over the same
shortcut, including the case where one is global and the other is
editor-specific, and the case where one has **Any** set and would swallow the
other's more specific combination.

The ▲/▼ buttons beside **New Pie Menu** reorder the list. That ordering is
purely cosmetic — it changes nothing about shortcuts or registration, it is
only how the menus are listed in the editor.

> *Window (Global)* registers the shortcut in Blender's own *Window* keymap, so
> it fires in every editor: the 3D viewport, UV editor, node editors, text
> editor and the rest. Any editor or mode that has its own binding on the same
> key still takes the key first. The editor shows such bindings as conflicts.
> Scope a menu to a **mode** when you want one key to mean different things in
> different contexts: two pies can share a key freely as long as the modes they
> are scoped to don't overlap.

## What you get on install

A fresh install lays down starter pie menus, so CocoPies is useful before you
configure anything:

| Pie | Shortcut | Scope | What it does |
| --- | --- | --- | --- |
| **Workspace Menu** | `Shift + T` | Global | Jump to Shading, Layout, UV Editing, Geometry Nodes, Sculpting, Scripting, Modeling or Rendering. A tap alternates Layout / UV Editing |
| **Edge Info** | `Alt + 2` | Global | Toggle the sharp / seam / crease / bevel-weight overlays |
| **Animation** | `Shift + Space` | Global | Play, play reverse, jump to start / end, previous / next keyframe, auto keying, keyframe menu |
| **UV Unwrap** | `Shift + F` | UV Editor | Mio3 unwrap, unwrap along X / Y (CocoUVs Unfold Along U / V), align X/Y, rectify, gridify, classic unwrap |
| **UV Transform** | `Shift + D` | UV Editor | Flip, rotate, stack, sort and orient islands |
| **UV Select** | `Shift + A` | UV Editor | Select similar, overlapping, zero-area, flipped, done, self-intersecting, boundary |
| **3D UV** | `Shift + F` | 3D View | Mark / clear seams, smart project, unwrap, bevel weight, crease, sharp |
| **Region Toggle** | `N` | 3D View | Show the toolbar, sidebar, tool settings, header, last-operation panel or asset shelf |
| **Mesh Delete** | `X` | Mesh edit | Delete and dissolve by element. A tap deletes the selection without the menu |
| **Mesh Merge** | `M` | Mesh edit | Merge by distance, at center, collapse, at first / last, at 3D cursor |
| **Mesh Flatten** | `Shift + M` | Mesh edit | Scale the selection flat on X, Y or Z, around the world centre or the 3D cursor |
| **Mesh Select** | `A` | Mesh edit | Select more / less, all, none, invert, linked. A tap alternates select all / deselect all |
| **Proportional Edit** | `O` | Object mode, Mesh edit | Falloff shapes and toggles. A tap turns proportional editing on or off |
| **Curve Delete** | `X` | Curve edit | Delete vertices or segments. A tap deletes the segment |
| **Add Object** | `Shift + Ctrl + A` | Object mode | Common primitives, plus the full Add menu |
| **Apply Transforms** | `Ctrl + A` | Object mode | Apply rotation / scale / location, visual transform, make single-user, and a Clear Transforms list |
| **Object Parenting** | `P` | Object mode | Set and clear parent, with and without keeping the transform |
| **Sculpt Brush Select** | `W` | Sculpt | Mask, Grab, Draw, and four sub-pies holding the rest of the bundled brushes |

The two delete pies switch Blender's own X delete menu off while CocoPies is
enabled, so a tap on X reaches them (untick it in the pie's settings to give X
back).

UV Transform is mostly [Mio3 UV](https://github.com/mio3io/mio3-uv) — Flip X/Y
and Rotate 90 are stock Blender (`transform.resize` / `transform.rotate`, the
same as `S X -1` and `R -90`), so those three work regardless. Stack Islands is
Mio3 Align ▸ Center in island mode (Bounding Box pivot: islands stack in place,
not at the UV centre). UV Unwrap is Mio3 apart from the classic unwrap and
UV Unwrap X / Y, which are **CocoUVs'** Unfold Along U / V; its Gridify runs
with Geometry Ratio 0. UV Select is Mio3 UV, with Select
Overlapping, Select Done and Select Self Intersecting coming from **CocoUVs**
(also in the CocoTools repository). Without the addon a slot depends on, it
simply reports a missing operator; install it and that slot starts working
with no edit needed.

Starter pies are recorded once given, so one you delete or rename never comes
back on the next startup — while a starter added by an update still appears on
its own. **Restore Starter Pies**, under Presets, adds back any that are
missing and leaves everything else alone. **Delete All Pie Menus**, in the
same menu, deletes every pie at once, after asking; the keys the pies took (Blender's X delete menus)
are given back.

### The bundled example scripts

The Workspace pie runs script files rather than inline commands, as a worked
example of `execute_script()`. They ship inside the addon at
`CocoPies/scripts/workspaces/`.

Open one to see the shape a script slot expects, then copy it for your own.

`CocoPies/scripts/delete/MeshDeleteNoMenu.py` is the one script that exists
because Blender has no operator for the job: Mesh Delete's tap. It deletes the
selection without a menu, dissolving vertices or edges rather than punching
holes, according to the select mode.

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
real tooltip, enabled/disabled state and redo panel (the operator's options in
the editor's bottom-left corner):

```python
bpy.ops.mesh.subdivide()
```

This needs a plain call with literal keyword arguments. Anything more (an
`if`/`else`, a variable, two statements) still runs, but as a script, with no
redo panel. An option the installed operator doesn't have is skipped instead
of failing, so one command can use options a newer version of an add-on added.

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
Blender → Add to CocoPies**. It works on any operator button and on any
setting, wherever it lives: viewport overlays and shading, tool settings
(snapping, proportional editing), the active object and its modifiers,
materials, the world, render settings, the Preferences. It fills in the
command and a label:

- an operator keeps the options its button sets (Add Modifier ▸ Bevel adds a
  Bevel), and runs as if you clicked the button;
- an on/off setting becomes a switch that flips it;
- a setting with a list of choices (Proportional Editing Falloff, Shading)
  asks which choice the slot should set, starting from the current one;
- one field of a row (Location X) sets just that field.

Settings of the active object, scene or editor follow whatever is active when
you open the pie, not the one you right-clicked.

The submenu lists every pie you have, each opening onto its eight directions
so you can see which are free before picking one. Choosing a direction that is
already taken asks before replacing it.

**Add a New Pie...**, at the top of that list, skips the Preferences window
entirely: name the pie, and it is created with the button you right-clicked on
its Left direction. It has no keyboard shortcut yet — give it one in
Preferences when you are ready to use it.

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

**Export** / **Import** (in the Presets menu) write and read plain JSON, so configurations
are easy to share or keep in version control.

Loading never wipes what you already have. If an incoming menu's name matches
one of yours, CocoPies asks whether to **replace** the matching menus or
**skip** them; menus with new names are always added.

This is the only backup of your menus. Blender's own **Keymap ▸ Preset** is a
separate thing and does not include CocoPies' shortcuts — saving one while
CocoPies is enabled produces a clean keymap preset (no need to disable the
add-on first), but it will not bring your pies back.

Switching between keymap presets is safe: as soon as the Keymap section
redraws, CocoPies switches off again any Blender shortcut you told it to
override.

## Troubleshooting

**A shortcut does nothing.** Check the menu is enabled, and look for a conflict
warning — another enabled menu, or one of Blender's own keymaps, may already
own that combination. `Q` in particular is taken by default in several editors.

**A menu looks stale after editing.** **Refresh All Keymaps**, in the Presets
menu, rebuilds every CocoPies shortcut from scratch — also the fix when a
shortcut stopped working after another add-on or a keymap preset change.

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
  presets.py                preset reading/writing, merging and collision handling
  defaults.py               starter pies, and the scripts they run
  previews.py               loads CocoPies' own icons: slot arrows, sculpt brushes, custom
  preferences.py            the pie editor panel
  operators/                everything the buttons call
  ui/                       list rows, the list toolbar and Presets menu, the Editors picker
  icons/                    the slot arrows, the sculpt brush icons, your custom icons
  scripts/workspaces/       the bundled example scripts
  scripts/delete/           Mesh Delete's tap, which Blender has no operator for
```
