# CocoAttributes

Blender add-on for managing vertex groups, UV maps, color attributes and
attributes on **every selected mesh at once**.

Requires Blender **5.2 LTS** or newer.

## Install

CocoAttributes is a Blender **Extension**, published from the
[CocoTools](https://github.com/MoonCoconutz/CocoTools) repository.

`Edit > Preferences > Get Extensions > repositories ▾ > + > Add Remote
Repository`, URL:

```
https://mooncoconutz.github.io/CocoTools/index.json
```

Then find **CocoAttributes** in Get Extensions and install it.

## Use

Properties editor, **Data** tab (the green triangle), **CocoAttributes**
panel. It sits below Blender's own panels; drag it higher by its `⠿` grip if
you like. Blender's own Vertex Groups, UV Maps, Color Attributes and
Attributes panels are not changed and still work on the active object only.

The Data tab follows the **active** object, so the panel shows while the
active object is a mesh. It works on the active object plus every selected
mesh (and every mesh in Edit Mode). Linked duplicates share one mesh, so they
count once: the panel's first line says how many meshes, and how many objects
when that differs.

### The two lists

**Vertex Groups** and **Attributes** each show every one found on **any**
selected mesh, each once. **Attributes** holds UV maps first (UV icon), then
color attributes (color icon), then every other attribute, each row saying
what it is (UV Map, or domain · type). Hidden attributes are left out:
Blender's internal ones, and any whose name starts with "." (add-ons keep
their private data that way). An attribute with the same name but a different domain or type
on two meshes shows as two rows.

| Control | Action |
| --- | --- |
| **Tick box** | Pick the row for `−`, Fill Missing and the Edit Mode buttons. Tick as many as you like |
| **Click a name** | Make it the active one on every selected mesh that has it (as clicking in Blender's own list does for one object), and tick that row alone. The highlighted row is the one you last clicked, while it is still active |
| **Double-click a name** (or Ctrl-click) | Rename it on every selected mesh that has it. A mesh that already uses the new name for something else keeps the old name, and a note under the list says so (Blender would otherwise call it "name.001" there) |
| **N/total** | How many of the selected meshes have it. A warning icon means some do not |
| **Lock** | Blender will not remove or rename it (`position`) |
| **Camera** (UV maps, color attributes) | Render with it on every selected mesh that has it |
| `+` | Add one, with the same name, to every selected mesh. In Attributes it first asks for the name and the type (Attribute, Color Attribute or UV Map), plus domain and data type where they apply. A UV map is copied from each mesh's active UV map |
| `−` | Remove the ticked rows from every selected mesh |
| **Fill Missing** (clipboard icon) | For each ticked row, add it to the selected meshes that do not have it: same name, and for attributes the same domain and type. Vertex groups come in empty, attributes and color attributes as zero (black), UV maps copied from that mesh's active one, custom normals through Blender's own Add Custom Normals Data |
| **Tick All** (check-box icon) | Tick every row, or untick them all if any is ticked |
| `▸` (bottom left of a list) | Blender's own filter: search by name, sort A-Z |

### Edit Mode (Vertex Groups)

With meshes in Edit Mode, four buttons work on the **ticked** vertex groups,
on **every** mesh in Edit Mode at once (Blender's own buttons only touch the
active object):

| Button | Action |
| --- | --- |
| **Assign** | Put the selected vertices in the ticked groups, with the **Weight** below (Blender's own Weight setting). A mesh without the group gets it |
| **Remove** | Take the selected vertices out of the ticked groups |
| **Select** / **Deselect** | Select or deselect the vertices in the ticked groups |

Locked groups are skipped, as with Blender's own Assign.

### Custom normals

Under the Attributes list: **Add Custom Normals** adds custom normals data
to every selected mesh that has none, and shows how many already have it.

## Undo

Every change can be undone with Ctrl+Z, including renames, clicks on a name
and the camera.
