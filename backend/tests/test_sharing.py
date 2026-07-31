"""Public share links: create/resolve/revoke/expire + isolation + capability."""

import csv
import io

import pytest

from app.analytics.engine import DatasetNotFound
from app.analytics.sharing import (
    ShareError, ShareNotFound, create_share, list_shares, resolve_share,
    resolve_share_dashboard_config, revoke_share,
)
from app.analytics.views import create_view
from app.ingest.pipeline import ingest_upload


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SALES = [["date", "branch", "revenue"],
         ["2025-01-05", "Delhi", "1000"],
         ["2025-01-06", "Mumbai", "2000"]]


@pytest.fixture()
def ds(con):
    con.execute("INSERT INTO workspaces VALUES ('ws_a', 'A', now())")
    con.execute("INSERT INTO workspaces VALUES ('ws_b', 'B', now())")
    res = ingest_upload(con, "ws_a", "sales.csv", _csv(SALES))
    return con, "ws_a", res.dataset_id


# ------------------------------------------------------ create + resolve ---

def test_create_and_resolve(ds):
    con, ws, dsid = ds
    share = create_share(con, ws, dsid)
    assert share["token"] and share["path"] == f"/share/{share['token']}"
    resolved = resolve_share(con, share["token"])
    assert resolved["workspace_id"] == ws and resolved["dataset_id"] == dsid


def test_share_pins_a_view(ds):
    con, ws, dsid = ds
    v = create_view(con, ws, dsid, "Delhi", {"filters": {"branch": "Delhi"}, "hidden_sections": ["treemap"]})
    share = create_share(con, ws, dsid, view_id=v["view_id"])
    _, _, cfg = resolve_share_dashboard_config(con, share["token"])
    assert cfg["filters"] == {"branch": "Delhi"} and cfg["hidden_sections"] == ["treemap"]


def test_share_view_must_match_dataset(ds):
    con, ws, dsid = ds
    other = ingest_upload(con, ws, "other.csv", _csv(SALES)).dataset_id
    v = create_view(con, ws, other, "V", {})
    with pytest.raises(ShareError):
        create_share(con, ws, dsid, view_id=v["view_id"])


def test_create_on_foreign_dataset_is_404(ds):
    con, _, dsid = ds
    with pytest.raises(DatasetNotFound):
        create_share(con, "ws_b", dsid)


# --------------------------------------------------------- revoke/expire ---

def test_revoke_disables_the_link(ds):
    con, ws, dsid = ds
    share = create_share(con, ws, dsid)
    assert revoke_share(con, ws, share["token"]) == 1
    with pytest.raises(ShareNotFound):
        resolve_share(con, share["token"])


def test_expired_link_is_rejected(ds):
    con, ws, dsid = ds
    share = create_share(con, ws, dsid, expires_in_days=1)
    # force the expiry into the past
    con.execute("UPDATE share_links SET expires_at = now() - to_days(2) WHERE token = ?", [share["token"]])
    with pytest.raises(ShareNotFound):
        resolve_share(con, share["token"])


def test_zero_expiry_means_never(ds):
    con, ws, dsid = ds
    share = create_share(con, ws, dsid, expires_in_days=0)
    assert share["expires_at"] is None
    assert resolve_share(con, share["token"])["dataset_id"] == dsid


# ------------------------------------------------- isolation + capability --

def test_listing_and_revoke_are_workspace_scoped(ds):
    con, ws, dsid = ds
    share = create_share(con, ws, dsid)
    # ws_b cannot see or revoke ws_a's link…
    assert list_shares(con, "ws_b", dsid) == []
    assert revoke_share(con, "ws_b", share["token"]) == 0
    # …but the public token still resolves (possession is the capability)
    assert resolve_share(con, share["token"])["workspace_id"] == ws


def test_unknown_token_is_not_found(ds):
    con, _, _ = ds
    with pytest.raises(ShareNotFound):
        resolve_share(con, "definitely-not-a-real-token")
