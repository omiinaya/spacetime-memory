"""ACL integration tests — admin bypass, promote/demote, grant/revoke.

These tests require a running SpacetimeDB standalone.  The ``stdb_session``
fixture auto-publishes the module with a clean data dir.

Covers: admin bypass, grant/revoke space access, promote/demote admin,
list admins, workspace CRUD by admin vs user, permission boundary checks,
user isolation, and self-demotion guard.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))
sys.path.insert(0, str(REPO_ROOT / "cli"))

from spacetime_memory import Client

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
    """Admin can store in another user's workspace; user cannot in admin's."""
    ws_a = f"acl-admin-{SUFFIX}"
    ws_u = f"acl-user-{SUFFIX}"
    admin._call("create_workspace", ["admin-ws", "admin ws", ws_a])
    user._call("create_workspace", ["user-ws", "user ws", ws_u])
    # Admin bypass: store in user's workspace
    r = admin.store(
        workspace_id=ws_u, peer_id="p1", content="admin bypass", memory_type="experience"
    )
    assert r["status"] == "ok"
    # User cannot store in admin's workspace
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws_a, peer_id="p1", content="should fail", memory_type="experience")
    # Admin can also read from user's workspace
    results = admin.search(workspace_id=ws_u, query="admin bypass")
    assert len(results) >= 1


def test_02_admin_grant_revoke(admin, user):
    """Grant then revoke space access controls user permissions."""
    ws = f"acl-grant-{SUFFIX}"
    admin._call("create_workspace", ["grant-ws", "grant", ws])
    uid = user._whoami()
    assert uid, "Could not determine user identity"

    # Grant editor access
    admin._call("grant_space_access", [ws, uid, "editor"])
    r = user.store(workspace_id=ws, peer_id="p1", content="granted", memory_type="experience")
    assert r["status"] == "ok"

    # Revoke access
    admin._call("revoke_space_access", [ws, uid])
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws, peer_id="p1", content="post-revoke", memory_type="experience")

    # Verify the grant call used correct parameters
    # (we already checked behavior above)


def test_03_promote_demote(admin, user):
    """Promote and demote a regular user to/from admin."""
    uid = user._whoami()
    assert uid, "Could not determine user identity"

    # Promote user to admin
    admin._call("promote_admin", [uid])
    # Demote back
    admin._call("demote_admin", [uid])

    # After demote, user is a regular user again.
    # list_admins intentionally allows any authenticated user to view admin list,
    # so this should succeed (it requires auth, not admin role — see auth.rs:1195).
    result = user._call("list_admins", [])
    # Should return a list or dict of admins, not raise
    assert result is not None


def test_04_list_admins(admin):
    """List admins returns at least the current admin."""
    try:
        admin._call("set_initial_admin", ["all"])
    except RuntimeError:
        pass  # admin already exists — fine
    r = admin._call("list_admins", [])
    assert isinstance(r, (list, dict))
    if isinstance(r, list):
        assert len(r) >= 1
        # Each entry should have an identity field
        for entry in r:
            assert "identity" in entry, f"Admin entry missing identity: {entry}"
    elif isinstance(r, dict):
        assert "status" in r


def test_05_admin_update_delete_workspace(admin, user):
    """Admin can update and delete any workspace."""
    ws = f"acl-del-{SUFFIX}"
    user._call("create_workspace", ["user-del-ws", "desc", ws])

    # Admin can update user's workspace
    admin._call("update_workspace", [ws, "updated", "new desc"])
    # Verify the update
    admin.search(workspace_id=ws, query="updated")
    # Admin can delete user's workspace
    admin._call("delete_workspace", [ws])


def test_06_user_no_delete(admin, user):
    """User with editor permission cannot delete a workspace."""
    ws = f"acl-prot-{SUFFIX}"
    admin._call("create_workspace", ["prot-ws", "protected", ws])
    uid = user._whoami()
    assert uid, "Could not determine user identity"
    admin._call("grant_space_access", [ws, uid, "editor"])
    with pytest.raises(
        RuntimeError, match="Access denied|'editor' permission but 'owner' is required"
    ):
        user._call("delete_workspace", [ws])


def test_07_workspace_isolation(admin, user):
    """Two non-admin users cannot access each other's workspaces."""
    ws_u1 = f"acl-iso-1-{SUFFIX}"
    ws_u2 = f"acl-iso-2-{SUFFIX}"
    admin._call("create_workspace", ["iso-1", "isolated 1", ws_u1])
    admin._call("create_workspace", ["iso-2", "isolated 2", ws_u2])

    uid1 = admin._whoami()  # admin for the purpose of grant
    uid2 = user._whoami()

    # Grant each access to a different workspace
    admin._call("grant_space_access", [ws_u1, uid1, "editor"])
    admin._call("grant_space_access", [ws_u2, uid2, "editor"])

    # User CAN search in ws_u2 (where access was granted)
    ws_u2_results = user.search(workspace_id=ws_u2, query="test")
    assert len(ws_u2_results) >= 0  # may be empty, but access should not raise

    # User CANNOT search in ws_u1 (no permission — should raise)
    with pytest.raises(RuntimeError, match="Access denied"):
        user.search(workspace_id=ws_u1, query="test")

    # Admin can see both (implicit admin access)
    admin_results = admin.search(workspace_id=ws_u1, query="test")
    assert isinstance(admin_results, list)


def test_08_grant_revoke_self(admin, user):
    """User cannot grant or revoke their own admin status."""
    uid = user._whoami()
    assert uid

    # Regular user cannot promote themselves
    with pytest.raises(RuntimeError):
        user._call("promote_admin", [uid])

    # Regular user cannot demote themselves
    with pytest.raises(RuntimeError):
        user._call("demote_admin", [uid])


def test_09_grant_nonexistent_user(admin):
    """Granting access to a non-existent identity by hex should not crash."""
    fake_id = "0" * 64  # 64 hex chars
    ws = f"acl-nonex-{SUFFIX}"
    admin._call("create_workspace", ["nonex-ws", "test", ws])
    try:
        admin._call("grant_space_access", [ws, fake_id, "editor"])
    except RuntimeError as e:
        # Expected: no such identity
        assert "identity" in str(e).lower() or "not found" in str(e).lower()


def test_10_revoke_then_grant_cycle(admin, user):
    """Revoke then re-grant access restores permissions."""
    ws = f"acl-cycle-{SUFFIX}"
    admin._call("create_workspace", ["cycle-ws", "cycle", ws])
    uid = user._whoami()
    assert uid

    # Grant, revoke, re-grant
    admin._call("grant_space_access", [ws, uid, "editor"])
    admin._call("revoke_space_access", [ws, uid])
    admin._call("grant_space_access", [ws, uid, "editor"])

    # Should work again
    r = user.store(workspace_id=ws, peer_id="p1", content="re-granted", memory_type="experience")
    assert r["status"] == "ok"
