"""Saved dashboard views — named, persisted dashboard configurations.

A *view* captures the analytical state a user wants to return to: the active
filters, date range, chosen measure, and which sections are hidden (the
"customize" part). Views are workspace + dataset scoped; one view per dataset
can be the default, auto-applied when the dataset is opened.

The config is stored as JSON but validated and whitelisted here first — the
section keys must be known, filter/measure values are coerced to strings, and
the whole blob is size-capped — so nothing unexpected is ever persisted. (The
filters are additionally re-validated at query time by the dashboard engine's
identifier whitelist, so a saved config can never widen data access.)
"""

import json

from ..core.security import new_id
from .engine import get_dataset

# Canonical dashboard section keys the frontend can hide/show.
SECTION_KEYS = {
    "kpis", "metrics", "drivers", "growth", "insights", "narrative", "forecast",
    "breakdowns", "map", "pareto", "treemap", "correlations", "distributions", "profile",
}
MAX_CONFIG_BYTES = 8192
MAX_NAME = 80
MAX_FILTERS = 50

_VIEW_SELECT = "view_id, dataset_id, name, config, is_default, created_at, updated_at"


class ViewError(ValueError):
    """A view could not be created or updated (bad name/config)."""


class ViewNotFound(ViewError):
    """No such view in this workspace."""


def _validate_config(config) -> dict:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ViewError("config must be an object")

    filters = config.get("filters") or {}
    if not isinstance(filters, dict):
        raise ViewError("filters must be an object")
    if len(filters) > MAX_FILTERS:
        raise ViewError("too many filters")

    out = {"filters": {str(k): str(v) for k, v in filters.items()}}
    for key in ("date_from", "date_to", "measure"):
        v = config.get(key)
        if v is not None and not isinstance(v, str):
            raise ViewError(f"{key} must be a string")
        out[key] = v or None

    hidden = config.get("hidden_sections") or []
    if not isinstance(hidden, list):
        raise ViewError("hidden_sections must be a list")
    unknown = [h for h in hidden if h not in SECTION_KEYS]
    if unknown:
        raise ViewError(f"unknown section(s): {', '.join(map(str, unknown))}")
    out["hidden_sections"] = list(dict.fromkeys(hidden))  # dedupe, keep order

    if len(json.dumps(out).encode()) > MAX_CONFIG_BYTES:
        raise ViewError("config is too large")
    return out


def _row_to_view(row) -> dict:
    return {
        "view_id": row[0], "dataset_id": row[1], "name": row[2],
        "config": json.loads(row[3]), "is_default": bool(row[4]),
        "created_at": str(row[5]), "updated_at": str(row[6]),
    }


def _get_view(con, workspace_id: str, view_id: str) -> dict:
    row = con.execute(
        f"SELECT {_VIEW_SELECT} FROM dashboard_views WHERE view_id = ? AND workspace_id = ?",
        [view_id, workspace_id],
    ).fetchone()
    if row is None:
        raise ViewNotFound("view not found")
    return _row_to_view(row)


def list_views(con, workspace_id: str, dataset_id: str) -> list[dict]:
    rows = con.execute(
        f"""SELECT {_VIEW_SELECT} FROM dashboard_views
            WHERE workspace_id = ? AND dataset_id = ? ORDER BY created_at""",
        [workspace_id, dataset_id],
    ).fetchall()
    return [_row_to_view(r) for r in rows]


def create_view(con, workspace_id: str, dataset_id: str, name: str, config,
                make_default: bool = False) -> dict:
    get_dataset(con, workspace_id, dataset_id)  # raises DatasetNotFound (→404) for other tenants
    name = (name or "").strip()
    if not name:
        raise ViewError("a name is required")
    name = name[:MAX_NAME]
    cfg = _validate_config(config)
    view_id = new_id("view")
    con.execute(
        """INSERT INTO dashboard_views (view_id, workspace_id, dataset_id, name, config, is_default)
           VALUES (?, ?, ?, ?, ?, false)""",
        [view_id, workspace_id, dataset_id, name, json.dumps(cfg)],
    )
    if make_default:
        set_default_view(con, workspace_id, view_id)
    return _get_view(con, workspace_id, view_id)


def update_view(con, workspace_id: str, view_id: str, name=None, config=None,
                is_default=None) -> dict:
    view = _get_view(con, workspace_id, view_id)
    new_name = view["name"] if name is None else ((name.strip() or view["name"])[:MAX_NAME])
    new_cfg = view["config"] if config is None else _validate_config(config)
    con.execute(
        """UPDATE dashboard_views SET name = ?, config = ?, updated_at = current_timestamp
           WHERE view_id = ? AND workspace_id = ?""",
        [new_name, json.dumps(new_cfg), view_id, workspace_id],
    )
    if is_default is True:
        set_default_view(con, workspace_id, view_id)
    elif is_default is False:
        con.execute("UPDATE dashboard_views SET is_default = false WHERE view_id = ? AND workspace_id = ?",
                    [view_id, workspace_id])
    return _get_view(con, workspace_id, view_id)


def set_default_view(con, workspace_id: str, view_id: str) -> None:
    """Make one view the default for its dataset (clears any prior default)."""
    view = _get_view(con, workspace_id, view_id)
    con.execute("UPDATE dashboard_views SET is_default = false WHERE workspace_id = ? AND dataset_id = ?",
                [workspace_id, view["dataset_id"]])
    con.execute("UPDATE dashboard_views SET is_default = true WHERE view_id = ? AND workspace_id = ?",
                [view_id, workspace_id])


def delete_view(con, workspace_id: str, view_id: str) -> int:
    n = con.execute(
        "SELECT count(*) FROM dashboard_views WHERE view_id = ? AND workspace_id = ?",
        [view_id, workspace_id],
    ).fetchone()[0]
    con.execute("DELETE FROM dashboard_views WHERE view_id = ? AND workspace_id = ?",
                [view_id, workspace_id])
    return n
