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

## The four places CocoPies exists

This is the single most confusing thing about the project, and most mistakes
start with losing track of which copy is being edited.

| Copy | Path | What it is |
|---|---|---|
| **Local repo** | `%USERPROFILE%\Documents\Claude\CocoPies` | Where you edit. Git remote `cocotools`; `origin` is an **archived** repo that rejects pushes. |
| **4.5 install** | `%APPDATA%\Blender Foundation\Blender\4.5\scripts\addons\CocoPies\` | Legacy add-on. Version in `bl_info`. |
| **5.2 install** | `%APPDATA%\Blender Foundation\Blender\5.2\extensions\mooncoconutz_github_io\CocoPies\` | **Extension**, not an add-on. Version in `blender_manifest.toml`, and its `__init__.py` has no `bl_info`. |
| **CocoTools** | `github.com/MoonCoconutz/CocoTools`, folder `CocoPies/` | What ships. Unrelated git history to the local repo. |

Both installs must be updated on every deploy or the two Blenders silently
drift apart. Casing is exact.

## Rules that are not negotiable

These each cost the project real damage at least once.

1. **Never `rm -rf` an installed folder, even to redeploy.** `icons/custom/`
   inside it holds the user's own artwork, deliberately uncommitted. Copy
   over the folder; never delete-then-copy.
2. **Never reload with `bpy.ops.preferences.addon_disable`.** It passes
   `default_set=True`, which drops the addon's whole `preferences.addons`
   entry — every stored pie with it — and re-registering then reseeds
   starters over the user's pies. Use the `addon_utils` form in
   [verify-and-deploy.md](verify-and-deploy.md).
3. **Never blanket-copy the package into CocoTools.** The two have drifted in
   both directions; a wholesale copy silently reverts published fixes. See
   [publishing.md](publishing.md).
4. **Never renumber an existing `KEYMAP_TYPE_ITEMS` entry.** Blender stores an
   `EnumProperty` as its integer, so those numbers are the on-disk format of
   every scope the user has ever set.
5. **Bump the version in the same session as the work.** Committing under an
   already-published version lets Blender's extension updater reinstall the
   older zip over the working copy. It has happened, twice, in one session.

## Working with this user

He judges UI by exact visual detail, and he is right to — several "fixes" in
this project's history moved a bug rather than removing it. Two consequences:

- Do not guess at pixels. If a question is about how something *draws*, use
  the GUI screenshot harness in [verify-and-deploy.md](verify-and-deploy.md)
  and measure it. Four rounds of layout guessing were spent on a problem one
  screenshot settled.
- Ask before building anything structural, and ask with concrete options
  rather than an open question.
