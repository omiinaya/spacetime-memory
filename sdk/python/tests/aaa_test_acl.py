"""ACL integration tests — admin bypass, promote/demote, grant/revoke.

Uses set_initial_admin for deterministic admin. The Client auto-captures
the SpacetimeDB identity token for consistent identity across calls.
"""
import os
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))
sys.path.insert(0, str(REPO_ROOT / "cli"))

from spacetime_memory import Client

DB = os.environ.get("SPACETIMEDB_DB", "c200e409f602c06527d0aa66dc2d05718a6b62c4c3317b5498951cea41782713")
SUFFIX = os.urandom(4).hex()

pytestmark = [pytest.mark.skipif(not DB, reason="SPACETIMEDB_DB required")]


def _register(client, username, display, password):
    try:
        client._call("register", [username, display, password])
    except RuntimeError as e:
        if "already" not in str(e).lower():
            raise


@pytest.fixture(scope="module")
def admin() -> Client:
    c = Client(database=DB)
    # Register as admin (first user in this Client = admin)
    _register(c, f"admin_{SUFFIX}", "Admin", "adminpass")
    # Ensure admin role — use set_initial_admin for fresh, promote_admin for existing
    try:
        resp = c._http.get(f"http://localhost:3001/v1/database/{DB}",
                           headers=c._headers())
        my_id = resp.headers.get("spacetime-identity", "")
        if not my_id:
            return c
        try:
            c._call("set_initial_admin", [my_id])
        except RuntimeError as e:
            err = str(e).lower()
            if "already exists" in err:
                # Account exists but might not be admin — promote
                try:
                    c._call("promote_admin", [my_id])
                except RuntimeError as pe:
                    if "already an admin" not in str(pe).lower():
                        raise
            elif "already has" in err:
                try:
                    c._call("promote_admin", [my_id])
                except RuntimeError as pe:
                    if "already an admin" not in str(pe).lower():
                        raise
            else:
                raise
    except Exception:
        pass
    return c


@pytest.fixture(scope="module")
def user() -> Client:
    c = Client(database=DB)
    _register(c, f"user_{SUFFIX}", "User", "userpass")
    return c


def test_01_admin_bypass(admin, user):
    """Admin can access any workspace; user cannot access without permission."""
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
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'user_{SUFFIX}'")
    uid = rows[0]["id"]

    admin._call("grant_space_access", [ws, uid, "editor"])
    r = user.store(workspace_id=ws, peer_id="p1",
                   content="granted", memory_type="experience")
    assert r["status"] == "ok"

    admin._call("revoke_space_access", [ws, uid])
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws, peer_id="p1",
                   content="revoked", memory_type="experience")


def test_03_promote_demote(admin, user):
    ws = f"acl-prom-{SUFFIX}"
    admin._call("create_workspace", ["prom-ws", "prom", ws])
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'user_{SUFFIX}'")
    uid = rows[0]["id"]

    admin._call("promote_admin", [uid])
    r = user.store(workspace_id=ws, peer_id="p1",
                   content="promoted", memory_type="experience")
    assert r["status"] == "ok"

    admin._call("demote_admin", [uid])
    with pytest.raises(RuntimeError, match="Access denied"):
        user.store(workspace_id=ws, peer_id="p1",
                   content="demoted", memory_type="experience")


def test_04_list_admins(admin):
    admin._call("list_admins", [])
    rows = admin._sql("SELECT * FROM admin_list_result")
    assert len(rows) >= 1


def test_05_admin_update_delete_workspace(admin, user):
    ws = f"acl-del-{SUFFIX}"
    user._call("create_workspace", ["del-ws", "del", ws])
    admin._call("update_workspace", [ws, "updated", "by admin"])
    rows = admin._sql(f"SELECT name FROM workspace WHERE id = '{ws}'")
    assert rows[0]["name"] == "updated"
    admin._call("delete_workspace", [ws])
    rows = admin._sql(f"SELECT * FROM workspace WHERE id = '{ws}'")
    assert len(rows) == 0


def test_06_user_no_delete(admin, user):
    ws = f"acl-prot-{SUFFIX}"
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'user_{SUFFIX}'")
    uid = rows[0]["id"]
    admin._call("create_workspace", ["prot-ws", "protected", ws])
    admin._call("grant_space_access", [ws, uid, "editor"])
    with pytest.raises(RuntimeError, match="Access denied"):
        user._call("delete_workspace", [ws])
