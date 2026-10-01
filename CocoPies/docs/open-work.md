# Open work

State as of **2026-09-28**. Check the facts before acting on them — this file
is a starting point, not an authority.

## 1. The port is finished

Fifteen pies were picked out of Blender's own **3D Viewport Pie Menus**
extension. Fourteen were rebuilt in CocoPies. The fifteenth, **Object
Relationships** (`X` in Object Mode and Outliner -- not `Ctrl+X`, as an earlier
version of this file claimed), was **dropped on 2026-09-03 at the user's
request**: it is largely Outliner inspection tooling, and the Outliner's own
Blender File and Orphan Data modes already cover most of it.

Do not "finish" it without asking. It is not pending work.

Worth keeping from the assessment, if it ever comes back: four of its eight
slots are cheap (`object.delete`, `outliner.orphans_purge`, and two short
scripts), but **List Datablock Users** and **List Dependencies** each need a
registered operator that draws its own `invoke_props_dialog` and re-invokes
itself to navigate deeper. CocoPies has no mechanism for that -- a slot runs a
command or a script, it cannot register an operator with a dialog. That would
be a new feature, not a pie.

## Two lessons the port paid for

**Read the source, do not infer it.** It is still on disk at
`%APPDATA%\Blender Foundation\Blender.5\extensionslender_orgiewport_pie_menus\`.
Reading it caught: Soft-Apply Constraints is `visual_transform_apply` *only*
and deliberately leaves constraints in place (the inferred version cleared
them -- destructive); Make Single-User passes `obdata` alone; Mesh Flatten is
on `Alt+X`; Object Relationships is on plain `X`. Three of those four were
already written down wrong.

**"Needs a custom operator" was true once in fifteen.** Apply Transforms' three
were wrappers adding a tooltip and a poll message around a built-in. Mesh
Flatten's collapsed to a single `transform.resize` with `center_override` once
the user pointed out that flatten *is* scale-to-zero about a pivot -- and the
script it replaced was subtly wrong, flattening along the object's local axis
instead of the global one. Reach for the built-in first.

Also: `hasattr(bpy.ops.object, "anything")` is **always True** -- `bpy.ops` is
lazy. It reported a non-existent operator as present during this port. Use
`bpy.ops.<mod>.<name>.get_rna_type()` and treat a raise as "does not exist".

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

## 3. The feed is live again

The repo was private from 2026-09-02, which took the Pages feed offline. It is
public again: on 2026-09-28 `https://mooncoconutz.github.io/CocoTools/index.json`
answered 200 and listed CocoPies 1.12.7. Should it go private again, Pages
stops serving and Blender's remote repository cannot update; development is
unaffected, since the Local Repository reads this working tree.

## 4. Pies made before 1.13.0 can carry the bugs it fixed

1.13.0 fixed how pies are *made*, not pies already stored:

- A pie made with **Add to a New Pie** before 1.13.0 is bound to Q in
  Window (Global). Clear its key or give it a real one.
- A **Duplicate** made before 1.13.0 is scoped to Window as well as its own
  editor, and lost its Trigger, Style and Quick Tap settings. Two duplicates
  of one pie share an idname, so only one of them registers.
- A fresh install's delete-starter suppressions were recorded with
  `restore_on_unregister = False`, so disabling CocoPies does not give
  Blender's X delete menu back. The user's own configuration had `True`
  (checked live 2026-09-28), so nothing was migrated.

## 5. Old "ghosted" shortcuts may have had one cause

Measured 2026-09-29 (see `../CLAUDE.md`, "Settle the keyconfig"): a user
keymap edit left pending while addon items are removed is paired with the
wrong items, removing a live addon item from `user` and keeping a removed one.
Up to 1.13.2 every rebuild did that in Mesh and Curve (the restore, then the
addon sweep). That may be where the ghosted Zen UV and Mesh Flatten bindings
and the register-time loss of Mesh/Curve addon items came from. **Not
verified** — nobody reproduced those from this cause. If a ghost turns up
again, check for a pending `user` write next to an addon keymap change first.

## Recently closed, for context

- **1.14.0** (2026-10-01): new preferences layout. The list has one toolbar
  (New, Duplicate, Delete, ▲▼ within the section, Presets menu) and
  split-based rows whose key caps line up. Settings are Menu, Quick Tap and
  Shortcut boxes, with an Editors checkbox popover and a modal key capture
  that shows modifiers live. Turning Quick Tap off restores the previous
  Trigger. Add/Remove Editor and the per-row buttons are gone. Checked
  old-against-new in isolated 5.2 profiles holding the user's 24 pies, also
  after an in-Blender update from 1.13.4 and a restart. Data and every
  keymap item matched, and a screenshot of an open pie was byte-identical.
  The only differences were the intended Quick Tap restore and the new
  Presets menu class.
- **1.13.4** (2026-09-30): a bin beside Restore Starter Pies deletes every pie
  after a confirmation, handing back the suppressed X delete menus; starters
  stay recorded, so they do not return at startup. Checked in an isolated
  5.2 profile: 24 pies to 0, no CocoPies keymap item left, X menus on, then
  Restore Starter Pies brought back 24 pies and both suppressions.
- **1.13.3** (2026-09-29): suppressions are written into `keyconfigs.user`
  only and restored only on a real unregister, not on every rebuild; the
  Delete-key menu no longer vanishes after an edit made while CocoPies
  rebuilt (CocoBackup's import did that). A stock → MyPreset switch puts back
  the Delete menu Blender's re-apply took, and an in-session update from an
  older version re-reads the preset first. The first start also puts back,
  once, a Delete menu an older version already deleted (the user's Curve one
  was). Checked old against new in isolated profiles, stock and MyPreset, and
  on a copy of the user's own saved preferences.
- **1.13.0** (2026-09-28): 5.2+ only, and a clean-up checked old against new
  in isolated profiles (identical pies, keymaps and screenshots, the user's
  real pies included). Fixed: Add Editor raised on every click; moving a pie
  left its shortcut drawing the neighbour's menu and its tap running the
  neighbour's direction; Duplicate, Add to a New Pie and the fresh-install
  suppression flag above; a preset import rebuilt 415 times (now once). The
  retired `cocopie.hold_or_tap` and the unused `cocopie.test_pie_menu`
  operators were removed. New starter defaults for UV Transform and UV Select.
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
