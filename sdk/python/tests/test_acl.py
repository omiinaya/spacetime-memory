"""ACL integration tests — admin bypass, promote/demote, grant/revoke.

These tests require a running SpacetimeDB standalone.  The ``stdb_session``
fixture auto-publishes the module with a clean data dir.
"""

from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))
sys.path.insert(0, str(REPO_ROOT / "cli"))

from spacetime_memory import Client  # noqa: E402 — intentional: after sys.path.insert

pytestmark = [
    pytest.mark.integration,
]

SUFFIX = os.urandom(4).hex()


@pytest.fixture(scope="module")
def admin(stdb_session) -> Client:
    """Create an admin client by registering and bootstrapping as admin.

    Works without JWT: registers a new user with the anonymous identity,
    then calls set_initial_admin(self_identity) since no admin exists yet.
    The conftest publishes with --delete-data=always, so each run is clean.
    """
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )

    uname = f"acl_admin_{SUFFIX}"
    c._call("register", [uname, "Admin", "adminpass"])

    my_id = c._whoami()
    if my_id:
        try:
            c._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass  # admin already exists (race unlikely)

    return c


@pytest.fixture(scope="module")
def user(stdb_session) -> Client:
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )
    try:
        c._call("register", [f"acl_user_{SUFFIX}", "User", "userpass"])
    except RuntimeError as e:
        if "already" not in str(e).lower():
            raise
    return c


# =====================================================================
# Tests
# =====================================================================


def test_01_admin_bypass(admin, user):
    ws_a = f"acl-admin-{SUFFIX}"
    ws_u = f"acl-user-{SUFFIX}"
    admin._call("create_workspace", ["admin-ws", "admin ws", ws_a])
    user._call("create_workspace", ["user-ws", "user ws", ws_u])
    r = admin.store(
        workspace_id=ws_u, peer_id="p1", content="admin bypass", memory_type="experience"
    )
    assert r["status"] == "ok"
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws_a, peer_id="p1", content="should fail", memory_type="experience")


def test_02_admin_grant_revoke(admin, user):
    ws = f"acl-grant-{SUFFIX}"
    admin._call("create_workspace", ["grant-ws", "grant", ws])
    uid = user._whoami()
    assert uid, "Could not determine user identity"
    admin._call("grant_space_access", [ws, uid, "editor"])
    r = user.store(workspace_id=ws, peer_id="p1", content="granted", memory_type="experience")
    assert r["status"] == "ok"
    admin._call("revoke_space_access", [ws, uid])
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws, peer_id="p1", content="post-revoke", memory_type="experience")


def test_03_promote_demote(admin, user):
    uid = user._whoami()
    assert uid, "Could not determine user identity"
    admin._call("promote_admin", [uid])
    admin._call("demote_admin", [uid])


def test_04_list_admins(admin):
    try:
        admin._call("set_initial_admin", ["all"])
    except RuntimeError:
        pass  # admin already exists — fine
    r = admin._call("list_admins", [])
    assert isinstance(r, (list, dict))


def test_05_admin_update_delete_workspace(admin, user):
    ws = f"acl-del-{SUFFIX}"
    user._call("create_workspace", ["user-del-ws", "desc", ws])
    admin._call("update_workspace", [ws, "updated", "new desc"])
    admin._call("delete_workspace", [ws])


def test_06_user_no_delete(admin, user):
    ws = f"acl-prot-{SUFFIX}"
    admin._call("create_workspace", ["prot-ws", "protected", ws])
    uid = user._whoami()
    assert uid, "Could not determine user identity"
    admin._call("grant_space_access", [ws, uid, "editor"])
    with pytest.raises(
        RuntimeError, match="Access denied|'editor' permission but 'owner' is required"
    ):
        user._call("delete_workspace", [ws])
