"""ACL integration tests — admin bypass, promote/demote, grant/revoke.

These tests require a running SpacetimeDB standalone.  The ``stdb_session``
fixture auto-publishes the module with a clean data dir, and admin bootstrap
uses a persistent identity token (saved to ``/tmp/stmem_admin_token``) so the
same SpacetimeDB identity is reused across test runs.

On a fresh DB (after publish --delete-data=always) it bootstraps via
register + set_initial_admin.  On subsequent runs it reuses the saved
token — the identity is already admin.
"""
from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))
sys.path.insert(0, str(REPO_ROOT / "cli"))

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]

SUFFIX = os.urandom(4).hex()
ADMIN_TOKEN_FILE = "/tmp/stmem_admin_token"


@pytest.fixture(scope="module")
def admin(stdb_session) -> Client:
    """Create an admin client using a persistent identity token.

    If a saved identity token exists (previous run), reuses it so the
    same identity (already admin) is used for all subsequent test runs.
    On a fresh DB, bootstraps via register + set_initial_admin and saves
    the identity token for reuse.
    """
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )

    # Reuse saved identity token if available
    if os.path.exists(ADMIN_TOKEN_FILE):
        with open(ADMIN_TOKEN_FILE) as f:
            token = f.read().strip()
        if token:
            c._identity_token = token
            c._identity_established = True
            return c

    # First run — bootstrap admin
    uname = f"acl_admin_{SUFFIX}"
    try:
        c._call("register", [uname, "Admin", "adminpass"])
    except RuntimeError:
        pass  # already registered

    my_id = c._whoami()
    if my_id:
        try:
            c._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass  # admin already exists

    # Save identity token for reuse across test runs
    if c._identity_token:
        with open(ADMIN_TOKEN_FILE, "w") as f:
            f.write(c._identity_token)

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
    r = admin.store(workspace_id=ws_u, peer_id="p1",
                    content="admin bypass", memory_type="experience")
    assert r["status"] == "ok"
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws_a, peer_id="p1",
                   content="should fail", memory_type="experience")


def test_02_admin_grant_revoke(admin, user):
    ws = f"acl-grant-{SUFFIX}"
    admin._call("create_workspace", ["grant-ws", "grant", ws])
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'acl_user_{SUFFIX}'")
    uid = rows[0]["id"]
    admin._call("grant_space_access", [ws, uid, "editor"])
    r = user.store(workspace_id=ws, peer_id="p1",
                   content="granted", memory_type="experience")
    assert r["status"] == "ok"
    admin._call("revoke_space_access", [ws, uid])
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws, peer_id="p1",
                   content="post-revoke", memory_type="experience")


def test_03_promote_demote(admin, user):
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'acl_user_{SUFFIX}'")
    uid = rows[0]["id"]
    admin._call("promote_admin", [uid])
    admin._call("demote_admin", [uid])


def test_04_list_admins(admin):
    admin._call("set_initial_admin", ["all"])
    r = admin._call("list_admins")
    assert isinstance(r, (list, dict))


def test_05_admin_update_delete_workspace(admin, user):
    ws = f"acl-del-{SUFFIX}"
    user._call("create_workspace", ["user-del-ws", "desc", ws])
    admin._call("update_workspace", [ws, "updated", "new desc"])
    admin._call("delete_workspace", [ws])


def test_06_user_no_delete(admin, user):
    ws = f"acl-prot-{SUFFIX}"
    admin._call("create_workspace", ["prot-ws", "protected", ws])
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'acl_user_{SUFFIX}'")
    uid = rows[0]["id"]
    admin._call("grant_space_access", [ws, uid, "editor"])
    with pytest.raises(RuntimeError, match="Access denied|'editor' permission but 'owner' is required"):
        user._call("delete_workspace", [ws])
