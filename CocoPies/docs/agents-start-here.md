# Start here

Orientation for an agent picking up CocoPies with no prior context. Read this
file, then the one that matches the job.

| You are about to… | Read |
|---|---|
| change code and prove it works | [verify-and-deploy.md](verify-and-deploy.md) |
| get a change onto GitHub or the Blender feed | [publishing.md](publishing.md) |
| touch the data model, keymaps or the preferences UI | [architecture-and-gotchas.md](architecture-and-gotchas.md) |
| find out what is unfinished | [open-work.md](open-work.md) |

`CLAUDE.md` is loaded into your context automatically and remains the
authority on conventions. These documents are procedures and traps, not a
second copy of it — where they overlap, `CLAUDE.md` wins.

## What CocoPies is

A Blender addon (Python, `bpy`) that lets the user build pie menus from the
addon's own Preferences panel. No build step, no linter, no test suite.
"Development" means editing Python under `CocoPies/`, then proving it
registers and behaves inside a real Blender.

It must work on **Blender 4.5 and 5.2** — both are LTS releases the user
actually runs. An API present in one and not the other is a real bug.

## There is one copy

A single CocoTools clone, registered in **both** Blender 4.5 and 5.2 as a
**Local extension repository** pointed at the clone's root (Preferences ▸ Get
Extensions ▸ repositories ▸ **+** ▸ Add Local Repository). Blender lists every
folder there holding a `blender_manifest.toml`, so `CocoPies/` *is* the live
install in both Blenders. Editing a file is editing the install — there is no
copy step and no deploy step.

CocoPies is an **extension** in both, so:

- module name is `bl_ext.<repo_module>.CocoPies` — read the exact value from
  `bpy.context.preferences.addons`, it depends on the name given to the local
  repo.
- there is no `bl_info` anywhere; the version lives only in
  `blender_manifest.toml`.
- `icons/custom/` sits at `CocoPies/icons/custom/`, gitignored — the user's own
  artwork, with no backup behind it.

Publishing is separate and unchanged: commit to `main` on
`github.com/MoonCoconutz/CocoTools`, then a tag or a `workflow_dispatch`
builds the feed. See [publishing.md](publishing.md).

### History, for reading old commits and docs

Until 2026-08-30 there were four copies: a standalone local repo, a legacy
4.5 add-on install, a separate 5.2 extension install, and CocoTools. They
drifted constantly and most mistakes in this project started with losing track
of which one was being edited. That setup is gone. If a doc or commit message
mentions "the two installs", "the local repo", or copying files across, it
predates this.

## Rules that are not negotiable

These each cost the project real damage at least once.

1. **Never delete `CocoPies/icons/custom/`.** It holds the user's own artwork,
   deliberately uncommitted, with no recycle bin behind it. The working tree
   is the live install now, so a careless clean here is a real loss.
2. **Never reload with `bpy.ops.preferences.addon_disable`.** It passes
   `default_set=True`, which drops the addon's whole `preferences.addons`
   entry — every stored pie with it — and re-registering then reseeds
   starters over the user's pies. Use the `addon_utils` form in
   [verify-and-deploy.md](verify-and-deploy.md).
3. **Never renumber an existing `KEYMAP_TYPE_ITEMS` entry.** Blender stores an
   `EnumProperty` as its integer, so those numbers are the on-disk format of
   every scope the user has ever set.
4. **Bump the version in the same session as the work.** Committing under an
   already-published version lets Blender's extension updater reinstall the
   older zip over the working copy. It has happened, twice, in one session —
   and now that the working copy *is* the install, that overwrite lands
   directly on the git working tree.

## Working with this user

He judges UI by exact visual detail, and he is right to — several "fixes" in
this project's history moved a bug rather than removing it. Two consequences:

- Do not guess at pixels. If a question is about how something *draws*, use
  the GUI screenshot harness in [verify-and-deploy.md](verify-and-deploy.md)
  and measure it. Four rounds of layout guessing were spent on a problem one
  screenshot settled.
- Ask before building anything structural, and ask with concrete options
  rather than an open question.
