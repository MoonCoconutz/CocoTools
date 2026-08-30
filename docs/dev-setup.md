# Setting up the dev channel

One-time setup, on the user's Windows machine, covering **every extension in
this repo**. The result: a git clone that *is* the live install in both Blender
4.5 and 5.2, so editing a file and reloading is the whole loop — nothing built,
nothing uploaded, nothing public.

The clone lives at:

```
%USERPROFILE%\Documents\Claude\CocoTools
```

## Why this is worth the hour

Two channels, cleanly separated:

| Channel | What it is | Public? |
|---|---|---|
| **Dev** | a Local Repository pointed at the clone above | No — never leaves the disk |
| **Released** | the Remote Repository at `https://mooncoconutz.github.io/CocoTools/index.json` | Yes |

Before this, the only way to look at a change in Blender was to publish it to
the public feed. That is backwards. After this, the feed is only ever touched
for real releases.

Blender scans a local repository's immediate children for
`blender_manifest.toml`, so **CocoPies, CocoSelections and CocoDelete all
appear at once** from the one directory. A new extension folder added later
shows up on its own.

## The one thing that can go wrong

Blender keys an addon's saved preferences by its **module name**. Installed
from the feed that is `bl_ext.mooncoconutz_github_io.<Extension>`; from a local
repository it becomes `bl_ext.<local repo name>.<Extension>`. Different name,
so Blender sees a fresh install with empty preferences.

What that costs, per extension:

| Extension | Where its data lives | Effect |
|---|---|---|
| **CocoPies** | `AddonPreferences` — every pie menu | **All pies appear gone**, and starter pies get seeded into the blank. Back up first. |
| **CocoDelete** | `AddonPreferences` — three on/off toggles | Back to defaults (all on). Re-tick if you had changed them. |
| **CocoSelections** | the Scene, saved in each `.blend` | Unaffected. Nothing to do. |

Nothing is corrupted and the old entry is not deleted — the data just does not
carry over on its own. Step 1 is what makes this a non-event.

## Steps

Do all of it in **both** Blender 4.5 and 5.2. They have separate preferences.

### 1. Back up — do not skip

- **CocoPies** preferences → **Save Preset**. This writes every pie menu to a
  JSON file. Put it somewhere outside the addon folder.
- Copy **`CocoPies/icons/custom/`** out of the installed folder. It holds your
  own artwork, is deliberately not in git, and has no backup behind it. Find
  the installed path in Preferences → Add-ons → CocoPies (expand the entry).
- **CocoDelete** — note which of its three toggles you have changed, if any.
- **CocoSelections** — nothing; its data is in your `.blend` files.

### 2. Clone the repo

```bash
git clone https://github.com/MoonCoconutz/CocoTools "%USERPROFILE%\Documents\Claude\CocoTools"
```

### 3. Add it as a Local Repository

Preferences → Get Extensions → the repositories dropdown (top right) → **+** →
**Add Local Repository**:

- Directory: `%USERPROFILE%\Documents\Claude\CocoTools`
- Give it a short name — that name becomes part of every extension's module
  name, so pick one and never change it. `cocotools_dev` is the one the docs
  assume.

All three extensions now appear under it.

### 4. Switch channels

Enable each extension from the **local** repository, and **disable** its copy
from the remote feed. Do not run both — they register the same keymaps twice
and keep separate preferences.

Only once the local copies are enabled and working, uninstall the feed copies.

### 5. Restore

- **CocoPies** preferences → **Load Preset**, pointing at the file from step 1.
- Copy `icons/custom/` back into
  `%USERPROFILE%\Documents\Claude\CocoTools\CocoPies\icons\custom\`. It is
  gitignored there, so it stays yours and never ships.
- **CocoDelete** — re-tick anything you had changed.

### 6. Check it took

- CocoPies: the pies are all back, in the right sections, with the right
  shortcuts; a shortcut actually fires the pie in the viewport; the icon picker
  shows your custom icons on the Custom tab.
- CocoDelete: `X` in mesh edit mode deletes without the confirmation menu.
- CocoSelections: the sidebar panel lists the sets saved in an existing
  `.blend`.

## Using it after that

```bash
cd "%USERPROFILE%\Documents\Claude\CocoTools"
git pull            # take whatever a session pushed
```

Then reload Blender — saving a file does nothing to a session that has already
imported the modules. The reload recipe is per-extension; for CocoPies see
[../CocoPies/docs/verify-and-deploy.md](../CocoPies/docs/verify-and-deploy.md).

Releasing is unchanged and still deliberate: bump that extension's
`blender_manifest.toml`, commit, then a tag (or a `workflow_dispatch` run)
builds and deploys the public feed.

## If it goes wrong

The feed installs are still there until step 4's uninstall, and the CocoPies
preset from step 1 restores the pies into whichever copy you end up using.
There is no state here that a preset and a re-clone cannot rebuild — except
`CocoPies/icons/custom/`, which is why it is backed up first.
