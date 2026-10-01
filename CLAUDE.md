# CLAUDE.md

CocoTools holds Blender extensions, one per top-level folder, each with its
own `blender_manifest.toml`: **CocoPies**, **CocoBackup**, **CocoSelections**,
**CocoUVs** and **CocoCutter**. All are Blender 5.2+ only.

## The documentation is in the Obsidian vault

Everything about this repository lives in the user's Obsidian vault, GitHub
repo `MoonCoconutz/Obsidian`: how to develop, verify and release, how each
add-on works, and how the user wants you to work. This file is only a
pointer. Do not grow it.

- Home PC: `C:\Users\Deso\Documents\Claude\3D Knowledge`
- Work PC: `C:\Users\d_desogus\Documents\Claude\Obsidian`
- Elsewhere: clone it to `%USERPROFILE%\Documents\Claude\3D Knowledge`.

`git pull` it before reading. After writing to it, commit and push.

Read:

1. `Working with Claude.md` (vault root), at the start of every session.
2. `Projects/CocoTools development.md`, before changing any code.
3. `Projects/<Extension> development.md` for the add-on you touch, and
   `Projects/<Extension>.md` for what it does for the user.

Anything new worth keeping goes into the vault, not into this file and not
into a local memory file.

## Never

- Delete `CocoPies/icons/custom/`: the user's own artwork, gitignored, with
  no backup.
- Reload an add-on with `bpy.ops.preferences.addon_disable`: it drops the
  stored settings. Use `addon_utils.disable/enable(..., default_set=False)`.
- Commit a change to an add-on's behaviour without bumping that add-on's
  manifest version in the same session.
- Push a release tag without asking the user first.
- Edit add-ons the user did not write.
- Report a change as working before verifying it on Blender 5.2.
