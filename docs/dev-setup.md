# Setting up the dev channel

One-time setup, on the user's Windows machine, covering **every extension in
this repo**. The result: a git clone that *is* the live install, so editing a
file and reloading is the whole loop — nothing built, nothing uploaded,
nothing public.

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
`blender_manifest.toml`, so **CocoPies and CocoSelections both appear at
once** from the one directory. A new extension folder added later shows up on
its own.

## The one thing that can go wrong

Blender keys an addon's saved preferences by its **module name**. Installed
from the feed that is `bl_ext.mooncoconutz_github_io.<Extension>`; from a
local repository it is `bl_ext.<repo module>.<Extension>`. Different name, so
Blender sees a fresh install with empty preferences.

**The repo module is the clone folder's name, not the label you type when
adding the repository.** The local repo here is *named* `cocotools_dev`, but
its module is `CocoTools` — taken from the directory — so the real names are
`bl_ext.CocoTools.CocoPies` and `bl_ext.CocoTools.CocoSelections`. The docs
said `bl_ext.cocotools_dev.CocoPies` for a while, which is a module that does
not exist — a reload snippet copied from one failed outright. Read the actual
value out of `bpy.context.preferences.addons` rather than typing either.

What the name change costs, per extension:

| Extension | Where its data lives | Effect |
|---|---|---|
| **CocoPies** | `AddonPreferences` — every pie menu | **All pies appear gone**, and starter pies get seeded into the blank. Back up first. |
| **CocoSelections** | the Scene, saved in each `.blend` | Unaffected. Nothing to do. |

Nothing is corrupted and the old entry is not deleted — the data just does not
carry over on its own. Step 1 is what makes this a non-event.

## Steps

Done in Blender 5.2, which is where the extensions were installed. 4.5 has a
separate preferences store and had no CocoPies install at all; setting it up
there is the same six steps against that Blender.

### 1. Back up — do not skip

- **CocoPies** preferences → **Save Preset**. This writes every pie menu to a
  JSON file. Put it somewhere outside the addon folder.
- Copy **`CocoPies/icons/custom/`** out of the installed folder, *if it
  exists*. It holds your own artwork, is deliberately not in git, and has no
  backup behind it. As of 2026-08-31 there is no such folder — only
  `icons/brushes/` and the slot arrows, both of which are in git — so this
  step is usually a no-op. Find the installed path in Preferences → Add-ons →
  CocoPies (expand the entry).
- **CocoSelections** — nothing; its data is in your `.blend` files.

### 2. Clone the repo

```bash
git clone https://github.com/MoonCoconutz/CocoTools "%USERPROFILE%\Documents\Claude\CocoTools"
```

A fresh clone has no git identity, and git refuses to commit without one. Set
it before the first commit, or it fails with `Author identity unknown`:

```bash
git config --global user.name "MoonCoconutz"
git config --global user.email "222581614+MoonCoconutz@users.noreply.github.com"
```

The noreply address is deliberate. Committing under a real address publishes
it in every commit's metadata, and rewriting history afterwards does not fully
remove it — GitHub keeps the old objects reachable by SHA until Support
garbage-collects them. GitHub's *Keep my email addresses private* and *Block
command line pushes that expose my email* (both at
<https://github.com/settings/emails>) stop it recurring.

### 3. Add it as a Local Repository

Preferences → Get Extensions → the repositories dropdown (top right) → **+** →
**Add Local Repository**:

- Directory: `%USERPROFILE%\Documents\Claude\CocoTools`
- The name is only a label in the UI. The module name comes from the folder
  (see above), so renaming the *folder* is what orphans preferences, not
  renaming the repository entry.

Both extensions now appear under it. A local repository creates nothing under
`AppData` — it reads the clone in place — so its absence there is not evidence
the repository is missing.

### 4. Switch channels

Enable each extension from the **local** repository, and **disable** its copy
from the remote feed. Do not run both — they register the same keymaps twice
and keep separate preferences.

Only once the local copies are enabled and working, uninstall the feed copies.

### 5. Restore

- **CocoPies** preferences → **Load Preset**, pointing at the file from step 1.
- Copy `icons/custom/` back into
  `%USERPROFILE%\Documents\Claude\CocoTools\CocoPies\icons\custom\`, if you had
  one. It is gitignored there, so it stays yours and never ships.

### 6. Check it took

- CocoPies: the pies are all back, in the right sections, with the right
  shortcuts; a shortcut actually fires the pie in the viewport; the icon picker
  shows your custom icons on the Custom tab.
- **X in mesh edit**: a tap deletes without the confirmation menu, holding it
  opens the Mesh Delete pie. Same in curve edit. This is Quick Tap on the two
  delete starter pies — see the next section if it does not behave.
- CocoSelections: the sidebar panel lists the sets saved in an existing
  `.blend`.

## Preferences do not save themselves

**Auto-Save Preferences is off on this machine.** Anything living in
preferences — pie menus, keymap edits, addon settings — exists only in the
running session until **File ▸ Defaults ▸ Save Preferences**.

This bites in a way that looks like a bug rather than a missing save. Remove a
keymap item, and Blender will happily restore it from the last saved
preferences the next time the keyconfig is rebuilt, silently undoing the
removal. Save *while the change is in place*, not afterwards, or the save
writes back the state you were trying to get rid of.

## X is spoken for, and other addons may want it

The **Mesh Delete** and **Curve Delete** starter pies bind `X` through
`cocopie.hold_or_tap`: tap runs a command, hold opens the pie. That is one key
serving both jobs, which is why CocoDelete — a separate extension that bound
`X` directly — was retired into these pies in 1.10.5. Two extensions binding
one key cannot negotiate: Blender takes the first match in the keymap, and
which one that is depends on registration order.

If `X` misbehaves, list what is actually bound rather than guessing:

```python
for km in bpy.context.window_manager.keyconfigs.user.keymaps:
    if km.name in ("Mesh", "Curve"):
        for i, kmi in enumerate(km.keymap_items):
            if kmi.type == 'X' and not (kmi.ctrl or kmi.alt or kmi.shift):
                print(km.name, i, kmi.idname)
```

`cocopie.hold_or_tap` must come **first**. Anything above it wins instead.

**Orphaned keymap items are the usual culprit.** An addon that removes only
what a module-level Python list remembers leaves real items behind, because
that list is empty again after every reload while the items are not —
`keymap_items.new()` appends and never replaces, so they accumulate and keep
firing. CocoPies sweeps by content for exactly this reason. Others do not: a
retired pie addon left fourteen dead bindings here, one of them on plain `X`.
Sweep by content, and save preferences in the same breath:

```python
for kc in (wm.keyconfigs.user, wm.keyconfigs.addon):
    for km in kc.keymaps:
        for kmi in list(km.keymap_items):
            if <matches what you are removing>:
                km.keymap_items.remove(kmi)
bpy.ops.wm.save_userpref()
```

Keymap *presets* are a separate source again. A binding written into the
active preset (`scripts/presets/keyconfig/*.py`) comes back every time that
preset loads, so it has to be removed from the `.py`, not from the keymap.

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
builds and deploys the public feed. **Bump before committing, never after
publishing** — committing under a version already on the feed means Blender
sees no update, and the updater will reinstall the older zip over the working
tree.

## If it goes wrong

The feed installs are still there until step 4's uninstall, and the CocoPies
preset from step 1 restores the pies into whichever copy you end up using.
There is no state here that a preset and a re-clone cannot rebuild — except
`CocoPies/icons/custom/`, which is why it is backed up first.
