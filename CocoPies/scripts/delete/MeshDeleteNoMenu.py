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

if bpy.context.mode != 'EDIT_MESH':
    raise RuntimeError("CocoPies: this needs Mesh Edit Mode")

use_vert, use_edge, use_face = bpy.context.tool_settings.mesh_select_mode

if use_vert or not (use_edge or use_face):
    # delete(type='VERT') also takes the vertex's edges and faces, punching a
    # hole; dissolving merges the surrounding faces instead.
    bpy.ops.mesh.dissolve_verts()
elif use_edge:
    # delete(type='EDGE') takes the faces on both sides with it; dissolving
    # merges them and clears the redundant vertices.
    bpy.ops.mesh.dissolve_edges(use_verts=True, use_face_split=False)
else:
    # A lone face has no dissolve equivalent - removing it leaves a hole.
    bpy.ops.mesh.delete(type='FACE')
