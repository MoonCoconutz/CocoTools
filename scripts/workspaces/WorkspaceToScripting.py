"""Switch the active workspace to "Scripting".

Bundled with CocoPie as an example of a pie slot that runs a script file.
A slot calls this with:

    execute_script("<path to this file>")

Copy this file and change WORKSPACE to point at any workspace you like.
"""

import bpy

WORKSPACE = "Scripting"


def main():
    workspace = bpy.data.workspaces.get(WORKSPACE)
    if workspace is None:
        # Not every .blend carries every workspace, so a miss is normal rather
        # than an error -- say so and leave the current workspace alone.
        print("CocoPie: no workspace named %r in this file" % WORKSPACE)
        return
    bpy.context.window.workspace = workspace


main()
