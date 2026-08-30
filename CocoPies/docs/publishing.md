# Publishing to CocoTools

CocoPies ships from the **CocoTools monorepo**, not from its own repository.

- Remote: `https://github.com/MoonCoconutz/CocoTools`, branch `main`.
- The local repo's `origin` (`MoonCoconutz/CocoPies`) is **archived and
  read-only** — pushing to it fails with `403 ... This repository was archived`.
  The local remote named `cocotools` points at the right place, but the two
  histories are **unrelated** (no common ancestor), so `main` cannot be pushed
  across. Publishing means copying content into a CocoTools checkout and
  committing there.

CocoTools layout:

```
.github/workflows/publish-extensions.yml
CLAUDE.md                 <- shared conventions
README.md
CocoDelete/  CocoPies/  CocoSelections/
```

`CocoTools/CocoPies/` is flat: the package files directly, plus that
extension's own `CLAUDE.md`, `README.md` and `blender_manifest.toml`.

There is no permanent checkout. Clone one into a scratch directory when you
need it; do not rely on a path from a previous session's scratchpad.

## The rule: copy only what this session changed

**Never blanket-copy `CocoPies/*` over CocoTools.** The two have drifted in
*both* directions, and a wholesale copy silently reverts published work. This
was caught in review on 2026-08-30, one command short of deleting a shipped bug
fix.

Before copying any file, confirm CocoTools' version of it matches the local
commit your session started from:

```bash
git archive <local-pre-session-sha> | tar -x -C /tmp/base
diff -rq --strip-trailing-cr -x __pycache__ /tmp/CocoTools/CocoPies /tmp/base/CocoPies
```

Files that come back identical are safe to copy wholesale. Files that differ
hold something one side does not have — read the diff before deciding, and by
default leave CocoTools' version alone.

Note that CRLF/LF differences make almost everything *look* modified. Use
`--strip-trailing-cr` when diffing and `git diff --ignore-cr-at-eol` when
reviewing, or you will not see the real changes among the noise.

### Known drift, as of 2026-08-30

CocoTools is **ahead** of the local repo in all of these:

| File | What CocoTools has |
|---|---|
| `presets.py` | `_repoint_missing_bundled_script()` — repoints starter-pie `execute_script()` paths when the addon folder has moved. 34 lines, published, absent locally. |
| `utils.py` | Differs; not yet analysed. |
| `__init__.py` | **No `bl_info`.** CocoPies is an extension there, and Blender strips a `bl_info` and warns. The local copy still has one. |
| `scripts/uv/` | An entire folder absent locally. |
| `README.md` | Differs; not yet analysed. |
| `CLAUDE.md` | CocoTools has **two** — a root one for shared conventions and `CocoPies/CLAUDE.md` for extension-specific notes, which explicitly defers to the root. The local root `CLAUDE.md` is the older monolithic version and maps cleanly onto neither. |

Two files that must therefore **never** be copied across: `__init__.py` and
`CLAUDE.md`. For docs, put a change in whichever of the two `CLAUDE.md` files
owns that topic — shared verification and release material in the root one,
architecture and UI gotchas in `CocoPies/CLAUDE.md`.

See [open-work.md](open-work.md); closing this drift is an outstanding task.

## Versions live in two places

| Where | Field |
|---|---|
| local repo | `CocoPies/__init__.py` → `bl_info["version"]` tuple |
| CocoTools | `CocoPies/blender_manifest.toml` → `version = "x.y.z"` |

Bump both, in the same session as the work.

**Why this matters more than it looks.** The publish workflow refuses to build
if a tag's version does not match the manifest — but nothing stops you
*committing* under an already-published version, and that is the dangerous
case. On 2026-08-30 a session's work was committed under the published
`1.9.1`; Blender therefore saw no update available, and running the extension
updater **reinstalled the older zip over the working copy**, twice, wiping
`icons/brushes/`, new operators and new starters until the addon would not load
at all.

- Pie data lives in `userpref.blend`, so stored pies survive that.
- `icons/custom/` does **not** — the updater replaces the whole folder. The
  manifest excludes it from the *build*, which stops it shipping but does not
  protect what is already on disk. Back it up before updating.
- While an older build is loaded it resolves stored scope integers against its
  own shorter enum. Reading is harmless; **saving preferences in that state
  writes the misreading back as real data.**

Bumping the installed copies past the feed's version is what keeps the updater
from reverting a hand-deploy.

## Releasing

Publishing is **one git tag**, not a manual build:

```bash
git tag CocoPies-v1.10.1 && git push origin CocoPies-v1.10.1
```

`.github/workflows/publish-extensions.yml` fires on any `*-v*` tag: it parses
the folder and version out of the tag name, **fails the build if the version
does not match that folder's manifest**, downloads a portable Blender, runs
`extension build` on *every* folder holding a manifest, regenerates
`index.json` with `server-generate`, and deploys to GitHub Pages. The feed
Blender subscribes to is `https://mooncoconutz.github.io/CocoTools/index.json`.

Two consequences:

- **Pushing to `main` publishes nothing.** Only a tag does.
- Every release rebuilds *all* extensions from current `main`, not only the
  tagged one — so `main` should be in a releasable state before tagging.

`workflow_dispatch` can rebuild without a tag from the Actions tab.

Tagging is a release to real users. Confirm with the user before pushing one,
even when the commit itself was authorised.

## Recovering an install the updater has reverted

Copy the source over the folder (never delete-then-copy), or better, build a
real package so the installed version is genuinely higher than the feed's:

```bash
blender --command extension build --source-dir <folder> --output-dir dist
```

then `bpy.ops.extensions.package_install_files(filepath=..., repo="mooncoconutz_github_io", enable_on_install=True)`.
That install keeps the addon's preferences entry intact, unlike
`bpy.ops.preferences.addon_disable`.
