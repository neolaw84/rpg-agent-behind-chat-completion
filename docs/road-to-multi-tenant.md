# Road to Multi-Tenant Cloud Deployment

This document outlines the architectural roadmap, design decisions, and implementation plan for enabling **RPG Agent Behind Chat Completion (RACHEL)** to support **multi-tenant cloud service provision** (hosted on **Google Cloud Run** with **Neon PostgreSQL**) for mobile-first, non-technical users alongside its existing **standalone single-tenant execution** on local PCs.

---

## 1. Executive Summary & Core Objectives

RACHEL supports **dual operational modes** to cater to different user profiles:
1. **Multi-Tenant Cloud Service Mode**: Built for **mobile-first, non-technical users** who do not have a PC or cannot run Python applications locally. Enables them to use the proxy via a managed cloud service with simple GUI key management (or resold tokens) and browser-based Admin Console auth.
2. **Standalone Single-Tenant Mode**: Self-hosted local run for users running RACHEL directly on their personal PCs.

### Primary Objectives:
1. **Admin Console Key Management & OAuth PKCE**: Replace mandatory environment variable setups (`OPENROUTER_API_KEY`) with an in-dashboard Admin Console GUI. Support OpenRouter OAuth PKCE authentication alongside direct API keys (BYOK) for OpenAI, Google Gemini, and DeepSeek in both local and multi-tenant modes.
2. **Multi-Tenant Service Provisioning**: In multi-tenant cloud mode, support three key management models:
   - **OpenRouter OAuth PKCE**
   - **Bring Your Own Key (BYOK)** for OpenAI, Google Gemini, DeepSeek, or OpenRouter Bearer Tokens
   - **Resold Tokens / Managed Access** via OpenRouter Provisioned Key Generation
3. **Flexible Storage & Infrastructure**: Enable RACHEL to seamlessly switch between local storage (`file` / local SQLite) for single-tenant desktop use and **Neon PostgreSQL** for multi-tenant **GCP Cloud Run** deployments.

---

## 2. System Architecture & Component Design

### 2.1 Dual-Mode Operation & Tenant Authentication Model

RACHEL supports two runtime operational modes determined by configuration (`MULTI_TENANT_MODE=true|false`):

#### Mode Comparison Matrix

| Feature | Standalone Single-Tenant Mode (Local PC) | Multi-Tenant Cloud Mode (GCP Cloud Run + Neon) |
| :--- | :--- | :--- |
| **Primary Audience** | Tech-savvy users running locally on personal PCs | **Mobile-first non-tech users** (no PC / can't run Python) & service providers |
| **Admin Auth** | Local Proxy Key (`RACHEL_PROXY_KEY`) | Stateless JWT Validation via external Auth provider (Clerk, Auth0, etc.) |
| **API Auth (`/v1/chat/completions`)** | DB-backed Client Keys (Auto-seeded with bootstrap `RACHEL_PROXY_KEY`, plus custom keys) | Tenant Proxy Keys (`sk-tenant-...`) managed in Admin Console |
| **State Storage Engine** | SQLite (using unified relational schema layout) | **Neon PostgreSQL** indexed by `tenant_id` |
| **Credentials Vault** | Envelope encrypted in SQLite (derived KEK via `RACHEL_PROXY_KEY`) | AES-256-GCM envelope encrypted in Neon DB (derived KEK via OIDC `sub` + `MasterSecret`) |

In **Multi-Tenant Cloud Mode**, client account lifecycle (user sign-up, user profiles, identity management) is handled outside this repository by an external Auth platform (e.g., Clerk, Auth0, Supabase Auth, Firebase Auth).

---

### 2.2 LLM Credentials Vault & Active Provider Selection

The Admin Console GUI key management and Active Provider selection apply universally to **both Local Standalone Mode and Multi-Tenant Cloud Mode**.

#### A. Universal Active Provider Selection (KISS Principle)
Users select **one Active Provider** in their Admin Console GUI from the available options:
1. **OpenRouter (BYOK Bearer Token)**
2. **OpenRouter (PKCE OAuth)**
3. **OpenRouter (Resold Token / Managed Provisioned Key)** *(Cloud Mode only)*
4. **OpenAI (BYOK API Key)**
5. **Google Gemini (BYOK API Key)**
6. **DeepSeek (BYOK API Key)**

When `/v1/chat/completions` is invoked, RACHEL forwards the incoming `model` parameter directly to the user's selected **Active Provider**.

#### B. Storage & Envelope Encryption Model (Parallelized)
To keep codebase implementation clean and uniform, both modes utilize **AES-256-GCM Envelope Encryption (DEK/KEK)** with key derivation via **HKDF-SHA256**:

- **Local Standalone Mode**:
  $$\text{KEK} = \text{HKDF-SHA256}(\text{RACHEL\_PROXY\_KEY}, \text{salt}=\text{"local"}, \text{info}=\text{"local\_admin"})$$
  - **Admin Console Access**: The user enters their `RACHEL_PROXY_KEY` to authenticate the dashboard, which is then used to construct the KEK and decrypt the Data Encryption Key (DEK).
  - **API Execution**: Incoming requests using `RACHEL_PROXY_KEY` or custom keys unwrap the DEK in-memory.

- **Multi-Tenant Cloud Mode (Tenant-Derived Envelope Encryption)**:
  To prevent service provider admins or DB leaks from exposing raw user keys in bulk, credentials in Neon PostgreSQL are encrypted using:
  $$\text{KEK} = \text{HKDF-SHA256}(\text{MasterSecret}, \text{salt}=\text{tenant\_id}, \text{info}=\text{SSO\_sub})$$
  - **Immutable Identity Guarantee**: In OpenID Connect (OIDC / OAuth2 with Google, Facebook, Discord, etc.), the `sub` (subject) claim is **globally unique and immutable** for a user account forever. Therefore, **decryption remains 100% valid across log-offs, log-ins, session expirations, and device switches**.
  - **Admin Console Access**: When a user logs in from any browser or device, RACHEL validates their SSO JWT, reconstructs the KEK from `(MasterSecret + tenant_id + SSO_sub)`, and unwraps the tenant's Data Encryption Key (DEK).
  - **API Execution (`/v1/chat/completions`)**: Incoming `sk-tenant-...` Tenant Proxy Keys securely unwrap the DEK in memory for that request cycle.
  - **Zero-Bulk-Exposure Guarantee**: A database dump alone, even if combined with the server's `ENCRYPTION_MASTER_KEY`, cannot decrypt tenant credentials without active user JWT tokens or valid tenant proxy keys.

---

### 2.3 OpenRouter PKCE OAuth Integration

OpenRouter PKCE (Proof Key for Code Exchange) enables users to authorize RACHEL to access OpenRouter without exposing or manually copying raw API keys.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant AdminUI as Admin Console GUI
    participant RABCC as RACHEL Server
    participant OR as OpenRouter OAuth

    User->>AdminUI: Click "Connect OpenRouter (PKCE)"
    AdminUI->>AdminUI: Generate code_verifier & code_challenge
    AdminUI->>OR: Redirect to OpenRouter auth URL with code_challenge
    User->>OR: Approve access
    OR-->>RABCC: Redirect to /v1/auth/openrouter/callback?code=...
    RABCC->>OR: Exchange authorization code + code_verifier
    OR-->>RABCC: Return API Key / Auth Token
    RABCC->>RABCC: Encrypt API key (AES-256-GCM) & save to Neon DB for Tenant
    RABCC-->>User: Redirect back to Admin Console with Success Status
```

---

### 2.4 Resold Token / Managed Provisioning Model

For tenants utilizing resold tokens provided by the platform operator:
- RACHEL integrates with **OpenRouter's Management API** to provision individual, restricted API keys per tenant.
- Credit limits, usage quotas, and rate limits are offloaded directly to OpenRouter's platform infrastructure.
- Admin Console displays current provisioned key quota and usage status.

---

### 2.5 Unified SQL Schema & Denormalized LRU Turn Performance

RACHEL implements a **Unified Relational SQL Strategy** across both **Local Standalone Mode (SQLite)** and **Multi-Tenant Cloud Mode (Neon PostgreSQL)** using an identical database schema. In Local Mode, `tenant_id` is fixed to `'local'`.

#### Core Data Entities:
- `tenants`: Primary tenant record linked to external `external_user_id` / `sub` (or `'local'`).
- `tenant_api_keys`: Hashed proxy keys (`sk-tenant-...`) issued to third-party clients (JanitorAI, SillyTavern, etc.).
- `tenant_credentials`: Encrypted LLM provider API keys and PKCE tokens per tenant.
- `tenant_settings`: Active provider selection, default model overrides, and reasoning payload format options.
- `sessions`: RPG session metadata and turn history stored as a denormalized JSON blob (`turns_data` dictionary `{ "<turn_key>": { "before": ..., "after": ... } }`), scoped by `(tenant_id, session_id)`.

Schema migrations are managed **manually** via SQL scripts or Neon SQL Console.

#### LRU Eviction Performance Mitigation Strategy

By storing `turns_data` as a denormalized JSON blob directly inside the `sessions` table (matching the structure of `FileSessionStorage`), RACHEL **completely eliminates SQL sorting operations and subquery deletion overhead**:

| Mitigation Aspect | Standalone Mode (SQLite) & Multi-Tenant Mode (Neon PostgreSQL) |
| :--- | :--- |
| **1. Zero-Sort In-Memory LRU Eviction** | LRU trimming occurs **100% in Python memory** (`dict` / `OrderedDict` key popping when `len > num_states_to_track`) before writing to the database. Eliminates `ORDER BY accessed_at`, CTEs, and `DELETE` queries. |
| **2. Single-Query Network RTT** | Every turn update is a single SQL `UPSERT` (1 network round-trip in Neon Postgres), maximizing serverless response speeds. |
| **3. Minimal Index Maintenance** | Only the primary key index on `(tenant_id, session_id)` is maintained, avoiding multi-column index overhead on secondary tables. |
| **4. Direct Compatibility with `FileSessionStorage`** | 1-to-1 data structure match with existing `.json` files, simplifying data import/export between local disk and cloud databases. |

---

### 2.6 Build-Time & Packaging-Time Differentiation

To optimize bundle sizes, protect cloud environments from local auth bypasses, and prevent dependency bloat in the local PC package, RACHEL employs build-time and packaging-time separation:

#### A. Frontend (Client-Side JS/HTML)
* **Strategy**: The client-side dashboard code is compiled into two distinct builds using environment flags (e.g., `import.meta.env.VITE_MULTI_TENANT`) and compiler dead-code elimination:
  * **Local Build (`dist/local`)**: Strips out external OIDC/SSO widgets, script tags (e.g., Clerk/Auth0), and redirection callback code. Renders the local password prompt overlay.
  * **Cloud Build (`dist/cloud`)**: Strips out the local password inputs, overlays, and manual token-saving UI elements. Enforces OIDC/SSO login and redirection paths.
* **Server-Side Mounting**: The FastAPI server mount path serves the static folder matching the runtime operational mode:
  ```python
  if settings.MULTI_TENANT_MODE:
      app.mount("/", StaticFiles(directory="dist/cloud", html=True))
  else:
      app.mount("/", StaticFiles(directory="dist/local", html=True))
  ```

#### B. Backend (Python/FastAPI)
* **Dependency Extras (`pyproject.toml`)**: Heavy cloud-specific packages (such as `asyncpg`, `pyjwt`, and `google-cloud-secret-manager`) are placed in optional dependency groups (e.g. `[project.optional-dependencies] cloud`).
  * **Local Package Build**: Built via `pip install .` to exclude cloud dependencies and minimize the desktop application `.zip` footprint.
  * **Cloud Container Build**: Built via `pip install .[cloud]` inside the production Dockerfile to include database drivers and SSO cryptographic tools.
* **Conditional Backend Imports**: To prevent runtime import failures in local mode where cloud packages are missing, modules for Postgres connections or SSO signature checks are dynamically imported behind runtime `if settings.MULTI_TENANT_MODE:` gates.

---

## 3. Brainstorming & Discarded Ideas Log

During architectural design, several alternatives were evaluated and intentionally discarded:

| Evaluated Concept | Status | Reason for Discarding |
| :--- | :--- | :--- |
| **Header Pass-Through for BYOK** (`X-OpenAI-Key`) | ❌ **Discarded** | Forces end-users to input raw LLM keys into third-party clients (e.g. JanitorAI) on every request, defeating Admin Console central key management. |
| **Strict Model-Prefix Routing** (`openai/gpt-4o`, `gemini/gemini-2.5-flash`) | ❌ **Discarded** | Overcomplicates model parameters and breaks standard client presets. Replaced by the simpler **Active Provider Toggle** (KISS principle). |
| **Custom In-House Token Metering Ledger** | ❌ **Discarded** | Calculating token costs and managing atomic USD balance deductions in DB adds significant complexity and race conditions. Replaced by **OpenRouter Provisioned Key Generation** which delegates quota enforcement directly to OpenRouter. |
| **PostgreSQL Row-Level Security (RLS)** | ❌ **Discarded** | Adds session variable configuration overhead per connection in serverless pooled environments (PgBouncer/Cloud Run). `tenant_id` indexed queries provide equivalent isolation with lower latency. |
| **Schema-per-Tenant DB Provisioning** | ❌ **Discarded** | High DDL maintenance overhead and slow schema migrations across hundreds of tenant schemas in Neon PostgreSQL. |
| **Automated Startup DB Migrations** | ❌ **Discarded** | Running migrations on container startup in Cloud Run creates race conditions when multiple container instances scale out simultaneously. Manual schema management selected instead. |

---

## 4. Phased Implementation Plan

### Phase 1: Multi-Provider LLM Dispatcher & Active Provider GUI (Universal Core)
- [x] **Multi-Provider Client Layer**: Extend LLM invocation in `src/rachel/agent/` to support direct API calls for OpenAI (`api.openai.com`), Google Gemini (`generativelanguage.googleapis.com`), and DeepSeek (`api.deepseek.com`) alongside OpenRouter.
- [x] **Active Provider Config**: Implement the **Active Provider Selection** configuration model in `src/rachel/config.py`.
- [x] **OpenRouter PKCE OAuth Flow**: Implement `/v1/auth/openrouter/authorize` (PKCE challenge generation) and `/v1/auth/openrouter/callback` token exchange in `src/rachel/routes/system.py`.
- [x] **Admin Console UI Update**: Update `src/rachel/templates/index.html` with a **Provider Credentials** configuration card and an **Active Provider Selector** toggle.

### Phase 2: Unified SQL Storage Engine (SQLite Local + Neon PostgreSQL)
- [x] **Unified Database Layer (`src/rachel/core/db.py`)**: Define SQLAlchemy/SQLModel models for `tenants`, `tenant_api_keys`, `tenant_credentials`, `tenant_settings`, and `sessions` (including `turns_data` JSON blob).
- [x] **Unified Relational Storage Strategy (`RelationalSessionStorage`)**: Refactor `BaseSessionStorage` in `src/rachel/core/state.py` to use `RelationalSessionStorage`. Connects to `sqlite:///data/rpg_agent.sqlite3` in Local Standalone Mode (`tenant_id = 'local'`) and Neon PostgreSQL in Multi-Tenant Cloud Mode.
- [x] **In-Memory Python LRU Eviction**: Implement Python `dict` key popping (`len > num_states_to_track`) before SQL `UPSERT` execution.
- [x] **Bootstrap Key Auto-Seeding (Local Mode)**: Auto-seed the SQLite `tenant_api_keys` table on database initialization with `RACHEL_PROXY_KEY` as a default client key for the `local` tenant.

### Phase 3: Multi-Tenant Identity, Universal Key Management & Envelope Encryption (Backend Security & Auth Core)
- [x] **Client Proxy Key Management (Universal)**: Add API endpoints in `src/rachel/routes/system.py` to generate, list, and revoke database-backed client proxy keys (with prefix `sk-local-...` in Local Mode and `sk-tenant-...` in Cloud Mode).
- [x] **Proxy Key Validation (Universal)**: Update the `require_proxy_key` authentication dependency in `src/rachel/auth.py` and `completions.py` to validate keys against the `tenant_api_keys` table and bind the resolved `tenant_id` (`local` or cloud tenant UUID) to the request context.
- [x] **Envelope Encryption (Universal)**: Implement HKDF-SHA256 key derivation. For cloud mode, derive KEK using `(MasterSecret + tenant_id + SSO_sub)`. For local mode, derive KEK using `(RACHEL_PROXY_KEY + "local" + "local_admin")`. Use the derived KEK to wrap/unwrap the Data Encryption Key (DEK) in memory.
- [x] **Stateless JWT SSO Auth Middleware**: Add JWKS-based JWT validation dependency in `src/rachel/auth.py` for Admin Console routes when `MULTI_TENANT_MODE=true`.

### Phase 4: Frontend Modular Refactoring & Dual-Build Pipeline (`dist/local` vs `dist/cloud`)
- [ ] **Frontend Modular Refactoring**: Refactor SPA dashboard in `src/rachel/templates/index.html` / frontend modules into structured component files.
- [ ] **Frontend Dual-Build Pipeline**: Implement frontend build bundler pipeline (e.g. Vite / compiler flags) to compile two distinct output targets:
  - `dist/local`: Single-tenant desktop dashboard (strips OIDC/SSO widgets and cloud auth redirects; renders local password/key prompts).
  - `dist/cloud`: Multi-tenant cloud dashboard (enforces OIDC/SSO login widgets and cloud authentication flow).
- [ ] **FastAPI Mount Alignment**: Update static file mounting in `src/rachel/proxy.py` to serve static files from `dist/cloud` when `MULTI_TENANT_MODE=true` and `dist/local` when `MULTI_TENANT_MODE=false`.

### Phase 5: Desktop Packaging, CI Release & GCP Cloud Run Deployment
- [ ] **Portable Python Bundling (`python-build-standalone`)**: Set up build scripts to bundle self-contained, isolated Python runtimes for Windows (`x86_64`), macOS (`aarch64`/`x86_64`), and Linux (`x86_64`), bundling `dist/local` static assets into release packages.
- [ ] **OS-Specific One-Click Launchers**: Create background launcher scripts/wrappers:
  - **Windows**: Silent `.vbs` launcher (`launch.vbs`) to start Uvicorn without a CMD prompt box and open default browser.
  - **macOS**: Shell launcher (`launch.command`) with double-click execution support.
  - **Linux**: Desktop entry (`rpg-agent.desktop`) and `launch.sh`.
- [ ] **Automated Multi-OS GitHub Release Workflow**: Create a GitHub Actions CI workflow to build and attach `rpg-agent-vX.X.X-{win,mac,linux}.zip` release artifacts on tag push.
- [ ] **Single-Tenant Desktop Documentation**: Document local double-click installation and macOS Gatekeeper bypass instructions in `README.md`.
- [ ] **OpenRouter Provisioned Key Client**: Implement OpenRouter Management API integration to request provisioned keys for tenants selecting "OpenRouter (Resold Token)" mode.
- [ ] **GCP Cloud Run Production Hardening**: Add GCP Secret Manager environment variable injection documentation (`DATABASE_URL`, `ENCRYPTION_MASTER_KEY`).
- [ ] **Dockerfile Optimization**: Optimize `Dockerfile` for Cloud Run (multi-stage build, non-root user, bundling `dist/cloud`).
- [ ] **Manual Database Migration Scripts**: Write `schema_v1.sql` for initial Neon PostgreSQL database provisioning.

---

*Document finalized based on design alignment.*
