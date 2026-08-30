# Open work

State as of **2026-08-30**. Check the facts before acting on them — this file
is a starting point, not an authority.

## 1. Finish the move to a single working copy

**Decided 2026-08-30:** the standalone local repo and both hand-managed
installs are retired in favour of one CocoTools clone registered as a Local
extension repository in 4.5 and 5.2. The docs already describe that state.

Still to do on the user's machine, in order:

1. **Save Preset** in each Blender, and copy `icons/custom/` somewhere safe.
   The module name changes from `CocoPies` to `bl_ext.<repo>.CocoPies`, and
   `AddonPreferences` is keyed by it, so **every stored pie orphans**.
2. Clone CocoTools; add it as a Local Repository in both Blenders.
3. Remove the old 4.5 legacy add-on and the old 5.2 extension install.
4. **Load Preset** in each; restore `icons/custom/` into
   `CocoPies/icons/custom/`.
5. Delete the old standalone repo once both Blenders are happy.

Until step 5 is done, treat any file found in the old repo as stale.

## 2. 1.10.2 is committed but unverified and unpublished

The image-icon picker cells were scaled (`IMAGE_CELL_SCALE = 1.5`, columns
16 → 11) and the manifest bumped to `1.10.2`, on branch
`claude/cocopies-addon-start-53ht5o`. **Not verified** — that session had no
Blender, so neither the headless run nor the screenshot harness was possible.
`1.5` is a guess.

Before this goes near `main`: measure it with the real-window harness in
[verify-and-deploy.md](verify-and-deploy.md) and adjust the constant.

## 3. 1.10.1 was published without a tag

It reached the feed on 2026-08-30 via `workflow_dispatch`, not a tag, because
that session's git credentials rejected tag pushes with a 403. The workflow
rebuilds every extension from current `main` either way, so the feed is
correct — but **no `CocoPies-v1.10.1` tag exists**, so there is no release
marker in git for it.

Tag it retroactively if that matters, from a session that can push tags:

```bash
git tag CocoPies-v1.10.1 07f5f13 && git push origin CocoPies-v1.10.1
```

## Recently closed, for context

- The four-copies setup was retired for a single CocoTools clone (item 1).
  With it, the local ↔ CocoTools drift and the hand-bumped install versions
  both stopped being things to track.
- Bigger brush icons in the picker were asked for and implemented — see item 2
  for the catch.
- Sculpt brush icons converted from `bpy.app.icons` triangle geometry to PNGs
  through the preview collection; the two workarounds built around the old
  behaviour (the Icon column's second wider width, and dropping the button
  frame for image icons) were removed with it.
- The Icon button is square again, via `scale_x` — `ui_units_x` never could
  size it.
- Icon picker: gaps between icons on the Custom and Brush tabs; built-in tabs
  deliberately untouched at the user's request.
