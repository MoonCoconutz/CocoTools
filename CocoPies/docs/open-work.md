# Open work

State as of **2026-08-30**. Check the facts before acting on them — this file
is a starting point, not an authority.

## 1. Close the local ↔ CocoTools drift

**Why it matters:** the local repo is behind CocoTools on several files, so
any future "copy the package across and commit" reverts published work. It was
caught one command short of doing exactly that.

CocoTools is ahead in `presets.py` (a published
`_repoint_missing_bundled_script()` fix), `utils.py`, `scripts/uv/` (a whole
folder), and `README.md`. See the table in [publishing.md](publishing.md).

Backporting into the local repo would close it, with two decisions to make
first:

- `__init__.py` — CocoTools has no `bl_info` (extension), the local copy needs
  one for the 4.5 legacy install. These may have to stay deliberately
  different, in which case say so in `CLAUDE.md` rather than "fixing" it.
- `CLAUDE.md` — CocoTools split it into a shared root file and a
  CocoPies-specific one. The local repo still has the old monolithic version.
  Either adopt the split locally or accept the divergence explicitly.

The user was offered this backport and had not answered when this file was
written.

## 2. 1.10.1 is committed but not released

`CocoPies-v1.10.1` exists in `main` (commits `bf33ffe`, `b7ed844`) with the
manifest bumped, but **no tag has been pushed**, so nothing has been built or
published to the Blender feed. Last published tag is `CocoPies-v1.10.0`.

To release, and only with the user's go-ahead:

```bash
git tag CocoPies-v1.10.1 && git push origin CocoPies-v1.10.1
```

## 3. The installed copies were hand-bumped

Both installs were updated by copying files, and their version strings edited
by hand to `1.10.1` (4.5's `bl_info`, 5.2's manifest) so the extension updater
cannot reinstall the older published zip over them. They are therefore *not*
byte-identical to what a real `extension build` would produce. If anything
looks strange in the 5.2 install, reinstall it properly rather than debugging
the hand-deploy — see the recovery recipe in [publishing.md](publishing.md).

## 4. Possible follow-up on the brush icons

Converting the sculpt brush icons from `.dat` geometry to PNG fixed the click
target, the selection highlight, the grid spacing and the item-row alignment —
but it also means they now draw at normal icon size (~18px) rather than the
oversized ~31px they used to. That is inherent to them behaving like icons.

If the user wants them larger, the lever is now available in a way it was not
before: the button genuinely contains the icon, so the picker's cells can be
scaled with `scale_x`/`scale_y`. Raising `IMAGE_GRID_COLUMNS` down from 16
would also give each one more room. He has not asked for this; do not do it
unprompted.

## Recently closed, for context

- Sculpt brush icons converted from `bpy.app.icons` triangle geometry to PNGs
  through the preview collection; the two workarounds built around the old
  behaviour (the Icon column's second wider width, and dropping the button
  frame for image icons) were removed with it.
- The Icon button is square again, via `scale_x` — `ui_units_x` never could
  size it.
- Icon picker: gaps between icons on the Custom and Brush tabs; built-in tabs
  deliberately untouched at the user's request.
