"""Delete the mesh selection without Blender's delete menu appearing.

Was CocoDelete's `mesh.cocodelete_delete` operator. It lives here as a script
so a pie's tap action can run it without CocoPies depending on another
extension being installed and enabled -- a tap bound to an operator from a
disabled add-on silently does nothing, which is exactly how this started.

The mode check replaces the operator's `poll()`. An operator that fails poll
is simply skipped by Blender; a script is not gated by anything, so without
this a tap in the wrong mode raises a context error at the user instead.
"""

import bpy
import bmesh

if bpy.context.mode != 'EDIT_MESH':
    raise RuntimeError("CocoPies: this needs Mesh Edit Mode")


def selected_verts():
    """[(bmesh, its selected vertices)] for every mesh in Edit Mode.

    The BMesh is kept with its vertices on purpose: once Python frees the
    wrapper, every vertex taken from it reads as invalid, and with two objects
    in Edit Mode the first one's survivors were skipped.
    """
    found = []
    for ob in bpy.context.objects_in_mode_unique_data:
        bm = bmesh.from_edit_mesh(ob.data)
        found.append((bm, [v for v in bm.verts if v.select]))
    return found


def select_only_survivors(found):
    """Select exactly those of `found` still in the mesh; False if none are.

    Only the survivors may be selected, or the next operator also takes
    whatever the last one left selected around them.
    """
    left = [(bm, [v for v in verts if v.is_valid]) for bm, verts in found]
    if not any(verts for _bm, verts in left):
        return False
    for bm, verts in left:
        for seq in (bm.faces, bm.edges, bm.verts):
            for elem in seq:
                elem.select = False
        for v in verts:
            v.select = True
        # Up to the edges between them too, which a delete by edge acts on
        bm.select_flush(True)
    return True


def delete_survivors(found):
    """Delete outright whichever of `found` a dissolve could not remove.

    Dissolving only ever removes a vertex it can merge away. A loose vertex, or
    the last vertex of a chain of loose edges, has nothing to merge, so it used
    to stay put; and dissolving a whole selected chain left one edge running
    from where the chain started to its last vertex. X is expected to take the
    vertex either way, so what is left over goes the hard way.
    """
    if select_only_survivors(found):
        bpy.ops.mesh.delete(type='VERT')


def delete_edges():
    """X in Edge Mode, on every mesh in Edit Mode.

    delete(type='EDGE') takes the faces on both sides of an edge with it;
    dissolving merges them instead. Dissolving alone is wrong when the faces
    themselves are selected: every selected edge fuses its two faces, so a
    fully selected tube or grid collapsed into one large leftover face instead
    of going away. So, in this order:

    1. A face with every edge selected is deleted, and so is the face of a
       selected border edge (nothing on the other side to merge with). A
       delete by face also takes the edges and vertices only those faces used.
    2. The selected edges still between two faces are dissolved, which merges
       those faces. use_verts=True also dissolves an end vertex left with just
       two edges, the one it would otherwise leave as a stray kink. A vertex
       that still joins three or more edges stays as a T-junction, as it
       should: dissolving it too merged the faces on every side into one large
       n-gon.
    3. A selected edge with no face (a wire) has nothing to dissolve into, so
       it is deleted as an edge, with any vertex left without one but not a
       vertex another, unselected wire edge still uses.

    Done in BMesh rather than by operator, so what happens never depends on
    which selection the previous step left behind.
    """
    for ob in bpy.context.objects_in_mode_unique_data:
        bm = bmesh.from_edit_mesh(ob.data)
        edges = {e for e in bm.edges if e.select}
        if not edges:
            continue

        doomed = {f for f in bm.faces if all(e in edges for e in f.edges)}
        for e in edges:
            if len(e.link_faces) == 1:
                doomed.add(e.link_faces[0])
        if doomed:
            bmesh.ops.delete(bm, geom=list(doomed), context='FACES')

        edges = [e for e in edges if e.is_valid]
        between = [e for e in edges if len(e.link_faces) == 2]
        if between:
            bmesh.ops.dissolve_edges(bm, edges=between, use_verts=True,
                                     use_face_split=False)

        wires = [e for e in edges if e.is_valid and not e.link_faces]
        if wires:
            bmesh.ops.delete(bm, geom=wires, context='EDGES')

        for seq in (bm.faces, bm.edges, bm.verts):
            for elem in seq:
                elem.select = False
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=True)


use_vert, use_edge, use_face = bpy.context.tool_settings.mesh_select_mode

if use_vert or not (use_edge or use_face):
    # delete(type='VERT') also takes the vertex's edges and faces, punching a
    # hole; dissolving merges the surrounding faces instead.
    found = selected_verts()
    bpy.ops.mesh.dissolve_verts()
    delete_survivors(found)
elif use_edge:
    delete_edges()
else:
    # A lone face has no dissolve equivalent - removing it leaves a hole.
    bpy.ops.mesh.delete(type='FACE')
