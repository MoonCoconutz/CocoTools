import json
from datetime import datetime

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, PropertyGroup, UIList
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import addons_resolve, autosave, keymap_diff, prefs_io, themes_io, ui


FORMAT = "CocoBackup"
FORMAT_VERSION = 2


# ---------------------------------------------------------------------------
# Preferences (autosave options)

def _restart_autosave(_self, _context):
    autosave.restart_timer()


class COCOBACKUP_Preferences(AddonPreferences):
    bl_idname = __package__

    use_autosave: BoolProperty(
        name="Autosave Next to the File", default=False,
        description="Save a copy of the open .blend in its own folder every few minutes")
    autosave_interval: IntProperty(
        name="Every (minutes)", default=5, min=1, max=240, update=_restart_autosave,
        description="Minutes between autosaves. Only written if something changed")
    autosave_versions: IntProperty(
        name="Versions to Keep", default=3, min=1, max=50,
        description="How many autosaves to keep per file; older ones are deleted")

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "use_autosave")
        col = layout.column()
        col.active = self.use_autosave
        col.prop(self, "autosave_interval")
        col.prop(self, "autosave_versions")
        col.label(text="Files are named <file>_autosave_<date-time>.blend, in a Backup folder next to the file.")


# ---------------------------------------------------------------------------
# Export / import

def _section_props(cls):
    cls.__annotations__["use_keymaps"] = BoolProperty(
        name="Shortcuts", default=True,
        description="Shortcut changes against stock Blender and add-ons, keymap preferences included")
    cls.__annotations__["use_preferences"] = BoolProperty(
        name="Preferences", default=True,
        description="Interface, editing, input, navigation and keymap settings. "
                    "Machine-specific paths and system settings are left out")
    cls.__annotations__["use_themes"] = BoolProperty(
        name="Themes", default=True,
        description="Your theme presets and the theme in use")
    cls.__annotations__["use_addons"] = BoolProperty(
        name="Add-on Settings", default=True,
        description="The preferences of every add-on")
    return cls


def _draw_sections(self, layout):
    col = layout.column(heading="Include")
    col.prop(self, "use_keymaps")
    col.prop(self, "use_preferences")
    col.prop(self, "use_themes")
    col.prop(self, "use_addons")


@_section_props
class COCOBACKUP_OT_export(Operator, ExportHelper):
    """Save shortcuts, preferences, themes and add-on settings to a file for another machine"""
    bl_idname = "cocobackup.export_backup"
    bl_label = "Export CocoBackup"
    bl_options = {'INTERNAL'}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def invoke(self, context, event):
        self.filepath = f"CocoBackup-{datetime.now():%Y%m%d}.json"
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        _draw_sections(self, self.layout)

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "No file chosen")
            return {'CANCELLED'}
        data = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "blender": bpy.app.version_string,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        if self.use_keymaps:
            data["keymaps"] = keymap_diff.export_keymaps()
        if self.use_preferences:
            data["preferences"] = prefs_io.export_preferences()
        if self.use_themes:
            data["themes"] = themes_io.export_themes()
        if self.use_addons:
            data["addons"] = prefs_io.export_addons()

        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        self.report({'INFO'}, f"CocoBackup saved to {self.filepath}")
        return {'FINISHED'}


def _upgrade(data):
    """Format 1 kept the active theme as values inside preferences."""
    old = data.get("preferences", {}).pop("themes", None)
    if old and "themes" not in data:
        data["themes"] = {"presets": {}, "active": {"label": "theme", "values": old[0]}}
    return data


@_section_props
class COCOBACKUP_OT_import(Operator, ImportHelper):
    """Apply a CocoBackup file to this machine. Save Preferences afterwards to keep it"""
    bl_idname = "cocobackup.import_backup"
    bl_label = "Import CocoBackup"
    bl_options = {'INTERNAL'}

    use_reset_shortcuts: BoolProperty(
        name="Undo shortcut changes not in the backup", default=True,
        description="Put back to stock any shortcut changed on this machine that the backup "
                    "does not contain, so the shortcuts end up exactly as in the backup")

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def draw(self, context):
        _draw_sections(self, self.layout)
        sub = self.layout.column()
        sub.active = self.use_keymaps
        sub.prop(self, "use_reset_shortcuts")

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "No file chosen")
            return {'CANCELLED'}
        try:
            with open(self.filepath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Could not read the file: {e}")
            return {'CANCELLED'}
        if data.get("format") != FORMAT:
            self.report({'ERROR'}, "Not a CocoBackup file")
            return {'CANCELLED'}
        data = _upgrade(data)

        job = {
            "data": data,
            "use_keymaps": self.use_keymaps,
            "use_preferences": self.use_preferences,
            "use_themes": self.use_themes,
            "use_addons": self.use_addons,
            "use_reset_shortcuts": self.use_reset_shortcuts,
            "addon_lines": [],
            "theme_overwrite": set(),
            "missing": [],
            "themes": [],
            "runs": [],
            "auto_enabled": [],
        }
        # Add-ons the backup names that can be switched on or installed are set
        # up first, before anything else: their settings and shortcuts only
        # exist once they run. Done later, their tool shortcuts (Bool Tool's
        # Box Carve) read as Blender's own and the reset pass removed them.
        # The report lists them unticked; ticking one switches it off again.
        if (self.use_addons or self.use_keymaps) and "addons" in data:
            for m in addons_resolve.classify(list(data["addons"])):
                if m["state"] == "disabled":
                    error, verb = addons_resolve.enable(m["module"]), "ENABLED"
                elif m["state"] == "available":
                    error, verb = addons_resolve.install(m["repo_dir"], m["id"]), "INSTALLED"
                else:
                    continue
                job["addon_lines"].append(f"FAILED    {m['id']}: {error}" if error else f"{verb:<9} {m['id']}")
                if not error:
                    job["auto_enabled"].append(m["id"])
        _state["job"] = job
        _run_and_show(job)
        return {'FINISHED'}


# The report popup and its buttons need the parsed backup after the import
# operator has finished; an operator property cannot hold a Python dict.
_state = {}


# ---------------------------------------------------------------------------
# Applying, and the report the user reads afterwards

TITLES = ("Add-ons / Extensions", "Shortcuts", "Add-on shortcuts", "Preferences", "Themes")
PUT_BACK = "Changed here after the export, put back as in the backup"
FROM_BACKUP = "Applied from the backup"


def _run(job):
    """Apply the backup once. Returns (groups, summary) for what changed.

    Lines for things that were already as in the backup are never returned:
    on a machine that already matched, listing them buried the one answer
    that mattered under a page of text.
    """
    data = job["data"]
    groups = {}          # title -> [(subtitle or None, [lines])]
    summary = []

    if (job["use_addons"] or job["use_keymaps"]) and "addons" in data:
        job["missing"] = addons_resolve.classify(list(data["addons"]))

    # 1. Add-ons / extensions: what was enabled or installed, and settings.
    ext_parts = []
    if job["addon_lines"]:
        ext_parts.append((None, list(job["addon_lines"])))
        done = [line.split()[1] for line in job["addon_lines"] if not line.startswith("FAILED")]
        if done:
            summary.append("Add-ons set up: " + ", ".join(done))
    if job["use_addons"] and "addons" in data:
        r = prefs_io.import_addons(data["addons"])
        per_addon = {}
        for line in r["log"]:
            word, _sep, rest = line.partition(" ")
            addon_id, _dot, detail = rest.strip().partition(".")
            per_addon.setdefault(addon_id, []).append(f"{word:<9} {detail}")
        for addon_id in sorted(per_addon, key=str.lower):
            ext_parts.append((f"{addon_id} settings", per_addon[addon_id]))
        if per_addon:
            summary.append("Add-on settings restored: " + ", ".join(sorted(per_addon, key=str.lower)))
    if ext_parts:
        groups[TITLES[0]] = ext_parts

    # Preferences before shortcuts: settings (keymap preferences included) can
    # rebuild keymaps, and the shortcut diff must land last.
    if job["use_preferences"] and "preferences" in data:
        pref_lines = prefs_io.import_preferences(data["preferences"])["log"]
        if pref_lines:
            summary.append(f"Preferences changed: {len(pref_lines)}")
            groups[TITLES[3]] = [(None, pref_lines)]

    if job["use_themes"] and "themes" in data:
        # "Kept" is not a change; a differing theme stays on offer as a row.
        theme_lines = [line for line in themes_io.apply(data["themes"], job["theme_overwrite"])
                       if not line.startswith("KEPT")]
        job["themes"] = themes_io.classify(data["themes"])
        if theme_lines:
            counts = {}
            for line in theme_lines:
                word = line.split()[0].lower()
                counts[word] = counts.get(word, 0) + 1
            summary.append("Themes: " + ", ".join(f"{n} {w}" for w, n in counts.items()))
            groups[TITLES[4]] = [(None, theme_lines)]

    if job["use_keymaps"] and "keymaps" in data:
        r = keymap_diff.import_keymaps(data["keymaps"], reset_extra=job["use_reset_shortcuts"])
        blender_rows, addon_rows = [], {}
        for entry in r["entries"]:
            if entry["word"] == "ALREADY":
                continue
            if entry["owner"]:
                addon_rows.setdefault(entry["owner"], []).append(entry)
            else:
                blender_rows.append(entry)
        if blender_rows:
            summary.append(f"Shortcuts changed: {len(blender_rows)}")
            # Two different stories, kept apart so each row reads on its own.
            parts = []
            applied = [e for e in blender_rows if e["word"] != "RESET"]
            reset = [e for e in blender_rows if e["word"] == "RESET"]
            if applied:
                parts.append((FROM_BACKUP, applied))
            if reset:
                parts.append((PUT_BACK, reset))
            groups[TITLES[1]] = parts
        counted = {k: sum(1 for e in v if e["word"] != "SKIPPED") for k, v in addon_rows.items()}
        counted = {k: n for k, n in counted.items() if n}
        if counted:
            summary.append("Add-on shortcuts changed: " + ", ".join(
                f"{k} ({n})" for k, n in sorted(counted.items(), key=lambda kv: kv[0].lower())))
        if addon_rows:
            parts = []
            for owner, rows in sorted(addon_rows.items(), key=lambda kv: kv[0].lower()):
                for row in rows:
                    if row["word"] == "RESET":
                        row["event"] = "Put back: " + row["event"][0].lower() + row["event"][1:]
                parts.append((owner, rows))
            groups[TITLES[2]] = parts
        if r["skipped"]:
            summary.append(f"Shortcuts skipped: {len(r['skipped'])} (their add-on is not enabled here)")

    bpy.context.preferences.is_dirty = True
    return groups, summary


def _run_and_show(job):
    job["runs"].append(_run(job))
    job["addon_lines"] = []
    _build_report(job)
    bpy.ops.cocobackup.show_report('INVOKE_DEFAULT')


def _redraw(context):
    """The report window stays open when one of its buttons is clicked (5.2):
    opening it again stacked a second copy on top. Redrawing is enough."""
    for area in context.screen.areas:
        area.tag_redraw()


def _build_report(job):
    """One list, five categories: every run's changes plus the open decisions."""
    wm = bpy.context.window_manager
    summary = [line for _groups, lines in job["runs"] for line in lines]

    unavailable = [m["id"] for m in job["missing"] if m["state"] == "unavailable"]
    differing = [t for t in job["themes"] if t["state"] == "different"]
    if unavailable:
        summary.append("Add-ons missing here: " + ", ".join(unavailable))
    if differing:
        summary.append(f"Themes different from this machine: {len(differing)}  (tick to replace)")
    if not summary:
        summary = ["Nothing to change: this Blender already matches the backup."]
    wm.cocobackup_summary = "\n".join(summary)

    wm.cocobackup_report.clear()
    for title in TITLES:
        parts = []
        for groups, _lines in job["runs"]:
            parts.extend(groups.get(title, []))
        choices = []
        if title == TITLES[0]:
            if job["auto_enabled"]:
                choices.append(("Switched on from the backup: tick any you want off again", [
                    ("addon", a, "enabled", "", f"{a}: switched on", False)
                    for a in job["auto_enabled"]]))
            if unavailable:
                parts.append(("Not in any repository here, install by hand",
                              [f"NOT       {a}" for a in unavailable]))
        if title == TITLES[4] and differing:
            choices.append(("Different from this machine: tick to replace with the backup's", [
                ("theme", themes_io.ACTIVE if t["kind"] == "active" else t["name"], "different", "",
                 (f"Theme in use (backup: {t['name']})" if t["kind"] == "active"
                  else f"Preset {t['name']}"),
                 False)
                for t in differing]))
        if not parts and not choices:
            continue
        _report_add(wm, "HEADER", title)
        for subtitle, rows in choices:
            sub = _report_add(wm, "SUBHEADER", subtitle)
            sub.word = 'QUESTION'
            for kind, item_id, state, target, label, default in rows:
                row = _report_add(wm, "CHOICE", label)
                row.choice_kind, row.item, row.state, row.target = kind, item_id, state, target
                row.select = default
        for subtitle, lines in parts:
            if subtitle:
                sub = _report_add(wm, "SUBHEADER", subtitle)
                sub.word = {FROM_BACKUP: 'IMPORT', PUT_BACK: 'LOOP_BACK'}.get(
                    subtitle, 'INFO' if subtitle.startswith("Not in any") else 'PLUGIN')
            for line in lines:
                if isinstance(line, dict):
                    _report_add_shortcut(wm, line)
                else:
                    _report_add(wm, "LINE", line)
    wm.cocobackup_report_index = 0


def _ticked(context, kind):
    return [r.item for r in context.window_manager.cocobackup_report
            if r.kind == "CHOICE" and r.choice_kind == kind and r.select]


class COCOBACKUP_OT_disable_addons(Operator):
    """Switch off again the ticked add-ons the import switched on"""
    bl_idname = "cocobackup.disable_addons"
    bl_label = "Disable Selected Add-ons"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        job = _state.get("job")
        if job is None:
            return {'CANCELLED'}
        lines, off = [], []
        for addon_id in _ticked(context, "addon"):
            error = addons_resolve.disable(addon_id)
            lines.append(f"FAILED    {addon_id}: {error}" if error else f"DISABLED  {addon_id}")
            if not error:
                off.append(addon_id)
                job["auto_enabled"].remove(addon_id)
        # Its settings and shortcuts went with it: drop their rows.
        for groups, _summary in job["runs"]:
            for title in (TITLES[0], TITLES[2]):
                if title in groups:
                    groups[title] = [(s, l) for s, l in groups[title]
                                     if s not in off and s not in {f"{a} settings" for a in off}]
        job["runs"].append(({TITLES[0]: [(None, lines)]},
                            ["Add-ons switched off again: " + ", ".join(off)] if off else []))
        _build_report(job)
        _redraw(context)
        return {'FINISHED'}


class COCOBACKUP_OT_replace_themes(Operator):
    """Replace the ticked themes with the backup's"""
    bl_idname = "cocobackup.replace_themes"
    bl_label = "Replace Selected Themes"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        job = _state.get("job")
        if job is None:
            return {'CANCELLED'}
        themes = job["data"]["themes"]
        lines = [line for line in themes_io.apply(themes, set(_ticked(context, "theme")))
                 if not line.startswith("KEPT")]
        job["themes"] = themes_io.classify(themes)
        job["runs"].append(({TITLES[4]: [(None, lines)]} if lines else {}, []))
        _build_report(job)
        _redraw(context)
        return {'FINISHED'}


def _report_add(wm, kind, text):
    item = wm.cocobackup_report.add()
    item.kind = kind
    item.text = text
    return item


def _report_add_shortcut(wm, entry):
    item = _report_add(wm, "SHORTCUT", entry["word"])
    item.word = entry["word"]
    item.what = entry["what"] or entry["keymap"]
    item.keymap = entry["keymap"]
    item.event = entry["event"]
    item.before = entry["before"]
    item.after = entry["after"]
    item.undo = json.dumps(entry["undo"]) if entry["undo"] else ""
    item.reverted = bool(entry.get("reverted"))


class COCOBACKUP_ReportLine(PropertyGroup):
    text: StringProperty()
    kind: StringProperty()
    # Shortcut rows only: the parts shown in columns, and how to revert it.
    word: StringProperty()
    what: StringProperty()
    keymap: StringProperty()
    event: StringProperty()
    before: StringProperty()
    after: StringProperty()
    undo: StringProperty()
    select: BoolProperty(name="", description="Tick to act on this row")
    reverted: BoolProperty()
    # Decision rows only (kind CHOICE): an add-on to set up or a theme to replace.
    choice_kind: StringProperty()
    item: StringProperty()
    state: StringProperty()
    target: StringProperty()


_WORD_ICONS = {"DISABLED": 'CHECKBOX_DEHLT', "CHANGED": 'FILE_REFRESH', "ADDED": 'ADD', "REMOVED": 'REMOVE',
               "SKIPPED": 'CANCEL', "FAILED": 'ERROR', "REBUILT": 'FILE_REFRESH',
               "ENABLED": 'CHECKMARK', "INSTALLED": 'IMPORT', "NOT": 'INFO',
               "OVERWROTE": 'FILE_REFRESH', "RESET": 'LOOP_BACK', "APPLIED": 'CHECKMARK', "KEPT": 'LOCKED'}


class COCOBACKUP_UL_report(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_prop, _index):
        if item.kind == "HEADER":
            layout.label(text=item.text, icon='DISCLOSURE_TRI_DOWN')
            return
        if item.kind == "SUBHEADER":
            row = layout.row()
            row.separator(factor=2.0)
            row.label(text=item.text, icon=item.word or 'PLUGIN')
            return
        if item.kind == "SHORTCUT":
            self._draw_shortcut(layout, item)
            return
        if item.kind == "CHOICE":
            row = layout.row(align=True)
            row.separator(factor=4.0)
            row.prop(item, "select", text="")
            row.label(text=item.text, icon='PLUGIN' if item.choice_kind == "addon" else 'COLOR')
            return
        word, _sep, rest = item.text.partition(" ")
        rest = rest.strip()
        if word == "NOT":
            rest = f"{rest}: not enabled here"
        row = layout.row()
        row.separator(factor=4.0)
        row.label(text=rest or item.text, icon=_WORD_ICONS.get(word, 'DOT'))

    @staticmethod
    def _draw_shortcut(layout, item):
        # Columns: [x] icon | what it does | where | what happened | key before -> after
        row = layout.row(align=True)
        row.separator(factor=2.0)
        if item.undo and not item.reverted:
            row.prop(item, "select", text="")
        else:
            row.label(text="", icon='BLANK1')
        row.label(text="", icon='LOOP_BACK' if item.reverted else _WORD_ICONS.get(item.word, 'DOT'))
        split = row.split(factor=0.26)
        split.label(text=item.what)
        split = split.split(factor=0.30)
        dim = split.row()
        dim.active = False
        dim.label(text=item.keymap)
        split = split.split(factor=0.45)
        if item.reverted:
            split.active = False
            split.label(text="Reverted")
            split.label(text="as before the import")
            return
        split.label(text=item.event)
        if item.before and item.after and item.before != item.after:
            split.label(text=f"{item.before}  →  {item.after}")
        else:
            # Only switched on/off: the key itself did not move.
            split.label(text=item.before or item.after)


class COCOBACKUP_OT_show_report(Operator):
    """What the last CocoBackup import changed"""
    bl_idname = "cocobackup.show_report"
    bl_label = "CocoBackup"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        wide = len(context.window_manager.cocobackup_report) > 0
        return context.window_manager.invoke_popup(self, width=980 if wide else 380)

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        layout.label(text="CocoBackup import", icon='CHECKMARK')
        for line in wm.cocobackup_summary.splitlines():
            layout.label(text=line)
        if len(wm.cocobackup_report):
            layout.template_list("COCOBACKUP_UL_report", "", wm, "cocobackup_report",
                                 wm, "cocobackup_report_index",
                                 rows=min(18, len(wm.cocobackup_report)))
            for kind, text, op, icon in (
                    ("addon", "Tick add-ons to switch them off again.", "cocobackup.disable_addons", 'CHECKBOX_DEHLT'),
                    ("theme", "Tick themes to replace them with the backup's.", "cocobackup.replace_themes", 'COLOR')):
                choices = [i for i in wm.cocobackup_report if i.kind == "CHOICE" and i.choice_kind == kind]
                if choices:
                    row = layout.row()
                    row.label(text=text)
                    sub = row.row()
                    sub.enabled = any(i.select for i in choices)
                    sub.operator(op, icon=icon)
            revertable = [i for i in wm.cocobackup_report
                          if i.kind == "SHORTCUT" and i.undo and not i.reverted]
            if revertable:
                row = layout.row()
                row.label(text="Tick shortcuts to undo what the import did to them.")
                sub = row.row()
                sub.enabled = any(i.select for i in revertable)
                sub.operator("cocobackup.revert_selected", icon='LOOP_BACK')
        row = layout.row()
        row.label(text="Nothing is kept after a restart until preferences are saved.")
        row.operator("wm.save_userpref", text="Save Preferences", icon='PREFERENCES')

    def execute(self, _context):
        return {'FINISHED'}


def _mark_reverted(undo_json):
    """Remember a revert on the run's own entry: Apply Ticked rebuilds the list
    from the runs, and a reverted row must not come back looking unreverted."""
    job = _state.get("job")
    if not job:
        return
    for groups, _summary in job["runs"]:
        for parts in groups.values():
            for _subtitle, lines in parts:
                for line in lines:
                    if isinstance(line, dict) and line.get("undo") \
                            and json.dumps(line["undo"]) == undo_json:
                        line["reverted"] = True


class COCOBACKUP_OT_revert_selected(Operator):
    """Undo what the import did to the ticked shortcuts, and only those"""
    bl_idname = "cocobackup.revert_selected"
    bl_label = "Revert Selected Shortcuts"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        done, failed = 0, []
        for item in wm.cocobackup_report:
            if not (item.select and item.undo and not item.reverted):
                continue
            error = keymap_diff.apply_undo(json.loads(item.undo))
            item.select = False
            if error:
                failed.append(f"{item.what}: {error}")
                continue
            item.reverted = True
            done += 1
            _mark_reverted(item.undo)
        for line in failed:
            print(f"CocoBackup: could not revert {line}")
        self.report({'WARNING'} if failed else {'INFO'},
                    f"Reverted {done} shortcut(s)" + (f", {len(failed)} could not be" if failed else ""))
        _redraw(context)
        return {'FINISHED'}


def menu_export(self, _context):
    self.layout.operator(COCOBACKUP_OT_export.bl_idname, text="CocoBackup (.json)")


def menu_import(self, _context):
    self.layout.operator(COCOBACKUP_OT_import.bl_idname, text="CocoBackup (.json)")


classes = (COCOBACKUP_Preferences, COCOBACKUP_ReportLine,
           COCOBACKUP_UL_report, COCOBACKUP_OT_export, COCOBACKUP_OT_import,
           COCOBACKUP_OT_disable_addons, COCOBACKUP_OT_replace_themes, COCOBACKUP_OT_show_report,
           COCOBACKUP_OT_revert_selected)

_WM_PROPS = ("cocobackup_report", "cocobackup_report_index", "cocobackup_summary")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.cocobackup_report = CollectionProperty(type=COCOBACKUP_ReportLine, options={'SKIP_SAVE'})
    wm.cocobackup_report_index = IntProperty(options={'SKIP_SAVE'})
    wm.cocobackup_summary = StringProperty(options={'SKIP_SAVE'})
    bpy.types.TOPBAR_MT_file_export.append(menu_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    ui.register()
    autosave.register()


def unregister():
    autosave.unregister()
    ui.unregister()
    _state.clear()
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    for name in _WM_PROPS:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
