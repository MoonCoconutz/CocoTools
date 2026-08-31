# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CocoTools is a monorepo of Blender extensions by this user — one Blender
Extension per top-level folder, each with its own `blender_manifest.toml`,
built and published together by a single shared release pipeline. Extension-
specific development notes live in that extension's own `CLAUDE.md`
(`<Extension>/CLAUDE.md`); this file covers what's shared across all of them.

## Extensions in this repo

| Folder | What it is |
| --- | --- |
| `CocoPies/` | Build custom pie menus from Blender's own Preferences panel. See `CocoPies/CLAUDE.md`. |
| `CocoSelections/` | Named object selection sets, listed in the 3D viewport sidebar. See `CocoSelections/CLAUDE.md`. |

There is no build step, no linter, and no automated test suite for any of
them. "Development" means editing the Python under an extension's folder,
then verifying it registers cleanly and behaves correctly inside a real
Blender process.

## Target versions

**Must work on both Blender 4.5 and 5.2** (LTS releases the user actually
runs — installed under `C:\Program Files\Blender Foundation\`) unless an
extension's own `CLAUDE.md` says otherwise. An API that exists on one and
not the other is a real bug, not an edge case. Confirm any non-trivial `bpy`
API actually exists on both before relying on it — read
`bpy.types.X.bl_rna.functions[...]` / check via a headless run rather than
trusting memory of the API.

## Verifying a change

There's no Python on `PATH`; use Blender's own interpreter, headless:

```bash
"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" --background --python <script>
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <script>
```

Run against **both** versions before considering a change verified. Expect
noisy, unrelated `SystemError: GPU functions...` tracebacks from other addons
in the user's stack (they run headless-unfriendly code at import) — grep for
your own marker output rather than treating any traceback as failure.

Load an extension's package under a **unique module name** in the
verification script, not `import <Extension>` — that resolves to the
already-installed copy and double-registers every class, which surfaces as a
misleading `ValueError: already registered as a subclass`:

```python
import sys, importlib
for name in list(sys.modules):
    if name == "<Extension>" or name.startswith("<Extension>."):
        del sys.modules[name]
spec = importlib.util.spec_from_file_location(
    "<Extension>_verify", r"<repo>\<Extension>\__init__.py",
    submodule_search_locations=[r"<repo>\<Extension>"])
mod = importlib.util.module_from_spec(spec)
sys.modules["<Extension>_verify"] = mod
spec.loader.exec_module(mod)
mod.register()
# ... assertions ...
mod.unregister()
```

`context.preferences.addons["<Extension>_verify"]` will **not** exist under
this loading method — `context.preferences.addons[name]` is only populated
by Blender's real `addon_enable` machinery, not by calling `register()`
directly. For anything that needs real `AddonPreferences` data, either drive
it through a scratch `PointerProperty` on `bpy.types.Scene`, or verify live
against the actually-installed copy instead.

**`--factory-startup` does not fully disable an already-installed Extension**
the way it disables a legacy `scripts/addons` entry. If the extension under
test is *also* genuinely installed on this machine (check
`bpy.context.preferences.addons` without `--factory-startup` first), loading a
second copy via the unique-module-name pattern above can silently fail: the
real install claims the `bl_idname` at Blender's own startup before the
script's `register()` runs, `bpy.utils.register_class()` then raises no
exception but the class never reaches `bpy.types`, and
`bpy.ops.<category>.<name>.poll()` raises `AttributeError: ... could not be
found`. This is not a bug in the extension - was confirmed on the since-removed
`CocoDelete`, whose
real install worked correctly. For an extension already installed here, verify
against that real install instead: drop `--factory-startup` and check
`bpy.context.preferences.addons`, `<operator>.poll()`, and `<operator>()`
directly rather than loading a synthetic copy.

`Operator.__subclasses__()` under `--background` under-reports registered
operators; treat an empty result as inconclusive, not proof of absence.
Preview icons (`bpy.utils.previews`) need a GPU, so `icon_id` is `0` headless
— that's a false negative, not a real bug; check those in a live session.

**A real window can be driven from the command line, which beats guessing at
layout.** Anything about how something *draws* — a button's size, where an icon
lands inside it, whether two things line up — cannot be answered headlessly, and
does not have to be answered by asking the user for a screenshot either:

```bash
blender.exe --factory-startup --no-window-focus --window-geometry 40 40 1150 800 --python probe.py
```

`--factory-startup` keeps the user's other addons and preferences out of it
(their addons also crash headlessly on GPU calls), and `--no-window-focus`
stops the window stealing focus mid-work. In the script: set
`bpy.context.preferences.use_preferences_save = False` **first** so it can never
write preferences back, load the extension by path under a unique module name,
draw the real UI into an `invoke_props_dialog` from a `bpy.app.timers` callback,
`bpy.ops.screen.screenshot(filepath=...)` a second later, then
`bpy.ops.wm.quit_blender()`. The screenshot includes popups. Shipped `draw_*`
methods can be called directly with a `types.SimpleNamespace` standing in for
`self`, so this tests the real code rather than a copy of it.

Do **not** try to force a draw with `bpy.ops.wm.call_menu` under
`--background`: it crashes Blender with an access violation.

**To exercise an extension's manifest-reading path** (any code calling
`addon_utils.module_bl_info()`), the verification module name above isn't
enough on its own — `addon_utils.module_bl_info()` only parses
`blender_manifest.toml` when the loaded module's name starts with `bl_ext.`
(confirmed by reading `addon_utils.py`'s
`module_bl_info`/`_bl_info_from_extension`); any other name just gets an
empty `bl_info` back, silently, with no error. Use a name like
`"bl_ext.dev_verify.<Extension>_verify"` instead of a bare
`"<Extension>_verify"` when a test needs the manifest to actually resolve —
`spec_from_file_location` doesn't care that the name isn't a real installed
path, only `module_bl_info`'s prefix check does.

## Dev install: a Local Repository pointed at this working directory

Setting this up from scratch is written out step by step in
[docs/dev-setup.md](docs/dev-setup.md), including what carries over and what
does not. The rest of this section is the reference.

Every extension here is developed through one **Local extension repository
that points directly at this git working directory** — added once via
Blender's own UI (Edit ▸ Preferences ▸ Get Extensions ▸ repositories
dropdown ▸ **+** ▸ Add Local Repository, directory set to this repo's root).
Blender scans that directory's immediate children for a `blender_manifest.toml`
and lists each as an installed extension pulled straight from the working
tree — editing a file *is* editing the live install, no copy step, no
separate installed folder to diverge from. Adding a new extension folder
here with its own manifest makes it show up in that same repository
automatically.

Each extension's module name is `bl_ext.<repo_module>.<id>` (e.g.
`bl_ext.cocotools_dev.CocoPies`), not a bare id — confirmed live: every
extension's `preferences.addons` key is `bl_ext.<repo_module>.<id>`. Find
the exact current value from `bpy.context.preferences.addons` rather than
assuming it — it depends on whatever name the local repo was given when it
was added. Reload/data-persistence caveats are per-extension — see that
extension's own `CLAUDE.md`.

## Publishing a release (GitHub Pages extension repository)

The Local Repository above is for day-to-day development only. Installing
or updating any extension here elsewhere (another machine, or someone else)
goes through a second, separate repository: a static Blender extensions
listing — **every extension in this repo, in one shared index** — published
to GitHub Pages at `https://mooncoconutz.github.io/CocoTools/`, built by
`.github/workflows/publish-extensions.yml`.

This only exists because the repo is public — Blender's remote-repository
mechanism is plain static-file hosting (confirmed from
`blender --command extension server-generate --help`: "can be used to host
packages which only requires static-file hosting"), and both GitHub Pages
and raw file access require a public repo (or a paid plan) to serve
unauthenticated.

**To cut a release:**
1. Bump `version` in `<Extension>/blender_manifest.toml`.
2. Commit that change.
3. Tag it `<Extension>-v<version>` (matching the folder name and manifest
   version exactly, e.g. `CocoPies-v1.9.1`), and push the tag:
   ```bash
   git tag CocoPies-v1.9.1
   git push origin CocoPies-v1.9.1
   ```
4. The workflow downloads a portable Blender, verifies the tag matches that
   extension's manifest version, then runs
   `blender --command extension build` against **every** top-level folder
   that has a `blender_manifest.toml` (not just the one that changed — the
   published index always reflects the current committed state of
   everything), then `--command extension server-generate` to produce one
   shared `index.json` + `index.html`, and deploys the result to Pages.
5. Can also be re-run without a new tag from the Actions tab
   (`workflow_dispatch`), e.g. to redeploy after only the workflow file
   itself changed, or after adding a brand-new extension folder.

**To install/update from it in Blender:** Edit ▸ Preferences ▸ Get
Extensions ▸ repositories ▸ **+** ▸ **Add Remote Repository**, URL
`https://mooncoconutz.github.io/CocoTools/index.json` — **must** end in
`index.json`, not just the bare directory. Learned the hard way (on the
predecessor single-extension repo this was split from): a bare directory URL
fails with `invalid manifest (Expecting value: line 1 column 1 (char 0))`,
because GitHub Pages serves `index.html` at a directory URL by default, and
Blender does not itself append `index.json` to a bare-directory remote_url
for a plain static host — it just fetches whatever URL it's given and
expects that response body to be the JSON listing. This is a genuinely
separate install from the Local Repository dev copy — same identity risk as
any other reinstall-at-a-new-location applies: back up via that extension's
own preset/export mechanism (if it has one) before switching.

**GitHub Pages environment note:** the auto-created `github-pages`
deployment environment defaults to restricting deploys to specific
branches, which silently rejects a tag-triggered deploy. A deployment
branch policy allowing the `*-v*` tag pattern needs to exist on this repo's
`github-pages` environment (`gh api --method POST
repos/MoonCoconutz/CocoTools/environments/github-pages/deployment-branch-policies
-f name='*-v*' -f type='tag'`) — already set up as of this repo's creation,
but worth knowing if a fresh repo/environment ever needs it redone.

## Adding a new extension to this repo

1. Create a new top-level folder named after the extension's `id`, with its
   own `blender_manifest.toml` (schema: `schema_version`, `id`, `name`,
   `version`, `tagline` **and every permission description ≤ 64 characters**
   — Blender's packager enforces this silently at build time, not caught by
   `addon_utils.module_bl_info()`, only by actually running
   `blender --command extension build`), `maintainer`, `type = "add-on"`,
   `blender_version_min`, `license`, `copyright`.
2. Give it its own `CLAUDE.md` for anything specific to that extension
   (architecture, gotchas, its own dev-install history) and its own
   `README.md` for user-facing docs.
3. It's picked up automatically by both the Local Repository (already
   scanning this whole directory) and the release workflow (already looping
   over every `*/blender_manifest.toml`) — no config changes needed
   elsewhere.
