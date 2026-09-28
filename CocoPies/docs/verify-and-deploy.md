# Verifying a change, and getting it into Blender

Four tools, in increasing cost: a headless run, a real-window screenshot, an
old-against-new comparison in isolated profiles, and the user's own eyes. Use
the cheapest one that can actually answer the question — but know which
questions each one *cannot* answer.

CocoPies is **5.2+ only** since 1.13.0. Every command here runs Blender 5.2;
do not test on 4.5.

## 1. Headless — does it load and behave

There is no Python on `PATH`. Use Blender's own interpreter:

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python <script>
```

`--factory-startup` is worth adding: without it the user's own addons load and
throw unrelated `SystemError: GPU functions...` tracebacks (Zen UV, HardOps and
friends run headless-unfriendly code at import). Either way, grep for your own
marker output rather than treating any traceback as failure — print lines
prefixed `MARK` and `grep "^MARK"`.

Load the package under a **unique module name**, never `import CocoPies` — that
resolves to the installed copy and double-registers every class, surfacing as a
misleading `ValueError: already registered as a subclass`:

```python
import sys, importlib.util
for name in list(sys.modules):
    if name == "CocoPies" or name.startswith("CocoPies."):
        del sys.modules[name]
spec = importlib.util.spec_from_file_location(
    "CocoPies_verify", r"<repo>\CocoPies\__init__.py",
    submodule_search_locations=[r"<repo>\CocoPies"])
mod = importlib.util.module_from_spec(spec)
sys.modules["CocoPies_verify"] = mod
spec.loader.exec_module(mod)
mod.register()
# ... assertions ...
mod.unregister()
```

Submodules are then reachable as `sys.modules["CocoPies_verify.previews"]` and
so on, which is how you reach internals without importing them a second time.

### What headless cannot tell you

- `context.preferences.addons["CocoPies_verify"]` **will not exist** — only
  Blender's real `addon_enable` machinery populates that, not `register()`.
  For anything needing real `AddonPreferences` data, note that every consumer
  only touches `pie_menus`, `active_pie_index` and `seeded_starters`, so a
  scratch `bpy.types.Scene` carrying those three names can be passed straight
  into `sync_starter_pies()`, `pie_menu_groups()` and friends.
- `Operator.__subclasses__()` under-reports. An empty result is inconclusive,
  not proof of absence.
- Preview icons need a GPU, so `icon_id` is `0` and `icon_args()` falls back to
  `BLANK1`. That is a false negative. Since the brush icons became PNGs this
  covers them too — nothing icon-shaped can be checked headlessly any more.
- **Anything about layout.** Do not try to force a draw with
  `bpy.ops.wm.call_menu` under `--background`; it crashes Blender with an
  access violation.

## 2. A real window — how does it actually draw

Layout questions (a button's size, where an icon lands inside it, whether two
columns line up) can be answered without asking the user, by driving a
throwaway GUI Blender:

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --factory-startup --no-window-focus --window-geometry 40 40 1150 800 --python probe.py
```

`--factory-startup` keeps the user's addons and preferences out of it;
`--no-window-focus` stops the window stealing focus while the user is working.

In the script, in this order:

1. `bpy.context.preferences.use_preferences_save = False` — **first**, so the
   throwaway session can never write preferences back.
2. Load the addon by path under a unique module name (as above) and
   `register()`, so previews and icons load.
3. Register a small operator whose `invoke` calls
   `context.window_manager.invoke_props_dialog(self, width=...)` and whose
   `draw` renders what you want to look at.
4. `bpy.app.timers.register(open_it, first_interval=1.5)`, then
   `bpy.ops.screen.screenshot(filepath=...)` at 3.0s, then
   `bpy.ops.wm.quit_blender()` at 4.5s. The screenshot includes popups.

**Render the shipped code, not a copy of it.** `draw_*` methods take a
`types.SimpleNamespace` as `self`; bind the ones they call on each other with
`functools.partial`:

```python
fake = types.SimpleNamespace(active_pie_index=0)
fake.draw_item_header = functools.partial(cls.draw_item_header, fake)
fake.draw_single_item = functools.partial(cls.draw_single_item, fake)
fake.draw_pie_items = functools.partial(cls.draw_pie_items, fake)
```

The icon picker can be opened for real with
`bpy.ops.cocopie.select_icon('INVOKE_DEFAULT', pie_index=0, item_index=0, category='BRUSH')`.
It seeds its current choice from the item it was opened on, so with no real
preferences present, stub `tools.get_pie_item` **before** invoking — patching
`_pending_icon` afterwards is too late, since the dialog draws once at invoke
and then only on input.

### Measuring the screenshot

Pillow is installed, but in the user's site-packages, which Blender does not
add to `sys.path`:

```python
sys.path.append("%USERPROFILE%/AppData/Roaming/Python/Python311/site-packages")
```

Measure rather than eyeball when the answer is a number. The trick that works:
draw each case **twice** with identical layout — once with `depress=True` and a
`BLANK1` icon (a solid block of selection blue, so its bounding box is exactly
the button rect), once with `emboss='NONE'` and the real icon (artwork on plain
background, so its bounding box is exactly the drawn icon). Comparing the two
needs no colour guessing. Colour-clustering a single mixed image gives noisy,
misleading numbers — it did here, twice.

## 3. Old against new — did anything change that should not have

The strongest check, and the one to use for a refactor or anything touching
stored pies or keymaps. It is how 1.13.0 was verified.

1. Copy the committed `CocoPies/` (before your change) into one scratch folder
   and the working copy into another, each as `<folder>/CocoPies`.
2. Build one profile per copy, headless: an empty folder as
   `BLENDER_USER_RESOURCES`, `--factory-startup`, then
   `preferences.extensions.repos.new(name=..., module=..., custom_directory=<folder>, source='USER')`,
   `addon_utils.enable("bl_ext.<module>.CocoPies", default_set=True)`,
   `show_splash = False`, `save_userpref()`. The extension registers the real
   way, so `preferences.addons` exists, starters are seeded and keymaps are
   real. Keep a clean copy of each profile and restore it before every run —
   and make the run script refuse to start if the clean copy is missing: an
   empty `BLENDER_USER_RESOURCES` folder silently reads the user's own
   configuration instead.
3. Run the same GUI probe against both (`--enable-event-simulate
   --no-window-focus`, `use_preferences_save = False` first). Record every
   pie's fields and items, every `COCOPIE` item in `keyconfigs.addon` and
   `keyconfigs.user`, which menu classes exist, and the X delete bindings'
   `active`. Exercise the operators through `bpy.ops.cocopie.*`. Screenshot
   the Preferences panel by drawing it into an `invoke_props_dialog` —
   `type(prefs).draw(proxy, context)` with a proxy whose `layout` is the
   dialog's and whose other attributes fall through to the real prefs — and a
   real pie opened with `wm.call_menu_pie('INVOKE_DEFAULT', ...)`. Close each
   popup with a simulated `ESC`.
4. Compare. Bundled script paths contain the folder name, so normalise it
   first. Identical data and byte-identical screenshots (`md5sum`) are the bar;
   every difference should be one you meant.

To replay the user's real pies rather than the starters, read them off the
running Blender read-only into a preset-shaped JSON and apply it in both
profiles with `resolve_preset_conflict(mode='REPLACE')` after staging it in
`presets._pending_preset_data`.

To count rebuilds, wrap `keymaps.unregister_pie_menus` in the probe:
`register_pie_menus()` calls it through the module global on every rebuild.

## 4. The user's eyes

The Preferences window opens as a **second OS window** and cannot be
screenshotted by the tooling, and popups are transient. Never switch a
`VIEW_3D` area to `'PREFERENCES'` to work around this — it silently becomes
`'PROPERTIES'` instead and costs the user their viewport. Draw the real panel
into a dialog as in section 3, or ask the user for a screenshot.

## There is nothing to deploy

The working tree is the live dev install in Blender 5.2, via the Local
extension repository pointed at this clone's root. Saving a file is the deploy. See
[agents-start-here.md](agents-start-here.md).

What still has to happen every time:

- **Bump `blender_manifest.toml`** in the same session as the work — the only
  version there is. See [publishing.md](publishing.md) for why.
- **Reload the running Blender**, below. Saving a file changes nothing in a
  session that has already imported the modules.

## Reloading a running Blender

Saving a file does nothing on its own; Blender caches loaded modules, and
`importlib.reload()` does not reload a package's submodules.

```python
import addon_utils, sys
# Read the exact name from bpy.context.preferences.addons -- it depends on
# the clone folder name, not the repo label -- here bl_ext.CocoTools.CocoPies
name = "bl_ext.<repo_module>.CocoPies"
addon_utils.disable(name, default_set=False)
for n in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
    del sys.modules[n]
addon_utils.enable(name, default_set=False, persistent=True)
```

`default_set=False` is the whole point: it leaves `preferences.addons`
untouched so the stored pies survive. `bpy.ops.preferences.addon_disable` does
not, and the resulting "Blender corrupted my pies" symptom was misdiagnosed
across five sessions — it was CocoPies reseeding starters over them. Do not use
`bpy.ops.script.reload()` either; it reloads every other addon for nothing.

Restarting Blender is always a valid alternative, and is what to tell the user
when the console is more trouble than it is worth.
