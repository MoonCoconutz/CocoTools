# Open work

State as of **2026-09-03**. Check the facts before acting on them — this file
is a starting point, not an authority.

## 1. Three pies left from the port

Fifteen pies were picked out of Blender's own **3D Viewport Pie Menus**
extension and rebuilt inside CocoPies. Twelve are done and in the shipped
starters. These three are not:

| Pie | Shortcut | Editor | What it needs |
| --- | --- | --- | --- |
| **Apply Transforms** | `Ctrl+A` | Object Mode | Loc/Rot/Scale slots are stock `object.transform_apply`. Three convenience slots — apply-constraints, make-single-user, clear-all — are short wrappers around built-ins. |
| **Mesh Flatten** | `Alt+R` | Mesh Edit | Three genuinely custom operators (`flatten_to_x/y/z`). Blender has no equivalent. |
| **Object Relationships** | `Ctrl+X` | Object Mode | Messiest. Several custom operators, some of which open their own popups. |

**The port-vs-call decision is closed: port.** It was open for a while —
whether to reimplement the source addon's operators or just call them and leave
that extension installed. Calling is no longer possible: as of 2026-09-03 the
only pie-related addon enabled on this machine is CocoPies itself, and
`bpy.ops.transform.flatten_to_x` does not exist. The keymap leftovers from that
extension were swept in the same session.

Porting does not automatically mean a bundled script. Per the repo's own rule
those are a last resort, and most of these "custom operators" are one to three
built-in calls that fit in a slot command directly — `exec()` runs the command
string, so several statements separated by newlines are fine.
`scripts/delete/MeshDeleteNoMenu.py` is the precedent for the cases that really
do need a file: branching on select mode, or anything needing a mode guard.

Suggested order: **Apply Transforms** first (most slots need no new code at
all), then Mesh Flatten, then Object Relationships.

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
