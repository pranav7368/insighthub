"""InsightHub API: auth + workspace-scoped upload / dashboard / ask.

Every data endpoint depends on get_principal, so the workspace_id used in
every query comes from the verified JWT - a tenant can never address
another tenant's data by guessing an id.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from .analytics.engine import DatasetNotFound, compute_dashboard, get_columns, get_dataset
from .analytics.nlquery import QueryError, answer_data_question
from .analytics.correlation import compute_scatter
from .analytics.narrative import generate_narrative
from .analytics.quality import QualityError, apply_cleaning, compute_quality
from .analytics.views import (
    ViewError, ViewNotFound, create_view, delete_view, list_views, update_view,
)
from .analytics.sharing import (
    ShareError, ShareNotFound, create_share, list_shares,
    resolve_share_dashboard_config, revoke_share,
)
from .analytics.alerts import (
    AlertError, AlertNotFound, create_alert, delete_alert, list_alerts,
    run_due_alerts, send_test, set_enabled,
)
from .analytics.semantic import (
    MetricError, create_metric, delete_metric, list_metrics,
)
from .analytics.drivers import DriverError, explain_change
from .analytics.rls import (
    RuleError, RuleNotFound, create_rule, delete_rule, list_rules, secured_relation,
)
from .analytics.privacy import KINDS as PII_KINDS, list_policies, set_policy
from .analytics.joins import (
    JoinError, RelationNotFound, create_join, delete_relation, list_relations,
    rebuild_join, suggest_join_keys,
)
from .qa.llm import provider_status
from .api.deps import Principal, get_principal, require_admin, require_editor
from .members import (
    MemberError, MemberNotFound, change_password, create_member, delete_member,
    list_members, update_member_role,
)
from .billing import BillingError, QuotaError, check_quota, entitlements, set_plan
from . import billing_stripe
from .core import config, db, passwords
from .core import ratelimit
from .core.security import create_access_token, hash_password, new_id, verify_password
from .ingest.append import append_to_dataset, list_batches, rollback_batch
from .ingest.connectors import (
    SourceError, SourceNotFound, create_source, delete_source, due_sources,
    list_sources, sync_source,
)
from .ingest.pipeline import create_structured_dataset, ingest_upload
from .ingest.templates import (
    DEFAULT_TEMPLATE_ID, Template, UnknownTemplate, catalog, get_template,
)
from .core.sqlsafe import safe_identifier, safe_table_name
from .qa.engine import answer_question

app = FastAPI(title="InsightHub API", version="0.1.0")

# CORS: an explicit allow-list of origins in production; a permissive localhost
# regex only when none is configured (local dev).
_cors_origins = [o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins,
                       allow_methods=["*"], allow_headers=["*"])
else:
    app.add_middleware(CORSMiddleware,
                       allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
                       allow_methods=["*"], allow_headers=["*"])

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
}


def _client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def _rate_limit_and_headers(request: Request, call_next):
    path = request.url.path
    if (config.RATE_LIMIT_ENABLED and path.startswith("/api/") and path not in ("/api/health", "/api/ready")):
        category, limit = ratelimit.bucket_for(path, config)
        ok, retry = ratelimit.limiter.check(f"{_client_ip(request)}:{category}", limit, config.RATELIMIT_WINDOW)
        if not ok:
            resp = JSONResponse({"detail": "rate limit exceeded — slow down and retry shortly"},
                                status_code=429, headers={"Retry-After": str(int(retry) + 1)})
            for k, v in _SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            return resp
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def _production_issues() -> list[str]:
    """Config problems that make a production deployment unsafe."""
    issues = []
    if config.ENV == "production":
        if config.SECRET_KEY.startswith("dev-only-insecure"):
            issues.append("IH_SECRET_KEY is still the insecure development default")
        if not config.CORS_ORIGINS.strip():
            issues.append("IH_CORS_ORIGINS is not set — CORS would fall back to permissive localhost")
    return issues


@app.on_event("startup")
def _enforce_secure_config():
    issues = _production_issues()
    if issues:
        raise RuntimeError("refusing to start in production: " + "; ".join(issues))
    if config.SECRET_KEY.startswith("dev-only-insecure"):
        print("[ih][WARNING] IH_SECRET_KEY is the insecure default - set a real secret before any real use.")


# Background auto-refresh for live data sources. Blocking DuckDB/HTTP work runs
# in a worker thread so the event loop is never blocked; each source is synced
# independently and its own errors are recorded (never crash the loop).
def _run_scheduled_work() -> None:
    con = db.connect()
    for source_id, workspace_id in due_sources(con):
        try:
            sync_source(con, workspace_id, source_id)
        except Exception:  # already recorded on the source row
            pass
    try:
        run_due_alerts(con)  # each alert isolates its own errors
    except Exception:
        pass


async def _scheduler_loop() -> None:
    while True:
        await asyncio.sleep(config.SCHEDULER_TICK_SECONDS)
        try:
            await asyncio.to_thread(_run_scheduled_work)
        except Exception as exc:  # never let the loop die
            print(f"[ih][scheduler] {exc}")


@app.on_event("startup")
async def _start_scheduler():
    if config.ENABLE_SCHEDULER:
        asyncio.create_task(_scheduler_loop())


# ----------------------------------------------------------- auth --------

class SignupBody(BaseModel):
    email: EmailStr
    password: str
    workspace_name: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@app.post("/api/auth/signup")
def signup(body: SignupBody):
    try:
        passwords.validate(body.password, email=body.email, workspace_name=body.workspace_name)
    except passwords.WeakPassword as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    con = db.connect()
    exists = con.execute("SELECT 1 FROM users WHERE email = ?", [body.email]).fetchone()
    if exists:
        raise HTTPException(status_code=409, detail="email already registered")
    workspace_id = new_id("ws")
    user_id = new_id("usr")
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)", [workspace_id, body.workspace_name])
    con.execute(
        "INSERT INTO users (user_id, workspace_id, email, password_hash, role) VALUES (?, ?, ?, ?, 'admin')",
        [user_id, workspace_id, body.email, hash_password(body.password)],
    )
    db.audit(con, workspace_id, user_id, "signup", body.email)
    token = create_access_token(user_id, workspace_id, "admin", 0)
    return {"access_token": token, "workspace_id": workspace_id, "role": "admin"}


# Online-guessing defence, per account. The per-IP limiter cannot see an
# attack distributed across many addresses against one mailbox.
MAX_FAILED_LOGINS = 8
LOCKOUT_MINUTES = 15


@app.post("/api/auth/login")
def login(body: LoginBody):
    con = db.connect()
    row = con.execute(
        """SELECT user_id, workspace_id, password_hash, role, token_epoch,
                  failed_logins, locked_until
           FROM users WHERE email = ?""",
        [body.email],
    ).fetchone()

    # One message and one code for every failure below, so the response never
    # reveals whether an address is registered or a account is locked.
    invalid = HTTPException(status_code=401, detail="invalid email or password")
    if row is None:
        raise invalid

    user_id, workspace_id, password_hash, role, epoch, failed, locked_until = row
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if locked_until is not None and locked_until > now:
        raise invalid

    if not verify_password(body.password, password_hash):
        failed = int(failed or 0) + 1
        lock_to = now + timedelta(minutes=LOCKOUT_MINUTES) if failed >= MAX_FAILED_LOGINS else None
        con.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE user_id = ?",
                    [failed, lock_to, user_id])
        if lock_to is not None:
            db.audit(con, workspace_id, user_id, "login_locked", body.email)
        raise invalid

    con.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE user_id = ?", [user_id])
    token = create_access_token(user_id, workspace_id, role, int(epoch or 0))
    return {"access_token": token, "workspace_id": workspace_id, "role": role}


@app.post("/api/auth/revoke-sessions")
def revoke_sessions(principal: Principal = Depends(get_principal)):
    """Sign out everywhere. Invalidates every token issued to this account,
    including the one making the request — the remedy for a laptop left on a
    train, which a self-contained JWT otherwise has no answer for."""
    con = db.connect()
    con.execute(
        "UPDATE users SET token_epoch = COALESCE(token_epoch, 0) + 1 WHERE user_id = ? AND workspace_id = ?",
        [principal.user_id, principal.workspace_id],
    )
    db.audit(con, principal.workspace_id, principal.user_id, "revoke_sessions", principal.user_id)
    return {"ok": True, "detail": "all sessions signed out — sign in again"}


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/auth/change-password")
def auth_change_password(body: ChangePasswordBody, principal: Principal = Depends(get_principal)):
    con = db.connect()
    try:
        result = change_password(con, principal.user_id, body.old_password, body.new_password)
    except MemberError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "change_password", principal.user_id)
    return result


# ---------------------------------------------------- team / members -----

class MemberCreateBody(BaseModel):
    email: EmailStr
    role: str = "viewer"
    password: str | None = None


class MemberRoleBody(BaseModel):
    role: str


@app.get("/api/members")
def members_list(principal: Principal = Depends(require_admin)):
    con = db.connect()
    return list_members(con, principal.workspace_id)


@app.post("/api/members")
def members_add(body: MemberCreateBody, principal: Principal = Depends(require_admin)):
    con = db.connect()
    try:
        check_quota(con, principal.workspace_id, "members")
        result = create_member(con, principal.workspace_id, body.email, body.role, body.password)
    except QuotaError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except MemberError as exc:
        code = 409 if "already registered" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "member_add", f"{body.email} ({body.role})")
    return result


@app.patch("/api/members/{user_id}")
def members_update(user_id: str, body: MemberRoleBody, principal: Principal = Depends(require_admin)):
    con = db.connect()
    try:
        result = update_member_role(con, principal.workspace_id, principal.user_id, user_id, body.role)
    except MemberNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MemberError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "member_role", f"{user_id} -> {body.role}")
    return result


@app.delete("/api/members/{user_id}")
def members_delete(user_id: str, principal: Principal = Depends(require_admin)):
    con = db.connect()
    try:
        result = delete_member(con, principal.workspace_id, principal.user_id, user_id)
    except MemberNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MemberError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "member_remove", user_id)
    return result


# ----------------------------------------------------------- billing -----

class PlanBody(BaseModel):
    plan: str


class CheckoutBody(BaseModel):
    plan: str = "pro"
    success_url: str
    cancel_url: str


@app.get("/api/billing")
def billing_info(principal: Principal = Depends(get_principal)):
    con = db.connect()
    return entitlements(con, principal.workspace_id)


@app.post("/api/billing/plan")
def billing_set_plan(body: PlanBody, principal: Principal = Depends(require_admin)):
    """Set the workspace plan directly (self-hosted / manual). For Stripe-managed
    billing, use checkout + the webhook instead."""
    con = db.connect()
    try:
        sub = set_plan(con, principal.workspace_id, body.plan)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "billing_set_plan", body.plan)
    return sub


@app.post("/api/billing/checkout")
def billing_checkout(body: CheckoutBody, principal: Principal = Depends(require_admin)):
    try:
        result = billing_stripe.create_checkout(
            principal.workspace_id, body.plan, None, body.success_url, body.cancel_url)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    """Stripe -> subscription state. No auth: authenticity comes from the Stripe
    signature (when a webhook secret is configured)."""
    payload = await request.body()
    try:
        event = billing_stripe.parse_event(payload, request.headers.get("stripe-signature"))
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    con = db.connect()
    return billing_stripe.apply_event(con, event)


# ------------------------------------------------------- datasets --------

@app.get("/api/datasets")
def list_datasets(principal: Principal = Depends(get_principal)):
    con = db.connect()
    rows = con.execute(
        """SELECT dataset_id, name, source_file, kind, row_count, char_count, ingested_at
           FROM datasets WHERE workspace_id = ? ORDER BY ingested_at DESC""",
        [principal.workspace_id],
    ).fetchall()
    return [
        {"dataset_id": r[0], "name": r[1], "source_file": r[2], "kind": r[3],
         "row_count": r[4], "char_count": r[5], "ingested_at": str(r[6])}
        for r in rows
    ]


@app.post("/api/datasets/upload")
async def upload(file: UploadFile, principal: Principal = Depends(require_editor)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"unsupported file type {suffix!r}")
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    con = db.connect()
    try:
        check_quota(con, principal.workspace_id, "datasets")
        result = ingest_upload(con, principal.workspace_id, file.filename, content)
    except QuotaError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "upload", file.filename)
    return {
        "dataset_id": result.dataset_id, "name": result.name, "kind": result.kind,
        "row_count": result.row_count, "chunks": result.chunks, "warnings": result.warnings,
        "columns": [{"name": c.name, "role": c.role, "subtype": c.subtype, "distinct_count": c.distinct_count}
                    for c in result.columns],
    }


def _materialize_template(con, principal: Principal, tpl: Template) -> dict:
    """Build a template's dataset, then its certified metrics and default view.

    The dataset is the deliverable; the metrics and the view are presentation
    on top of it. A failure in either of those must not lose the data the user
    just created, so they are best-effort — the dashboard still renders, just
    without the pre-built arrangement.
    """
    try:
        check_quota(con, principal.workspace_id, "datasets")
    except QuotaError as exc:
        raise HTTPException(status_code=402, detail=str(exc))

    result = create_structured_dataset(
        con, principal.workspace_id, tpl.dataset_name, tpl.build(), f"template:{tpl.id}")

    metrics_created = 0
    for m in tpl.metrics:
        try:
            create_metric(con, principal.workspace_id, result.dataset_id,
                          m.name, m.kind, m.definition, m.format)
            metrics_created += 1
        except (MetricError, DatasetNotFound):
            pass          # a metric that does not fit the data is simply skipped
    try:
        create_view(con, principal.workspace_id, result.dataset_id,
                    tpl.view_name, tpl.view_config(), make_default=True)
    except (ViewError, DatasetNotFound):
        pass

    db.audit(con, principal.workspace_id, principal.user_id, "template", f"{tpl.id}:{result.dataset_id}")
    return {"dataset_id": result.dataset_id, "name": result.name, "kind": "structured",
            "row_count": result.row_count, "template_id": tpl.id, "metrics": metrics_created}


@app.get("/api/templates")
def list_templates(principal: Principal = Depends(get_principal)):
    """The industry template catalog shown on the empty-state gallery."""
    return catalog()


class TemplateBody(BaseModel):
    template_id: str = DEFAULT_TEMPLATE_ID


@app.post("/api/datasets/template")
def load_template(body: TemplateBody, principal: Principal = Depends(require_editor)):
    """One click: an industry dataset with its metrics and dashboard arrangement."""
    try:
        tpl = get_template(body.template_id)
    except UnknownTemplate as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _materialize_template(db.connect(), principal, tpl)


@app.post("/api/datasets/sample")
def load_sample(principal: Principal = Depends(require_editor)):
    """One-click sample dataset so a new user immediately sees a full dashboard."""
    return _materialize_template(db.connect(), principal, get_template(DEFAULT_TEMPLATE_ID))


@app.get("/api/datasets/{dataset_id}/export.csv")
def export_csv(dataset_id: str, principal: Principal = Depends(get_principal)):
    """Download the dataset's rows (user columns only) as CSV."""
    con = db.connect()
    try:
        dataset = get_dataset(con, principal.workspace_id, dataset_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    if dataset["kind"] != "structured":
        raise HTTPException(status_code=400, detail="only spreadsheet datasets can be exported")
    cols = [c.name for c in get_columns(con, principal.workspace_id, dataset_id)]
    allowed = set(cols)
    tq, rls_params = secured_relation(con, principal.workspace_id, principal.user_id, dataset)
    select = ", ".join(safe_identifier(c, allowed) for c in cols)
    csv_text = con.execute(f"SELECT {select} FROM {tq}", list(rls_params)).df().to_csv(index=False)
    safe_name = "".join(ch for ch in (dataset["name"] or "dataset") if ch.isalnum() or ch in " -_")[:60].strip() or "dataset"
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )


@app.post("/api/datasets/{dataset_id}/append")
async def append_data(dataset_id: str, file: UploadFile, mode: str = Form("append"),
                      principal: Principal = Depends(require_editor)):
    """Add a new file (e.g. next month's report) into an existing dataset.
    mode = 'append' | 'replace_period'."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"unsupported file type {suffix!r}")
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    con = db.connect()
    try:
        result = append_to_dataset(con, principal.workspace_id, dataset_id, file.filename, content, mode)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "append", f"{file.filename} ({mode})")
    return result


@app.get("/api/datasets/{dataset_id}/batches")
def dataset_batches(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_batches(con, principal.workspace_id, dataset_id)


class RollbackBody(BaseModel):
    batch_id: str


@app.post("/api/datasets/{dataset_id}/rollback")
def rollback_data(dataset_id: str, body: RollbackBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        result = rollback_batch(con, principal.workspace_id, dataset_id, body.batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "rollback", body.batch_id)
    return result


# ------------------------------------------------- live data sources -----

class SourceBody(BaseModel):
    name: str
    kind: str = "url_csv"
    url: str
    refresh_interval_minutes: int = 0


@app.get("/api/sources")
def get_sources(principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_sources(con, principal.workspace_id)


@app.post("/api/sources")
def add_source(body: SourceBody, principal: Principal = Depends(require_editor)):
    """Create a live source and run its first sync. If the URL is malformed the
    request fails; if the first fetch fails, the source is still created with an
    error status so it can be fixed and re-synced."""
    con = db.connect()
    try:
        check_quota(con, principal.workspace_id, "datasets")  # first sync creates a dataset
        source = create_source(con, principal.workspace_id, body.name, body.kind,
                                body.url, body.refresh_interval_minutes)
    except QuotaError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "source_create", f"{body.kind}:{body.name}")
    try:
        result = sync_source(con, principal.workspace_id, source["source_id"])
    except (SourceError, ValueError) as exc:
        return {"source": list_sources(con, principal.workspace_id)[0], "sync": {"status": "error", "error": str(exc)}}
    return {"source": source, "sync": result}


@app.post("/api/sources/{source_id}/sync")
def resync_source(source_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        result = sync_source(con, principal.workspace_id, source_id)
    except SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (SourceError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "source_sync", source_id)
    return result


@app.delete("/api/sources/{source_id}")
def remove_source(source_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    n = delete_source(con, principal.workspace_id, source_id)
    if not n:
        raise HTTPException(status_code=404, detail="source not found")
    db.audit(con, principal.workspace_id, principal.user_id, "source_delete", source_id)
    return {"ok": True}


# ---------------------------------------------- saved dashboard views ----

class ViewCreateBody(BaseModel):
    name: str
    config: dict = {}
    make_default: bool = False


class ViewUpdateBody(BaseModel):
    name: str | None = None
    config: dict | None = None
    is_default: bool | None = None


@app.get("/api/datasets/{dataset_id}/views")
def get_views(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_views(con, principal.workspace_id, dataset_id)


@app.post("/api/datasets/{dataset_id}/views")
def add_view(dataset_id: str, body: ViewCreateBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        view = create_view(con, principal.workspace_id, dataset_id, body.name, body.config, body.make_default)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except ViewError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "view_create", body.name)
    return view


@app.patch("/api/views/{view_id}")
def edit_view(view_id: str, body: ViewUpdateBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        view = update_view(con, principal.workspace_id, view_id, body.name, body.config, body.is_default)
    except ViewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ViewError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return view


@app.delete("/api/views/{view_id}")
def remove_view(view_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    n = delete_view(con, principal.workspace_id, view_id)
    if not n:
        raise HTTPException(status_code=404, detail="view not found")
    db.audit(con, principal.workspace_id, principal.user_id, "view_delete", view_id)
    return {"ok": True}


# ------------------------------------------------ public share links -----

class ShareCreateBody(BaseModel):
    view_id: str | None = None
    label: str | None = None
    expires_in_days: int | None = None


@app.post("/api/datasets/{dataset_id}/shares")
def add_share(dataset_id: str, body: ShareCreateBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        share = create_share(con, principal.workspace_id, dataset_id, body.view_id,
                             body.label, body.expires_in_days, principal.user_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except ViewNotFound:
        raise HTTPException(status_code=404, detail="view not found")
    except ShareError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "share_create", dataset_id)
    return share


@app.get("/api/datasets/{dataset_id}/shares")
def get_shares(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_shares(con, principal.workspace_id, dataset_id)


@app.delete("/api/shares/{token}")
def revoke_share_endpoint(token: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    n = revoke_share(con, principal.workspace_id, token)
    if not n:
        raise HTTPException(status_code=404, detail="share link not found")
    db.audit(con, principal.workspace_id, principal.user_id, "share_revoke", token)
    return {"ok": True}


@app.get("/api/public/{token}/dashboard")
def public_dashboard(token: str):
    """Unauthenticated, read-only: the dashboard behind a valid share token.
    The token is the only credential; it names exactly one dataset."""
    con = db.connect()
    try:
        workspace_id, dataset_id, cfg, author_id = resolve_share_dashboard_config(con, token)
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="this link is invalid or has expired")
    try:
        dash = compute_dashboard(
            con, workspace_id, dataset_id,
            filters=(cfg.get("filters") or None),
            date_from=cfg.get("date_from"), date_to=cfg.get("date_to"),
            breakdown_measure=cfg.get("measure"),
            user_id=author_id,          # a link shows only what its author could see
        )
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="this dashboard is no longer available")
    return {"dashboard": dash, "meta": {
        "hidden_sections": cfg.get("hidden_sections", []),
        "section_order": cfg.get("section_order", []),
    }}


# ------------------------------------------------- threshold alerts ------

class AlertCreateBody(BaseModel):
    name: str
    measure: str
    aggregate: str
    op: str
    threshold: float
    webhook_url: str


@app.get("/api/datasets/{dataset_id}/alerts")
def get_alerts(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_alerts(con, principal.workspace_id, dataset_id)


@app.post("/api/datasets/{dataset_id}/alerts")
def add_alert(dataset_id: str, body: AlertCreateBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        check_quota(con, principal.workspace_id, "alerts")
        alert = create_alert(con, principal.workspace_id, dataset_id, body.name, body.measure,
                             body.aggregate, body.op, body.threshold, body.webhook_url,
                             created_by=principal.user_id)
    except QuotaError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except AlertError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "alert_create", body.name)
    return alert


class AlertPatchBody(BaseModel):
    enabled: bool


@app.patch("/api/alerts/{alert_id}")
def toggle_alert(alert_id: str, body: AlertPatchBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        return set_enabled(con, principal.workspace_id, alert_id, body.enabled)
    except AlertNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/alerts/{alert_id}/test")
def test_alert(alert_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        return send_test(con, principal.workspace_id, alert_id)
    except AlertNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AlertError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/alerts/{alert_id}")
def remove_alert(alert_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    n = delete_alert(con, principal.workspace_id, alert_id)
    if not n:
        raise HTTPException(status_code=404, detail="alert not found")
    db.audit(con, principal.workspace_id, principal.user_id, "alert_delete", alert_id)
    return {"ok": True}


# ------------------------------------------------ multi-table joins ------

class JoinCreateBody(BaseModel):
    left_dataset_id: str
    right_dataset_id: str
    left_key: str
    right_key: str
    join_type: str = "left"
    name: str | None = None


@app.get("/api/joins/suggest")
def joins_suggest(request: Request, principal: Principal = Depends(get_principal)):
    left = request.query_params.get("left")
    right = request.query_params.get("right")
    if not left or not right:
        raise HTTPException(status_code=400, detail="left and right dataset ids are required")
    con = db.connect()
    try:
        return suggest_join_keys(con, principal.workspace_id, left, right)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")


@app.get("/api/joins")
def joins_list(principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_relations(con, principal.workspace_id)


@app.post("/api/joins")
def joins_create(body: JoinCreateBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        check_quota(con, principal.workspace_id, "datasets")  # a join creates a dataset
        result = create_join(con, principal.workspace_id, body.left_dataset_id, body.right_dataset_id,
                            body.left_key, body.right_key, body.join_type, body.name)
    except QuotaError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except JoinError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "join_create", result["name"])
    return result


@app.post("/api/joins/{relation_id}/rebuild")
def joins_rebuild(relation_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        result = rebuild_join(con, principal.workspace_id, relation_id)
    except RelationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (JoinError, DatasetNotFound) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "join_rebuild", relation_id)
    return result


@app.delete("/api/joins/{relation_id}")
def joins_delete(relation_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    n = delete_relation(con, principal.workspace_id, relation_id)
    if not n:
        raise HTTPException(status_code=404, detail="join not found")
    db.audit(con, principal.workspace_id, principal.user_id, "join_delete", relation_id)
    return {"ok": True}


@app.get("/api/datasets/{dataset_id}/explain")
def explain(dataset_id: str, request: Request, principal: Principal = Depends(get_principal)):
    """Root-cause / driver analysis: why the measure changed period-over-period."""
    con = db.connect()
    try:
        return explain_change(
            con, principal.workspace_id, dataset_id,
            measure=request.query_params.get("measure"),
            dimension=request.query_params.get("dimension"),
            user_id=principal.user_id,
        )
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except DriverError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------- certified metrics ---------

class MetricCreateBody(BaseModel):
    name: str
    kind: str = "aggregate"
    definition: dict
    format: str | None = None


@app.get("/api/datasets/{dataset_id}/metrics")
def get_metrics(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    return list_metrics(con, principal.workspace_id, dataset_id, with_values=True,
                        user_id=principal.user_id)


@app.post("/api/datasets/{dataset_id}/metrics")
def add_metric(dataset_id: str, body: MetricCreateBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        metric = create_metric(con, principal.workspace_id, dataset_id, body.name,
                               body.kind, body.definition, body.format)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except MetricError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "metric_create", body.name)
    # return the metric with its computed value + SQL
    return list_metrics(con, principal.workspace_id, dataset_id, with_values=True,
                        user_id=principal.user_id)


@app.delete("/api/metrics/{metric_id}")
def remove_metric(metric_id: str, principal: Principal = Depends(require_editor)):
    con = db.connect()
    n = delete_metric(con, principal.workspace_id, metric_id)
    if not n:
        raise HTTPException(status_code=404, detail="metric not found")
    db.audit(con, principal.workspace_id, principal.user_id, "metric_delete", metric_id)
    return {"ok": True}


# ------------------------------------------------ row-level security -----

class RuleBody(BaseModel):
    user_id: str
    column_name: str
    values: list[str]
    operator: str = "in"


@app.get("/api/datasets/{dataset_id}/rls")
def get_rls_rules(dataset_id: str, principal: Principal = Depends(require_admin)):
    """Who is restricted to which rows on this dataset. Admin-only: the rules
    are the access-control policy, so reading them is itself privileged."""
    return list_rules(db.connect(), principal.workspace_id, dataset_id)


@app.post("/api/datasets/{dataset_id}/rls")
def add_rls_rule(dataset_id: str, body: RuleBody, principal: Principal = Depends(require_admin)):
    con = db.connect()
    try:
        rule = create_rule(con, principal.workspace_id, dataset_id, body.user_id,
                           body.column_name, body.values, body.operator)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "rls_create",
             f"{body.user_id}:{body.column_name}")
    return rule


@app.delete("/api/rls/{rule_id}")
def remove_rls_rule(rule_id: str, principal: Principal = Depends(require_admin)):
    con = db.connect()
    if not delete_rule(con, principal.workspace_id, rule_id):
        raise HTTPException(status_code=404, detail="rule not found")
    db.audit(con, principal.workspace_id, principal.user_id, "rls_delete", rule_id)
    return {"ok": True}


# --------------------------------------------------------- PII policy ----

class PolicyBody(BaseModel):
    column_name: str
    masked: bool
    pii_kind: str | None = None


@app.get("/api/datasets/{dataset_id}/privacy")
def get_privacy(dataset_id: str, principal: Principal = Depends(require_admin)):
    """Which columns are treated as PII and whether they are masked. Admin-only
    — this is the list of what is sensitive about the data."""
    con = db.connect()
    try:
        get_dataset(con, principal.workspace_id, dataset_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    return list_policies(con, principal.workspace_id, dataset_id)


@app.patch("/api/datasets/{dataset_id}/privacy")
def set_privacy(dataset_id: str, body: PolicyBody, principal: Principal = Depends(require_admin)):
    """Turn masking on or off for one column. The underlying values are never
    rewritten, so this is reversible at any time."""
    con = db.connect()
    try:
        get_dataset(con, principal.workspace_id, dataset_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    known = {c.name for c in get_columns(con, principal.workspace_id, dataset_id)}
    if body.column_name not in known:
        raise HTTPException(status_code=400, detail=f"unknown column {body.column_name!r}")
    if body.pii_kind is not None and body.pii_kind not in PII_KINDS:
        raise HTTPException(status_code=400, detail="invalid pii kind")
    set_policy(con, principal.workspace_id, dataset_id, body.column_name,
               body.pii_kind, body.masked)
    db.audit(con, principal.workspace_id, principal.user_id,
             "privacy_mask" if body.masked else "privacy_unmask", body.column_name)
    return list_policies(con, principal.workspace_id, dataset_id)


@app.get("/api/datasets/{dataset_id}/schema")
def schema(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    cols = get_columns(con, principal.workspace_id, dataset_id)
    if not cols:
        raise HTTPException(status_code=404, detail="dataset not found")
    return [{"name": c.name, "role": c.role, "subtype": c.subtype, "distinct_count": c.distinct_count} for c in cols]


class OverrideBody(BaseModel):
    role: str
    subtype: str | None = None


@app.patch("/api/datasets/{dataset_id}/schema/{column_name}")
def override(dataset_id: str, column_name: str, body: OverrideBody, principal: Principal = Depends(require_editor)):
    if body.role not in ("measure", "dimension", "date", "ignored"):
        raise HTTPException(status_code=400, detail="invalid role")
    con = db.connect()
    n = con.execute(
        "SELECT count(*) FROM dataset_columns WHERE dataset_id = ? AND workspace_id = ? AND column_name = ?",
        [dataset_id, principal.workspace_id, column_name],
    ).fetchone()[0]
    if n == 0:
        raise HTTPException(status_code=404, detail="column not found")
    con.execute(
        """UPDATE dataset_columns SET role = ?, subtype = ?, overridden = true
           WHERE dataset_id = ? AND workspace_id = ? AND column_name = ?""",
        [body.role, body.subtype, dataset_id, principal.workspace_id, column_name],
    )
    return {"ok": True}


# ------------------------------------------------------ dashboard --------

_RESERVED_QUERY_KEYS = {"date_from", "date_to", "measure"}


@app.get("/api/datasets/{dataset_id}/dashboard")
def dashboard(dataset_id: str, request: Request, principal: Principal = Depends(get_principal)):
    query = dict(request.query_params)
    filters = {k: v for k, v in query.items() if k not in _RESERVED_QUERY_KEYS}
    con = db.connect()
    try:
        return compute_dashboard(
            con, principal.workspace_id, dataset_id,
            filters=filters or None,
            date_from=query.get("date_from"), date_to=query.get("date_to"),
            breakdown_measure=query.get("measure"),
            user_id=principal.user_id,
        )
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")


# ------------------------------------------------------------ ask --------

class AskBody(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: AskBody, principal: Principal = Depends(get_principal)):
    con = db.connect()
    answer = answer_question(con, principal.workspace_id, body.question)
    db.audit(con, principal.workspace_id, principal.user_id, "ask", body.question[:200])
    return answer.as_dict()


@app.get("/api/datasets/{dataset_id}/scatter")
def scatter(dataset_id: str, request: Request, principal: Principal = Depends(get_principal)):
    query = dict(request.query_params)
    x, y = query.pop("x", None), query.pop("y", None)
    date_from, date_to = query.pop("date_from", None), query.pop("date_to", None)
    if not x or not y:
        raise HTTPException(status_code=400, detail="x and y query params are required")
    con = db.connect()
    try:
        return compute_scatter(con, principal.workspace_id, dataset_id, x, y,
                               filters=query or None, date_from=date_from, date_to=date_to,
                               user_id=principal.user_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/datasets/{dataset_id}/quality")
def data_quality(dataset_id: str, principal: Principal = Depends(get_principal)):
    con = db.connect()
    try:
        return compute_quality(con, principal.workspace_id, dataset_id, principal.user_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")


class CleanBody(BaseModel):
    action: str
    column: str | None = None


@app.post("/api/datasets/{dataset_id}/clean")
def clean_data(dataset_id: str, body: CleanBody, principal: Principal = Depends(require_editor)):
    con = db.connect()
    try:
        result = apply_cleaning(con, principal.workspace_id, dataset_id, body.action, body.column)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except QualityError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "clean", f"{body.action} {body.column or ''}")
    return result


class DataQueryBody(BaseModel):
    question: str


@app.post("/api/datasets/{dataset_id}/query")
def query_data(dataset_id: str, body: DataQueryBody, principal: Principal = Depends(get_principal)):
    """Conversational analytics: a natural-language question is turned into a
    validated query and answered from the real data (grounded, no invented
    numbers)."""
    con = db.connect()
    try:
        result = answer_data_question(con, principal.workspace_id, dataset_id, body.question,
                                      user_id=principal.user_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.audit(con, principal.workspace_id, principal.user_id, "query", body.question[:200])
    return result


@app.post("/api/datasets/{dataset_id}/narrative")
def narrative(dataset_id: str, principal: Principal = Depends(get_principal)):
    """AI executive narrative + suggested actions, grounded in the computed
    facts. Uses whichever LLM provider is configured (or the offline fallback)."""
    con = db.connect()
    try:
        result = generate_narrative(con, principal.workspace_id, dataset_id)
    except DatasetNotFound:
        raise HTTPException(status_code=404, detail="dataset not found")
    db.audit(con, principal.workspace_id, principal.user_id, "narrative", dataset_id)
    return result


@app.get("/api/llm")
def llm_info(principal: Principal = Depends(get_principal)):
    """Which LLM provider/model is active (no secrets)."""
    return provider_status()


@app.get("/api/health")
def health():
    """Liveness — the process is up (no dependencies checked)."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness — the database is reachable. Use this for load-balancer /
    orchestrator readiness probes; returns 503 if the DB can't be queried."""
    try:
        db.connect().execute("SELECT 1")
    except Exception:
        raise HTTPException(status_code=503, detail="database not ready")
    return {"status": "ready", "backend": "postgres" if config.DATABASE_URL else "duckdb"}
