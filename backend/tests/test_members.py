"""Team members + roles: create/invite, role change, last-admin guard, scope."""

import pytest

from app.members import (
    MemberError, MemberNotFound, change_password, create_member, delete_member,
    list_members, update_member_role,
)
from app.core.security import hash_password


@pytest.fixture()
def ws(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    con.execute("INSERT INTO users (user_id, workspace_id, email, password_hash, role) VALUES "
                "('usr_admin', 'ws_a', 'admin@a.com', ?, 'admin')", [hash_password("origadmin1")])
    return con, "ws_a", "usr_admin"


# ------------------------------------------------------- create/invite ----

def test_invite_generates_temp_password(ws):
    con, wsid, actor = ws
    m = create_member(con, wsid, "bob@a.com", "editor")
    assert m["role"] == "editor" and m["temp_password"]           # returned once
    # the temp password actually works for login lookup
    row = con.execute("SELECT role FROM users WHERE email = 'bob@a.com'").fetchone()
    assert row[0] == "editor"
    assert len(list_members(con, wsid)) == 2


def test_invite_with_explicit_password(ws):
    con, wsid, _ = ws
    m = create_member(con, wsid, "sue@a.com", "viewer", password="viewerpass1")
    assert m["temp_password"] is None


def test_invite_rejects_short_password_and_dupes(ws):
    con, wsid, _ = ws
    with pytest.raises(MemberError):
        create_member(con, wsid, "x@a.com", "viewer", password="short")
    with pytest.raises(MemberError):
        create_member(con, wsid, "admin@a.com", "viewer")   # already registered
    with pytest.raises(MemberError):
        create_member(con, wsid, "y@a.com", "superuser")    # bad role


# --------------------------------------------------------- role changes ----

def test_change_role(ws):
    con, wsid, actor = ws
    bob = create_member(con, wsid, "bob@a.com", "viewer")
    update_member_role(con, wsid, actor, bob["user_id"], "editor")
    assert next(m for m in list_members(con, wsid) if m["user_id"] == bob["user_id"])["role"] == "editor"


def test_cannot_demote_last_admin(ws):
    con, wsid, actor = ws
    with pytest.raises(MemberError):
        update_member_role(con, wsid, actor, actor, "viewer")   # only admin
    # but once a second admin exists, demotion is allowed
    two = create_member(con, wsid, "admin2@a.com", "admin")
    update_member_role(con, wsid, actor, actor, "viewer")
    roles = {m["user_id"]: m["role"] for m in list_members(con, wsid)}
    assert roles[actor] == "viewer" and roles[two["user_id"]] == "admin"


# ------------------------------------------------------------ delete -------

def test_cannot_delete_self_or_last_admin(ws):
    con, wsid, actor = ws
    with pytest.raises(MemberError):
        delete_member(con, wsid, actor, actor)                  # self
    bob = create_member(con, wsid, "bob@a.com", "editor")
    assert delete_member(con, wsid, actor, bob["user_id"])["ok"] is True
    assert len(list_members(con, wsid)) == 1


def test_delete_missing_member(ws):
    con, wsid, actor = ws
    with pytest.raises(MemberNotFound):
        delete_member(con, wsid, actor, "usr_ghost")


# --------------------------------------------------------- passwords -------

def test_change_password(ws):
    con, _, actor = ws
    with pytest.raises(MemberError):
        change_password(con, actor, "wrongpass", "newpass12")   # wrong current
    assert change_password(con, actor, "origadmin1", "newpass12")["ok"] is True
    with pytest.raises(MemberError):
        change_password(con, actor, "newpass12", "short")       # too short


# --------------------------------------------------------- isolation -------

def test_members_are_workspace_scoped(ws):
    con, wsid, actor = ws
    bob = create_member(con, wsid, "bob@a.com", "editor")
    assert list_members(con, "ws_b") == []
    with pytest.raises(MemberNotFound):
        update_member_role(con, "ws_b", "someone", bob["user_id"], "viewer")
