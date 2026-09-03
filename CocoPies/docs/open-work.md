# Open work

State as of **2026-09-03**. Check the facts before acting on them — this file
is a starting point, not an authority.

## 1. One pie left from the port

Fifteen pies were picked out of Blender's own **3D Viewport Pie Menus**
extension and rebuilt inside CocoPies. Fourteen are done. This one is not:

| Pie | Shortcut | Editor | What it needs |
| --- | --- | --- | --- |
| **Object Relationships** | `Ctrl+X` | Object Mode | Several custom operators, some of which open their own popups. |

**Read the source before porting.** It is still on disk at
`%APPDATA%\Blender Foundation\Blender.5\extensionslender_orgiewport_pie_menus\`,
and reading `pie_apply_transform.py` and `pie_mesh_flatten.py` rather than
inferring from a screenshot caught three real defects: Soft-Apply Constraints
is `visual_transform_apply` *only* and deliberately leaves constraints in
place; Make Single-User passes `obdata` alone; and Mesh Flatten's hotkey is
`Alt+X`, not the `Alt+R` an earlier version of this file claimed.

**"Needs custom operators" has meant "needs a bundled script" zero times so
far.** Apply Transforms' three turned out to be wrappers adding a tooltip and
a poll message around a built-in. Mesh Flatten's looked like they needed a
vertex loop, and the whole thing collapsed to one `transform.resize` with
`center_override` once the user pointed out that flatten *is* scale-to-zero
about a pivot. Reach for the built-in operator before writing a file;
`scripts/delete/MeshDeleteNoMenu.py` is the only case that has genuinely
earned one.

## 1b. A pie registered mid-session may not reach the dispatch keyconfig

**Believed fixed in 1.10.9; the original diagnosis was wrong.**

Symptom (2026-09-03): Mesh Flatten was invisible on `Alt+X` -- present in the
addon keyconfig, absent from `keyconfigs.user`, which is what Blender actually
dispatches from. Every other Mesh pie worked. A Blender restart fixed it.

The first diagnosis, written here confidently, was that writing `kmi.active`
to suppress a conflicting shortcut freezes that keymap against later merges.
**That does not reproduce.** With the default keyconfig and with MyPreset
active, with a victim suppressed, newly added addon keymap items merge every
time and the suppression survives. Do not repeat that theory without evidence.

What is actually established: `keymap_items.new()` populates only the *addon*
keyconfig, and Blender merges it into the user keyconfig on its own schedule.
Every headless test that saw the merge land had called
`wm.keyconfigs.update()` explicitly; `register_pie_menus` never did. It does
now, at the end, after its items exist.

Verified live by adding a throwaway pie to the Mesh keymap mid-session: it
reached the dispatch keyconfig immediately, no restart. That is consistent
with the fix, but it is **not proof** -- the original failure was never
reproduced on demand, so if a shortcut is ever silently dead again, start by
comparing `keyconfigs.addon` against `keyconfigs.user` rather than trusting
this section.

## 2. 1.10.1 was published without a tag

It reached the feed on 2026-08-30 via `workflow_dispatch`, not a tag, because
that session's git credentials rejected tag pushes with a 403. The workflow
rebuilds every extension from current `main` either way, so the feed was
correct — but **no `CocoPies-v1.10.1` tag exists**, so there is no release
marker in git for it.

Tag it retroactively if that matters:

```bash
git tag CocoPies-v1.10.1 07f5f13 && git push origin CocoPies-v1.10.1
```

## 3. The feed is offline while the repo is private

`MoonCoconutz/CocoTools` was made private on 2026-09-02. GitHub Pages does not
serve a private repo on a Free or Pro plan, so
`https://mooncoconutz.github.io/CocoTools/index.json` 404s and Blender's remote
repository cannot update from it. This is deliberate, not a fault.

Consequences worth knowing:

- Development is unaffected — the Local Repository reads this working tree, so
  every change is live without the feed.
- `CocoPies-v1.10.6` is tagged and pushed. Making the repo public again and
  re-running the workflow from the Actions tab (`workflow_dispatch`) publishes
  it; no re-tagging needed.
- Blender *does* support authenticated repositories (`use_access_token` /
  `access_token`, sent as `Authorization: Bearer`), but that cannot rescue a
  Pages URL that is not being served at all. A private feed would mean moving
  the index and the zips to `raw.githubusercontent.com` and giving every user a
  PAT — untested, and not worth it below a real audience. Sending a built zip
  is one command: `blender --command extension build --source-dir <ext>`.

## Recently closed, for context

- **1.10.8** (2026-09-03): Apply Transforms and Mesh Flatten ported; menus
  gained a List style (a flat dropdown instead of a pie), which is what let
  Apply Transforms reproduce the source's Clear Transforms submenu.
- **1.10.6** (2026-09-02): Quick Tap became a real `CLICK_DRAG`/`CLICK` pair
  instead of a hand-timed modal, and gained the ability to switch off a
  conflicting shortcut that would otherwise beat it. Three keymap findings from
  it are in `../CLAUDE.md`; the one most likely to be re-broken is that writing
  `kmi.active` during `register()` permanently stops Blender merging addon
  items into that keymap.
- The dev channel (item 1 of the old version of this file) is set up: one
  CocoTools clone registered as a Local extension repository, module name
  `bl_ext.CocoTools.CocoPies`.
- The unverified `IMAGE_CELL_SCALE = 1.5` from 1.10.2 was measured and found to
  do nothing — `template_icon` was the only call that actually resizes preview
  artwork, and the picker and pies were rebuilt around it.
- CocoDelete was retired into the two delete starter pies.
