"""Add-ons from a backup that are not running here: which can be switched on,
which can be installed from an online repository, which cannot.

The import switches on what it can; the report offers to switch each off again.
"""

import sys

import addon_utils
import bpy


def _addon_id(module):
    return module.rsplit(".", 1)[-1]


def classify(addon_ids):
    """Return one dict per add-on that is not enabled here.

    state is "disabled" (installed, just switched off: `module` is what to
    enable), "available" (in an online repository's listing: `repo_dir` and
    `repo_name` say which), or "unavailable" (bought, installed by hand, or
    simply not listed anywhere this Blender knows).
    """
    enabled = {_addon_id(k) for k in bpy.context.preferences.addons.keys()}
    wanted = [a for a in addon_ids if a not in enabled]
    if not wanted:
        return []

    installed = {}
    for mod in addon_utils.modules(refresh=False):
        installed.setdefault(_addon_id(mod.__name__), mod.__name__)

    remote = _remote_listing(set(wanted) - set(installed))

    out = []
    for addon_id in sorted(wanted, key=str.lower):
        if addon_id in installed:
            out.append({"id": addon_id, "state": "disabled", "module": installed[addon_id]})
        elif addon_id in remote:
            repo_dir, repo_name = remote[addon_id]
            out.append({"id": addon_id, "state": "available",
                        "repo_dir": repo_dir, "repo_name": repo_name})
        else:
            out.append({"id": addon_id, "state": "unavailable"})
    return out


def _remote_listing(ids):
    """{id: (repo directory, repo name)} for ids some online repository lists.

    Reads the listing Blender already downloaded (what Get Extensions shows);
    it does not go online itself. A repository never synced has no listing,
    and its add-ons read as unavailable.
    """
    found = {}
    if not ids:
        return found
    bl_pkg = sys.modules.get("bl_pkg")
    if bl_pkg is None:
        return found
    try:
        store = bl_pkg.repo_cache_store_ensure()
    except Exception:
        return found
    for repo in bpy.context.preferences.extensions.repos:
        if not (repo.enabled and repo.use_remote_url):
            continue
        try:
            for manifest in store.pkg_manifest_from_remote_ensure(
                    error_fn=lambda _e: None, ignore_missing=True,
                    directory_subset={repo.directory}):
                for addon_id in ids:
                    if manifest and addon_id in manifest and addon_id not in found:
                        found[addon_id] = (repo.directory, repo.name)
        except Exception:
            continue
    return found


def enable(module):
    try:
        mod = addon_utils.enable(module, default_set=True, persistent=True)
    except Exception as e:
        return str(e)
    return None if mod else "Blender refused to enable it (see the system console)"


def install(repo_dir, addon_id):
    try:
        result = bpy.ops.extensions.package_install(
            repo_directory=repo_dir, pkg_id=addon_id, enable_on_install=True)
    except Exception as e:
        return str(e)
    # FINISHED says nothing about success: a failed download (measured: an
    # SSL certificate error) is reported to the Info editor and the operator
    # still returns FINISHED. Whether the add-on now runs is the only check.
    if 'FINISHED' not in result or addon_id not in {
            _addon_id(k) for k in bpy.context.preferences.addons.keys()}:
        return "not installed; the reason is in the Info editor (Window > Info)"
    return None


def disable(addon_id):
    """Switch off an add-on by its id (the last part of its module name)."""
    modules = [k for k in bpy.context.preferences.addons.keys() if _addon_id(k) == addon_id]
    if not modules:
        return "it is not enabled"
    try:
        addon_utils.disable(modules[0], default_set=True)
    except Exception as e:
        return str(e)
    return None
