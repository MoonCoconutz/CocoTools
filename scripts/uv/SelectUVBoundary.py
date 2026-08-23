"""Select the border edges of every UV island.

Blender ships no operator for this. Its own uv.* selection operators work on
islands, loops, pinned UVs, overlaps and so on, but none of them expose "the
outline of each island" -- checked against the full uv.* operator list, not
assumed. Zen UV has one; this does it with nothing but stock Blender so the
slot keeps working without that addon installed.

An edge is on an island border when only ONE face uses it *in UV space*. That
covers both cases at once, which is why it is the test used here rather than
looking for seams:

  * a real mesh boundary -- the edge only ever had one face; and
  * a UV seam -- two faces still share the mesh edge, but their UVs were cut
    apart, so in UV space each face has its own copy of that edge.

Counting how many times each UV-space edge appears therefore finds both
without needing to know which is which. Interior edges appear twice.

Bundled with CocoPie as an example of a pie slot that runs a script file.
A slot calls this with:

    execute_script("<path to this file>")
"""

from collections import Counter

import bmesh
import bpy


def _uv_edge_key(loop, uv_layer):
    """Both ends of this loop's edge in UV space, order-independent.

    Rounded before comparing: two faces meeting along a shared edge should
    agree to the last bit, but coordinates that arrive from different
    unwraps can differ in the final decimals, and an exact == would then
    read a continuous edge as two separate ones and wrongly call it a
    border.
    """
    a = loop[uv_layer].uv
    b = loop.link_loop_next[uv_layer].uv
    return tuple(sorted((
        (round(a.x, 6), round(a.y, 6)),
        (round(b.x, 6), round(b.y, 6)),
    )))


def select_uv_boundary(obj):
    """Select island border edges on one mesh. Returns how many it selected."""
    bm = bmesh.from_edit_mesh(obj.data)

    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        return 0

    # Blender 5.x keeps UV selection in these corner attributes rather than on
    # the UV loop itself -- BMLoopUV carries only `uv` and `pin_uv` now, so the
    # older loop[uv_layer].select does not exist. They may not be present yet
    # on a mesh whose UVs have never been selected.
    bools = bm.loops.layers.bool
    vert_sel = bools.get(".uv_select_vert") or bools.new(".uv_select_vert")
    edge_sel = bools.get(".uv_select_edge") or bools.new(".uv_select_edge")

    # With UV sync off the UV editor only shows faces selected in the mesh, so
    # anything hidden there is not a candidate -- otherwise this would select
    # borders you cannot see, around islands that are not on screen.
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return 0

    counts = Counter()
    for face in faces:
        for loop in face.loops:
            counts[_uv_edge_key(loop, uv_layer)] += 1

    for face in bm.faces:
        for loop in face.loops:
            loop[vert_sel] = False
            loop[edge_sel] = False

    selected = 0
    for face in faces:
        for loop in face.loops:
            if counts[_uv_edge_key(loop, uv_layer)] == 1:
                loop[edge_sel] = True
                # An edge is only drawn as selected when both its ends are, so
                # the far end has to be marked too -- that is the next loop
                # round the same face.
                loop[vert_sel] = True
                loop.link_loop_next[vert_sel] = True
                selected += 1

    bmesh.update_edit_mesh(obj.data)
    return selected


def main():
    if bpy.context.mode != 'EDIT_MESH':
        print("CocoPie: select UV boundary needs Edit Mode")
        return

    # Show the result as edges; selecting edges while the editor is in vertex
    # or face mode would look like nothing happened.
    bpy.context.scene.tool_settings.uv_select_mode = 'EDGE'

    total = 0
    # objects_in_mode rather than the active object alone, so multi-object
    # edit mode selects borders on every mesh being edited
    for obj in bpy.context.objects_in_mode:
        if obj.type == 'MESH':
            total += select_uv_boundary(obj)

    print(f"CocoPie: selected {total} UV border edge(s)")


main()
