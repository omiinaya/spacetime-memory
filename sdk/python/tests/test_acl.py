"""ACL integration tests — admin bypass, promote/demote, grant/revoke.

Admin bootstraps via set_initial_admin (no register) — guarantees admin role.
User registers normally (will always be user since admin exists).
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


@pytest.fixture(scope="module")
def admin() -> Client:
    """Create an admin client via set_initial_admin (no register needed)."""
    c = Client(database=DB)
    my_id = c._whoami()
    if my_id:
        try:
            c._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass  # admin already exists
    return c


@pytest.fixture(scope="module")
def user() -> Client:
    c = Client(database=DB)
    try:
        c._call("register", [f"acl_user_{SUFFIX}", "User", "userpass"])
    except RuntimeError as e:
        if "already" not in str(e).lower():
            raise
    return c


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
                   content="revoked", memory_type="experience")


def test_03_promote_demote(admin, user):
    ws = f"acl-prom-{SUFFIX}"
    admin._call("create_workspace", ["prom-ws", "prom", ws])
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'acl_user_{SUFFIX}'")
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
    rows = admin._sql(f"SELECT * FROM account WHERE username = 'acl_user_{SUFFIX}'")
    uid = rows[0]["id"]
    admin._call("create_workspace", ["prot-ws", "protected", ws])
    admin._call("grant_space_access", [ws, uid, "editor"])
    with pytest.raises(RuntimeError, match="Access denied"):
        user._call("delete_workspace", [ws])
