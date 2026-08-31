# Publishing to CocoTools

CocoPies ships from the **CocoTools monorepo**, not from its own repository.

- Remote: `https://github.com/MoonCoconutz/CocoTools`, branch `main`.
- You are already working in a CocoTools clone, so publishing is an ordinary
  commit and push. No copying between repositories.
- `MoonCoconutz/CocoPies` (the old standalone repo) was **deleted on
  2026-08-31** — it 404s now. Nothing is lost with it: the subtree merge
  carried every pre-2026-08 commit into this repo, reachable from `main`.
  Don't go looking for it to read old history; it's already here.

CocoTools layout:

```
.github/workflows/publish-extensions.yml
CLAUDE.md                 <- shared conventions
README.md
CocoDelete/  CocoPies/  CocoSelections/
```

`CocoTools/CocoPies/` is flat: the package files directly, plus that
extension's own `CLAUDE.md`, `README.md` and `blender_manifest.toml`.

The user's clone of this repo is also his dev install — see
[agents-start-here.md](agents-start-here.md).

## Drift: closed

Until 2026-08-30 CocoPies lived in a standalone local repo *and* here, and the
two had drifted in both directions — `presets.py`, `utils.py`, `scripts/uv/`
and `README.md` were all ahead here, and a wholesale copy across would have
silently reverted published work (caught in review, one command short).

That is over: there is one working copy, this one. There is no other side to
diff against and nothing to copy. If an older doc or commit tells you to check
CocoTools against a local checkout before copying, it predates this.

## The version lives in one place

`CocoPies/blender_manifest.toml` → `version = "x.y.z"`. There is no `bl_info`
any more; the legacy 4.5 add-on install that needed one is gone.

Bump it in the same session as the work.

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

Since the working tree is now the live install, that overwrite would land on
your git checkout. Keeping the manifest version ahead of the feed's is what
prevents it.

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

## Recovering from the updater overwriting the working tree

Only possible if a *remote* repository is still subscribed alongside the local
one. The overwrite lands on the git checkout, so git is the recovery tool:
`git status` shows what was clobbered, `git checkout -- <paths>` restores it.

`icons/custom/` is the exception — it is gitignored, so git cannot bring it
back. That is the one thing to have a copy of elsewhere.

Then bump the manifest above the feed's version so it cannot happen again.
