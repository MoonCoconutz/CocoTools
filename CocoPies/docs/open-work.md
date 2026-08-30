# Open work

State as of **2026-08-30**. Check the facts before acting on them — this file
is a starting point, not an authority.

## 1. Finish the move to a single working copy

**Decided 2026-08-30:** the standalone local repo and both hand-managed
installs are retired in favour of one CocoTools clone registered as a Local
extension repository in 4.5 and 5.2. The docs already describe that state.

Still to do on the user's machine. The steps are written out in
[../../docs/dev-setup.md](../../docs/dev-setup.md) — it covers all three
extensions, since one local repository serves the whole monorepo. The clone
goes at `%USERPROFILE%\Documents\Claude\CocoTools`.

The part that matters for CocoPies: the module name changes, and
`AddonPreferences` is keyed by it, so **every stored pie orphans**. Save Preset
first, Load Preset after, and back up `icons/custom/` — it is gitignored and
has no other copy.

Until it is done, treat any file found in the old standalone repo as stale.

## 2. 1.10.2 is published but unverified

The image-icon picker cells were scaled (`IMAGE_CELL_SCALE = 1.5`, columns
16 → 11) and the manifest bumped to `1.10.2`. It is on `main` and on the feed.

**Never verified.** That session had no Blender, so neither the headless run nor
the screenshot harness was possible, and `1.5` is a guess rather than a
measurement. It went to the feed only because there was no dev channel to look
at it in — which is what item 1 fixes.

Once the dev channel exists: measure it with the real-window harness in
[verify-and-deploy.md](verify-and-deploy.md), adjust the constant, and publish
the corrected value.

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
