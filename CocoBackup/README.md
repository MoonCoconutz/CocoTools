# CocoBackup

Move your Blender setup to another machine in one file: your **shortcuts**,
your **preferences** and your **add-on settings**.

## Why not a keymap preset?

A keymap preset copies whole keymaps, add-on shortcuts included. Import it on
another machine and every add-on shortcut you touched shows up **twice**: the
add-on registers its own, and the preset brings a copy. Switching an add-on
shortcut off inside a preset does not even work, because the add-on's own copy
stays on.

CocoBackup stores only **what you changed** compared to stock Blender and your
add-ons: "this shortcut, moved to Alt+F", "this one, switched off", "this one,
added". On import it finds the same shortcut on the new machine and edits it,
so nothing gets duplicated, and your changes to add-on shortcuts travel too.

## Use

- The **coconut button** in the 3D Viewport header, after the View / Select /
  Add / Object menus, opens both, plus the autosave options. Its colour tells
  you about the open file: **red** means it was never saved anywhere, **green**
  means it is saved, **plain** means it is saved but you changed something
  since.
- **File ▸ Export ▸ CocoBackup (.json)** saves the backup.
- **File ▸ Import ▸ CocoBackup (.json)** applies it. A popup then lists
  exactly what changed: which preference went from what to what, and which
  shortcuts were changed, removed, added or skipped. If this Blender already
  matched the backup, it just says so.
- Then **Save Preferences** (there is a button at the bottom of the popup), or
  the changes last only until Blender closes.
- In the popup, tick shortcuts and press **Revert Selected Shortcuts** to undo
  just those.

Both sides let you choose what to include: **Keymaps**, **Preferences**,
**Add-on Settings**.

Importing the same file twice changes nothing the second time.

Shortcuts end up **exactly** as in the backup: a shortcut you changed after
exporting is put back to stock, and listed. Untick **Undo shortcut changes not
in the backup** in the import dialog to keep this machine's own changes and
only add the backup's.

## What is included

| Section | Included | Left out |
| --- | --- | --- |
| Keymaps | Every shortcut you moved, switched off, removed or added. The keymap settings too (select with left/right, Spacebar action) | Switched-off copies a keymap preset carried, since they do nothing |
| Preferences | Interface, Editing, Input, Navigation, Keymap, File Paths options | Every file and folder path, System (GPU, memory), Extensions repositories, Asset Libraries, Experimental: these belong to the machine |
| Themes | Your theme presets and the theme in use. Missing presets are installed; different ones are only replaced if you tick them | Nothing |
| Add-on Settings | The preferences of every enabled add-on, CocoPies menus included | Nothing |

## Autosave to a Backup folder

Optional (off by default): every N minutes, if something changed since the
last save or autosave, a copy is saved in a `Backup` folder next to the file
(created the first time) as `<name>_autosave_26-09-2026_18.25.blend`, keeping
only the newest few. If nothing changed, nothing is written. Set it in the
coconut panel or in the add-on's preferences. The open file itself is not
touched. A file that was never saved is skipped.

## Good to know

- **Add-ons the backup uses but this machine is not running** are switched on
  first: one installed but switched off is enabled, one listed in an online
  repository you added (extensions.blender.org included) is installed. The
  popup lists them; tick any you do not want and press **Disable Selected
  Add-ons**. Bought or hand-installed add-ons have to be installed by hand;
  until then their settings and shortcuts are skipped, not half-applied.
- **Themes that differ** from this machine's are listed unticked; tick them
  and press **Replace Selected Themes** to take the backup's.
- A shortcut is found on the new machine by its command and its original key.
  Across Blender versions some commands change their options; CocoBackup then
  falls back to "same command on the same key", but only when that is
  unambiguous. Anything it cannot place is listed as skipped.
- Some add-ons read their settings only at startup. If one does not look right
  after importing, Save Preferences and restart Blender.
