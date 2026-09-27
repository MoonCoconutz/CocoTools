"""Checker Map: Alt+T (or the checker button) swaps the target objects'
materials for a checker material, and swaps back.

The originals are stored on each object as an ID property
(ORIG_KEY: [[slot link, material name], ...] plus how many slots were added),
so they survive saving the file with the checker on. While it is on, Solid
viewports showing Material colour switch to Texture colour, and UV Editors
show the checker image; both are put back when it goes off.
"""

import json
import os

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from . import common

MATERIAL = "CocoUVs Checker"
IMAGE = "CocoUVs Checker"
ORIG_KEY = "cocouvs_checker_orig"
SIZES = (256, 512, 1024, 2048, 4096, 8192)

_addon_keymaps = []
_view_state = {}   # space pointer -> what to restore


def _map_items(self, context):
    items = [
        ('UV_GRID', "UV Grid", "Blender's black-and-white UV grid", 'TEXTURE', 0),
        ('COLOR_GRID', "Color Grid", "Blender's labelled colour grid", 'COLOR', 1),
    ]
    imported = [img for img in bpy.data.images if img.get("cocouvs_checker_import")]
    for n, img in enumerate(imported):
        items.append((f"IMG:{img.name}", img.name, "Imported checker map", 'IMAGE_DATA', 10 + n))
    # Blender keeps a reference to dynamic enum strings.
    _map_items.cache = items
    return items


def _settings_changed(self, context):
    if is_on():
        _update_image(context.scene)


def is_on():
    return any(ORIG_KEY in obj for obj in bpy.data.objects)


def _update_image(scene):
    """The image the checker material shows, for the current settings."""
    settings = scene.cocouvs
    choice = settings.checker_map
    if choice.startswith("IMG:"):
        img = bpy.data.images.get(choice[4:])
        if img is not None:
            _material().node_tree.nodes["Checker"].image = img
            return img
        choice = 'UV_GRID'
    size = int(settings.checker_size)
    img = bpy.data.images.get(IMAGE)
    if img is None:
        img = bpy.data.images.new(IMAGE, size, size)
    if tuple(img.size) != (size, size) or img.generated_type != choice or img.source != 'GENERATED':
        img.source = 'GENERATED'
        img.generated_width = img.generated_height = size
        img.generated_type = choice
    _material().node_tree.nodes["Checker"].image = img
    return img


def _material():
    mat = bpy.data.materials.get(MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL)
        mat.use_nodes = True
    tree = mat.node_tree
    tex = tree.nodes.get("Checker")
    if tex is None:
        tex = tree.nodes.new("ShaderNodeTexImage")
        tex.name = "Checker"
        tex.location = (-350, 300)
        bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
        tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    # Solid mode's Texture colour shows the active image node.
    tree.nodes.active = tex
    return mat


def _apply(obj, mat):
    if ORIG_KEY in obj:
        return
    slots = obj.material_slots
    obj[ORIG_KEY] = json.dumps({
        "slots": [[s.link, s.material.name if s.material else ""] for s in slots],
        "added": 0 if len(slots) else 1,
    })
    if not len(slots):
        obj.data.materials.append(None)
    for slot in obj.material_slots:
        slot.material = mat


def _restore(obj):
    raw = obj.get(ORIG_KEY)
    if raw is None:
        return
    data = json.loads(raw)
    stored = data["slots"]
    for slot, (link, name) in zip(obj.material_slots, stored):
        slot.link = link
        slot.material = bpy.data.materials.get(name) if name else None
    if data["added"]:
        # A slot is only ever added to an object that had none. clear(), not
        # pop(): pop() leaves the object's slot count stale (5.2), showing an
        # empty slot in the Material tab.
        obj.data.materials.clear()
    del obj[ORIG_KEY]


def _set_views(on, image=None):
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            space = area.spaces.active
            key = space.as_pointer()
            if area.type == 'VIEW_3D':
                shading = space.shading
                if on and shading.type == 'SOLID' and shading.color_type != 'TEXTURE':
                    _view_state[key] = ("color_type", shading.color_type)
                    shading.color_type = 'TEXTURE'
                elif not on and key in _view_state:
                    shading.color_type = _view_state.pop(key)[1]
            elif area.type == 'IMAGE_EDITOR' and space.mode == 'UV':
                if on:
                    _view_state.setdefault(key, ("image", space.image.name if space.image else ""))
                    space.image = image
                elif key in _view_state:
                    name = _view_state.pop(key)[1]
                    space.image = bpy.data.images.get(name) if name else None
            area.tag_redraw()


def turn_on(context):
    image = _update_image(context.scene)
    mat = _material()
    objects = common.target_objects(context)
    for obj in objects:
        _apply(obj, mat)
    _set_views(True, image)
    return len(objects)


def turn_off():
    for obj in bpy.data.objects:
        _restore(obj)
    _set_views(False)


class COCOUVS_OT_checker_toggle(Operator):
    bl_idname = "cocouvs.checker_toggle"
    bl_label = "Toggle Checker Map"
    bl_description = ("Show a checker map on the selected objects (Alt+T); "
                      "press again to put their materials back")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if is_on():
            turn_off()
            self.report({'INFO'}, "Checker off, materials restored")
        else:
            n = turn_on(context)
            if not n:
                self.report({'WARNING'}, "Select a mesh object first")
                return {'CANCELLED'}
            self.report({'INFO'}, f"Checker on for {n} object{'s' if n != 1 else ''}")
        return {'FINISHED'}


class COCOUVS_OT_checker_import(Operator):
    bl_idname = "cocouvs.checker_import"
    bl_label = "Import Checker Map"
    bl_description = "Load an image file to use as a checker map"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({'WARNING'}, "Pick an image file")
            return {'CANCELLED'}
        img = bpy.data.images.load(self.filepath, check_existing=True)
        img["cocouvs_checker_import"] = True
        context.scene.cocouvs.checker_map = f"IMG:{img.name}"
        return {'FINISHED'}


classes = (COCOUVS_OT_checker_toggle, COCOUVS_OT_checker_import)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        for name, space in (("3D View", 'VIEW_3D'), ("Image", 'IMAGE_EDITOR')):
            km = kc.keymaps.new(name=name, space_type=space)
            kmi = km.keymap_items.new(COCOUVS_OT_checker_toggle.bl_idname, 'T', 'PRESS', alt=True)
            _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
