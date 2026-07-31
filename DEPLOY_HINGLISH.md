# InsightHub — Deployment Guide (Hinglish)

Ye guide batati hai ki **kaun si file kahan hai** aur **project ko deploy kaise
karna hai** — step by step, detail mein. English technical terms rakhe hain
taaki commands exactly waise hi kaam karein.

---

## 1. Ye project hai kya (2 line mein)

Upload koi bhi company data (CSV/Excel/PDF) → seedha ek **trustworthy dashboard
+ AI analyst** milta hai. Har number **data se compute hota hai** (AI invent
nahi karta). Do hisse hain:

- **Backend** — FastAPI (Python), data + analytics + API. DuckDB ya Postgres pe
  chalta hai.
- **Frontend** — React + Vite, jo backend ke API se baat karta hai.

Deploy ke **3 tareeke** hain (aage detail mein): **Docker** (sabse easy),
**Local dev**, aur **Production server**.

---

## 2. Poora file structure — kahan kya hai

```
InsightHub/
├── README.md                    # main documentation (English)
├── DEPLOY_HINGLISH.md           # <-- ye file (deployment guide)
├── docker-compose.yml           # poora stack ek command mein (db+backend+frontend)
├── .env.example                 # saari environment variables ka template
├── run.sh / run.ps1             # local dev mein dono servers start karne ke liye
│
├── backend/                     # === BACKEND (Python / FastAPI) ===
│   ├── Dockerfile               # backend ka docker image banane ke liye
│   ├── .dockerignore
│   ├── requirements.txt         # python dependencies (pip install ke liye)
│   ├── app/
│   │   ├── main.py              # FastAPI app + saare API endpoints yahin
│   │   ├── core/               # neeche wale core modules
│   │   │   ├── config.py        # SAARI settings/env variables yahan read hoti hain
│   │   │   ├── db.py            # database connection (DuckDB ya Postgres) + schema
│   │   │   ├── security.py      # password hashing (bcrypt) + JWT tokens
│   │   │   ├── sqlsafe.py       # SQL-injection defense (identifier whitelist)
│   │   │   ├── nettrust.py      # SSRF guard (bahar ke URL fetch karne pe safety)
│   │   │   └── ratelimit.py     # per-IP rate limiting
│   │   ├── api/deps.py          # JWT -> workspace (tenant isolation) + roles
│   │   ├── analytics/          # dashboard + insights ka dimaag
│   │   │   ├── engine.py        # KPIs, breakdowns, trends (SQL)
│   │   │   ├── detect.py        # column ko measure/dimension/date detect karna
│   │   │   ├── intelligence.py  # forecast, anomaly, growth, pareto
│   │   │   ├── correlation.py   # correlation + scatter
│   │   │   ├── quality.py       # data quality + cleaning
│   │   │   ├── nlquery.py       # natural language -> safe SQL (Ask feature)
│   │   │   ├── narrative.py     # AI executive summary (number gate ke saath)
│   │   │   ├── views.py         # saved dashboard views
│   │   │   ├── sharing.py       # public share links
│   │   │   ├── alerts.py        # threshold alerts (webhook)
│   │   │   ├── semantic.py      # certified metrics (show-the-SQL)
│   │   │   ├── drivers.py       # "What changed" root-cause analysis
│   │   │   ├── rls.py           # row-level security (kis member ko kaun si rows)
│   │   │   └── privacy.py       # PII detect + masking (email/phone chhupana)
│   │   ├── ingest/             # data andar laane ka kaam
│   │   │   ├── pipeline.py      # upload -> parse -> table banana
│   │   │   ├── parsers.py       # csv/xlsx/pdf/docx padhna
│   │   │   ├── append.py        # monthly/incremental data add karna
│   │   │   ├── templates.py     # industry templates (retail/saas/ecom/logistics/health)
│   │   │   └── connectors.py    # live source (URL / Google Sheet) sync
│   │   ├── qa/                  # document Q&A (PDF/Word pe)
│   │   │   ├── llm.py           # multi-provider LLM (Claude/OpenAI/Gemini/Ollama)
│   │   │   ├── engine.py        # cited answers + abstention
│   │   │   └── gates.py         # grounding gates
│   │   ├── billing.py           # plans + quota (plan gating)
│   │   ├── billing_stripe.py    # Stripe checkout + webhook
│   │   └── members.py           # team members + roles (admin/editor/viewer)
│   ├── tests/                   # 426 tests (pytest)
│   └── scripts/                 # sample data generator
│
└── frontend/                    # === FRONTEND (React / Vite) ===
    ├── Dockerfile               # frontend image (vite build -> nginx)
    ├── .dockerignore
    ├── nginx.conf               # nginx: static serve + /api ko backend pe proxy
    ├── package.json             # node dependencies
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── App.jsx              # main app (header, tabs, modals)
        ├── main.jsx             # entry point + /share/<token> public route
        ├── api.js               # backend API calls (axios) — yahan API base URL
        ├── theme.css, App.css   # styling + design tokens
        └── components/          # saare UI components (dashboard, dialogs, charts)
```

**Yaad rakhne wali important files:**
- `backend/app/core/config.py` → yahan saari env settings define hain.
- `backend/app/main.py` → saare API endpoints.
- `frontend/src/api.js` → frontend backend se kaise baat karta hai.
- `docker-compose.yml` + `.env.example` → deployment ka control panel.

---

## 3. Deploy karne ke 3 tareeke

### A) Docker se — SABSE EASY (recommended) ✅

Iske liye sirf **Docker Desktop** installed hona chahiye. Ek command mein poora
stack (Postgres + backend + frontend) chal jaata hai.

```bash
# InsightHub folder ke andar se:
docker compose up --build
```

Fir browser mein kholo: **http://localhost:8080**

Kya-kya hota hai iske andar:
- **db** — Postgres 16 (data yahin store hota hai, `pgdata` volume mein — restart
  pe data safe rehta hai).
- **backend** — FastAPI, Postgres se connect (connection pooling ON).
- **frontend** — nginx jo React app serve karta hai aur `/api` ko backend pe
  proxy karta hai (isliye sab **single origin** pe — CORS ka jhanjhat nahi).

Useful commands:
```bash
docker compose up -d --build     # background mein chalao
docker compose logs -f backend   # backend ke logs dekho
docker compose ps                # kaun se container chal rahe hain
docker compose down              # sab band karo (data volume safe rehta hai)
docker compose down -v           # sab band + DATA BHI DELETE (dhyan se!)
```

**AI on karna (optional):** by default offline mode mein chalta hai (deterministic,
bina key). Real AI ke liye `docker-compose.yml` ke `backend` service ke
`environment` mein add karo (ya `.env` se pass karo):
```
IH_OFFLINE: "0"
IH_LLM_PROVIDER: anthropic          # ya openai / gemini / ollama
ANTHROPIC_API_KEY: sk-ant-...        # apni key
```

**Verify karo sab theek hai:**
```bash
curl http://localhost:8080/api/ready     # {"status":"ready","backend":"postgres"}
curl http://localhost:8080/api/health    # {"status":"ok"}
```

---

### B) Local development — bina Docker (code change karte waqt best)

**Prerequisites:** Python 3.11+, Node 18+.

```bash
# 1) Backend setup
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 2) Frontend setup
cd ../frontend
npm install

# 3) Config (optional — chhod do to fully offline chalega)
cd ..
cp .env.example .env              # fir .env edit karke IH_SECRET_KEY set karo

# 4) Dono servers ek saath start karo (repo root se)
./run.sh                          # Windows PowerShell: ./run.ps1
```

- Frontend: **http://localhost:5173**
- Backend: **http://localhost:8010**

Sign up karo, ek CSV/Excel upload karo → dashboard khud ban jaata hai.

**Note:** local dev mein by default **DuckDB file** use hota hai
(`backend/data/insighthub.duckdb`) — koi Postgres setup nahi chahiye. Agar
Postgres pe test karna hai to `.env` mein `IH_DATABASE_URL` set kar do.

Backend ko akele run karna ho:
```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --port 8010 --reload
```
(`--reload` = code change pe auto-restart. Dev mein zaroor use karo.)

Tests chalane ke liye:
```bash
cd backend
IH_OFFLINE=1 .venv/Scripts/python -m pytest -q      # 426 tests
```

---

### C) Production deploy — real server pe (internet pe live)

Docker wala tareeka hi base hai, bas **kuch cheezein zaroor set karni hain**:

**1. Secret key (MANDATORY):**
```bash
# ek strong random secret banao:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Ise `IH_SECRET_KEY` mein daalo. Aur `IH_ENV=production` set karo — agar secret
default rahega ya CORS set nahi hoga to app **start hi nahi hogi** (safety).

**2. CORS lock karo:** `IH_CORS_ORIGINS=https://apka-domain.com` (apna real
frontend URL).

**3. HTTPS:** InsightHub khud HTTPS terminate nahi karta. Aage ek reverse proxy
(Nginx / Caddy / Traefik) lagao jo:
- port 443 pe HTTPS handle kare,
- traffic ko frontend container (:8080) pe bheje,
- `IH_TRUST_PROXY=1` set ho (taaki rate-limiting sahi client IP dekhe).

**4. Postgres backup:** data `pgdata` docker volume mein hai. Regular backup lo:
```bash
docker exec insighthub-db-1 pg_dump -U insighthub insighthub > backup.sql
```

**5. LLM provider** (agar AI chahiye): provider + API key env mein set karo (upar
"AI on karna" dekho).

**Production ke liye ek example `.env`:**
```
IH_ENV=production
IH_SECRET_KEY=<48-char random secret>
IH_CORS_ORIGINS=https://apka-domain.com
IH_DATABASE_URL=postgresql://insighthub:STRONG_PASS@db:5432/insighthub
IH_TRUST_PROXY=1
IH_DB_POOL=1
IH_OFFLINE=0
IH_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```
Fir: `docker compose up -d --build`

> Bade scale ke liye: ek connection pool already hai (`IH_DB_POOL`). Aage chal ke
> uploaded files ke liye object storage (S3) aur ek dedicated job queue add kiya
> ja sakta hai.

---

## 4. Environment variables — poori list

Sab optional hain except jahan likha hai. Details `.env.example` mein bhi hain.

| Variable | Kaam | Default |
|----------|------|---------|
| `IH_SECRET_KEY` | JWT sign karne ka secret. **Production mein MANDATORY.** | dev-only (warn karta hai) |
| `IH_ENV` | `production` set karne pe insecure config pe app start nahi hoti | development |
| `IH_DATABASE_URL` | Postgres URL. Set nahi to DuckDB file use hota hai | (empty = DuckDB) |
| `IH_DB_POOL` | Connection pooling on/off | 1 (on) |
| `IH_CORS_ORIGINS` | Allowed frontend origins (comma separated) | (empty = localhost) |
| `IH_TRUST_PROXY` | Reverse proxy ke peeche ho to X-Forwarded-For trust karo | off |
| `IH_OFFLINE` | 1 = bina LLM, deterministic fallback | (set in docker) |
| `IH_LLM_PROVIDER` | anthropic / openai / gemini / ollama / groq / ... | (auto) |
| `IH_MODEL` | provider ka model id override | (per-provider default) |
| `ANTHROPIC_API_KEY` etc. | provider ki API key | — |
| `IH_RATELIMIT_AUTH` / `_LLM` / `_DEFAULT` | per-IP rate limits (60s window) | 15 / 40 / 400 |
| `IH_ALLOW_PRIVATE_FETCH` | internal URLs se sync allow (SSRF guard off) | off |
| `IH_ENABLE_SCHEDULER` | live-source auto-refresh + alerts scheduler | on |
| `IH_BILLING_ENABLED` | plan gating (free/pro limits) on karo | off |
| `IH_STRIPE_SECRET_KEY` / `_WEBHOOK_SECRET` / `_PRICE_PRO` | Stripe billing | — |
| `IH_MAX_UPLOAD_BYTES` | upload size cap | 50 MB |
| `IH_JWT_TTL_MINUTES` | login session ki lifetime | 720 (12h) |

---

## 5. Common problems / troubleshooting

**"docker compose up" ke baad :8080 nahi khul raha**
- `docker compose ps` chalao — sab container "running/healthy" hone chahiye.
- `docker compose logs backend` dekho error ke liye.
- Docker Desktop ka **engine on hai** ye confirm karo (`docker ps` chalke).

**Backend restart kiya par naye features/routes 404 de rahe (local dev)**
- `run.sh`/`run.ps1` uvicorn ko **bina `--reload`** start karte hain, isliye code
  change pe purana code chalta rehta hai. Backend manually `--reload` ke saath
  chalao: `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8010 --reload`

**Frontend chal raha par API calls fail (local dev)**
- Backend :8010 pe on hai kya check karo. `frontend/src/api.js` by default
  `http://localhost:8010/api` use karta hai. Docker mein `/api` (nginx proxy).

**Postgres se connect nahi ho raha**
- Docker mein backend `db:5432` (service name) use karta hai, host ka port nahi.
- Password/DB name `docker-compose.yml` ke `db` service se match hone chahiye.

**Rate limit / 429 error aa raha**
- Normal use mein nahi aana chahiye. Limits `IH_RATELIMIT_*` se badha sakte ho.

**Data delete ho gaya restart pe**
- `docker compose down -v` mat chalao (`-v` volume delete karta hai). Sirf
  `docker compose down` karo — `pgdata` volume safe rehta hai.

---

## 6. Deploy verify karne ki quick checklist

```bash
# 1. containers healthy hain?
docker compose ps

# 2. DB reachable hai? (postgres backend confirm)
curl http://localhost:8080/api/ready      # -> {"status":"ready","backend":"postgres"}

# 3. process zinda hai?
curl http://localhost:8080/api/health     # -> {"status":"ok"}

# 4. frontend load ho raha?
# browser mein: http://localhost:8080  -> login page dikhe

# 5. end-to-end: sign up -> CSV upload -> dashboard bane
```

Sab tick? To deployment **live aur healthy** hai. 🎉

---

*Sawaal ho ya koi step atak jaaye to bata dena — main us specific part ko aur
detail mein samjha dunga.*
