# Verifying a change, and getting it into Blender

Three tools, in increasing cost: a headless run, a real-window screenshot, and
the user's own eyes. Use the cheapest one that can actually answer the
question — but know which questions each one *cannot* answer.

## 1. Headless — does it load and behave

There is no Python on `PATH`. Use Blender's own interpreter:

```bash
"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" --background --factory-startup --python <script>
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python <script>
```

Run **both** before calling anything verified.

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
"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" --factory-startup --no-window-focus --window-geometry 40 40 1150 800 --python probe.py
```

`--factory-startup` keeps the user's addons and preferences out of it;
`--no-window-focus` stops the window stealing focus while he is working.

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

## 3. The user's eyes

The Preferences window opens as a **second OS window** and cannot be
screenshotted by the tooling, and popups are transient. Never switch a
`VIEW_3D` area to `'PREFERENCES'` to work around this — it silently becomes
`'PROPERTIES'` instead and costs him his viewport. Ask for a screenshot, or
better, reproduce the same layout in the harness above.

## Deploying to the two installs

Copy files over the existing folders. **Never delete-then-copy** — `icons/custom/`
holds the user's own artwork with no recycle bin behind it.

```bash
A="$HOME/AppData/Roaming/Blender Foundation/Blender/4.5/scripts/addons/CocoPies"
B="$HOME/AppData/Roaming/Blender Foundation/Blender/5.2/extensions/mooncoconutz_github_io/CocoPies"
```

Copy only the files you changed, then confirm with `diff -q`. Two asymmetries
to respect:

- `__init__.py` — the 4.5 copy carries `bl_info`; the 5.2 copy must **not**
  (Blender strips it from an extension and prints a deprecation warning).
- Version — 4.5 reads `bl_info`, 5.2 reads `blender_manifest.toml`. Bump both,
  and see [publishing.md](publishing.md) for why leaving them at the published
  version is dangerous.

## Reloading a running Blender

Copying files alone does nothing; Blender caches loaded modules, and
`importlib.reload()` does not reload a package's submodules.

```python
import addon_utils, sys
name = "CocoPies"   # 5.2: "bl_ext.mooncoconutz_github_io.CocoPies"
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
