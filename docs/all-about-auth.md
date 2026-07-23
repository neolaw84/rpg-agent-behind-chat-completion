# All About Authentication & Authorization in RACHEL

This document serves as the authoritative guide for developers and AI coding agents on the authentication and authorization architectures in **RPG Agent Behind Chat Completion (RACHEL)**.

Because RACHEL operates in two operational modes (**Standalone Single-Tenant** and **Multi-Tenant Cloud Service**) and acts as a middle proxy between chat clients and external LLM providers, there are **three distinct authentication boundaries**. Developers and AI agents must carefully distinguish between them.

---

## High-Level Authentication & Data Flow

```
+------------------------------------+
|   Chat Client (JanitorAI, etc.)   |
+------------------------------------+
                  |
                  | [1] Inbound Chat Auth: Tenant Proxy Key (sk-tenant-...) or Local Proxy Key
                  v
+-------------------------------------------------------------------+
|                         RACHEL Proxy Server                        |
|                                                                   |
|  +------------------------+      +-----------------------------+  |
|  | [2] Admin Panel Auth   |      | Credentials Vault           |  |
|  | (Human Operator / SSO) |      | (AES-256-GCM Encrypted)    |  |
|  +------------------------+      +-----------------------------+  |
+-------------------------------------------------------------------+
                  |
                  | [3] Outbound LLM Auth: Provider API Key / PKCE Token / Provisioned Key
                  v
+-------------------------------------------------------------------+
|               LLM Providers (OpenRouter, OpenAI, etc.)             |
+-------------------------------------------------------------------+
```

---

## 1. Chat Client Authentication (Inbound Access)

**Purpose**: Authenticates third-party chat completion clients (e.g., JanitorAI, SillyTavern, or custom frontends) making HTTP requests to `/v1/chat/completions` or session management endpoints (`/v1/sessions/*`).

Both operational modes utilize a parallel database-backed API key system, validating incoming requests against the `tenant_api_keys` table and resolving the tenant context.

### Standalone Single-Tenant Mode (Local PC)
* **Mechanism**: Local Proxy Keys (prefixed with `sk-local-...`) plus the **Bootstrap Proxy Key** (`RACHEL_PROXY_KEY`).
* **Storage / Resolution**: 
  - The Bootstrap Proxy Key is specified via the `RACHEL_PROXY_KEY` environment variable or auto-generated at startup in `data/proxy.key`.
  - On startup, if the SQLite database is initialized and does not contain this Bootstrap Proxy Key, it is automatically seeded into the `tenant_api_keys` database table for the `local` tenant.
  - The user can generate and revoke additional client-specific keys (prefixed with `sk-local-...`) via the local Admin Console GUI.
* **Client Usage**: Passed in the standard `Authorization` header:
  ```http
  Authorization: Bearer <RACHEL_PROXY_KEY_OR_SK_LOCAL>
  ```
* **Enforcement**: Validated in `src/rachel/auth.py` via the `require_proxy_key` dependency by hashing the incoming key and querying SQLite `tenant_api_keys`.

### Multi-Tenant Cloud Mode (GCP Cloud Run)
* **Mechanism**: **Tenant Proxy Keys** prefixed with `sk-tenant-...`.
* **Management**: Generated, named, and revoked by the human tenant in the Admin Console GUI.
* **Storage**: Hashed (e.g., SHA-256) in the Neon PostgreSQL database table `tenant_api_keys`. Raw keys are shown to the user **once** upon creation.
* **Client Usage**: Passed in the `Authorization` header:
  ```http
  Authorization: Bearer sk-tenant-xxxxxxxxxxxxxx
  ```
* **Request Lifecycle (Universal)**:
  1. Incoming request extracts the bearer token.
  2. Database lookup matches the hashed token in `tenant_api_keys` and resolves the associated `tenant_id` (`local` or cloud tenant UUID).
  3. The proxy key is used in-memory to unwrap the tenant's Data Encryption Key (DEK) to access upstream LLM credentials for that specific request execution.

---

## 2. Admin Panel Authentication (Human / Operator Access)

**Purpose**: Authorizes human users to access the web dashboard (`/`) and administrative control endpoints (provider credential setup, active provider selection, proxy key creation/revocation, session management).

### Standalone Single-Tenant Mode (Local PC)
* **Mechanism**: Local Proxy Key (`RACHEL_PROXY_KEY`).
* **Usage**: On single-tenant local instances, entering the local proxy key into the Admin Console UI grants full administrative access.

### Multi-Tenant Cloud Mode (Cloud Service)
* **Mechanism**: **Stateless OpenID Connect (OIDC) / OAuth2 Single Sign-On (SSO)** via external identity platforms (Clerk, Auth0, Supabase Auth, Firebase Auth, etc.).
* **User Experience**: Non-technical or mobile-first users click "Log In" and authenticate via standard SSO providers (Google, Discord, Email Magic Link, etc.).
* **JWT Validation**:
  * Requests to admin endpoints include the SSO JWT in the `Authorization: Bearer <JWT>` header or session cookie.
  * RACHEL verifies the JWT statelessly using the external auth provider's public JWKS (JSON Web Key Set).
  * The JWT contains the user's subject claim (`sub`) and assigned `tenant_id`.
* **Dual Purpose of the SSO `sub` Claim**:
  1. **Authentication**: Verifies human user identity statelessly.
  2. **Envelope Key Derivation**: The OIDC `sub` claim is **globally unique and immutable** for the life of the user account. RACHEL uses `sub` in HKDF-SHA256 key derivation to reconstruct the Key Encryption Key (KEK) needed to decrypt tenant credentials stored in the database.

### Frontend Build-Time Differentiation & Hardening

To enforce separation of concerns, prevent cloud bypasses, and reduce client bundle sizes, the dashboard code is statically compiled into two separate build targets using environment/compiler flags (such as Vite/Webpack environment flags):

1. **Local Build Target (`dist/local`)**:
   - Compiles only the local key strategy.
   - Strips out all external SSO scripts (e.g., Clerk, Auth0 scripts/widgets) and redirect callback handlers.
   - Restores/renders the local password overlay.
2. **Cloud Build Target (`dist/cloud`)**:
   - Compiles only the SaaS/SSO redirection and widget loading logic.
   - Completely removes the local password input overlays, raw key forms, and local authorization DOM elements.
   - Enforces OIDC JWT validation paths, making it physically impossible for the browser code to display or accept a local key bypass.

At startup, the FastAPI server mounts and serves the static assets corresponding to the `MULTI_TENANT_MODE` config setting.

---

## 3. LLM Provider Authentication (Outbound Upstream Access)

**Purpose**: Authenticates RACHEL requests sent to external LLM provider API endpoints when forwarding chat completions.

### Provider Types & Methods

RACHEL supports multiple active providers and multiple authentication methods for the same provider:

1. **OpenRouter (BYOK Bearer Token)**: Direct user-supplied OpenRouter API key (`sk-or-v1-...`).
2. **OpenRouter (PKCE OAuth)**: Authorizes access via OpenRouter PKCE flow (`/v1/auth/openrouter/authorize`), exchanging authorization codes for access tokens without asking users to copy raw secret keys.
3. **OpenRouter (Resold Token / Managed Provisioning)** *(Cloud Mode only)*: Integrates with OpenRouter Management API to dynamically generate provisioned sub-keys for resold credits and quota management.
4. **OpenAI (BYOK API Key)**: Direct API key (`sk-...`) for `api.openai.com`.
5. **Google Gemini (BYOK API Key)**: Direct API key for `generativelanguage.googleapis.com`.
6. **DeepSeek (BYOK API Key)**: Direct API key for `api.deepseek.com`.

> [!NOTE]
> **Multiple Accounts / Provider Instances**: A single tenant may configure multiple credentials (for example, two separate OpenRouter accounts or both direct keys and provisioned keys). The Admin Console allows selecting one **Active Provider** for completions dispatch.

### Storage & Encryption Architecture (Parallelized)

Both operational modes utilize **AES-256-GCM Envelope Encryption (DEK/KEK)** via HKDF-SHA256 derivation to protect upstream LLM API keys:

* **Standalone Local Mode**: 
  - Credentials set via the Admin Console GUI are stored in the local SQLite database table `tenant_credentials`.
  - The Key Encryption Key (KEK) is derived as:
    $$\text{KEK} = \text{HKDF-SHA256}(\text{RACHEL\_PROXY\_KEY}, \text{salt}=\text{"local"}, \text{info}=\text{"local\_admin"})$$
* **Multi-Tenant Cloud Mode**:
  - Credentials are stored in `tenant_credentials` in Neon PostgreSQL.
  - The KEK is derived using OIDC identity claims:
    $$\text{KEK} = \text{HKDF-SHA256}(\text{MasterSecret}, \text{salt}=\text{tenant\_id}, \text{info}=\text{SSO\_sub})$$
  - **Zero Bulk Exposure**: A database leak combined with `ENCRYPTION_MASTER_KEY` cannot decrypt user API keys without an active user SSO session (`sub`) or a valid incoming tenant proxy key (`sk-tenant-...`).

---

## 4. Authentication Matrix & Summary

| Auth Realm | Initiator & Target | Standalone Local Mechanism | Multi-Tenant Cloud Mechanism | Stored Credential Location |
| :--- | :--- | :--- | :--- | :--- |
| **Inbound Chat Client Auth** | Chat Client $\rightarrow$ RACHEL (`/v1/chat/completions`) | `RACHEL_PROXY_KEY` (auto-seeded) OR Local Proxy Keys (`sk-local-...`) | Tenant Proxy Keys (`sk-tenant-...`) | SHA-256 Hashed in SQLite `tenant_api_keys` (Local) / SHA-256 Hashed in Postgres `tenant_api_keys` (Cloud) |
| **Admin Panel Auth** | Human User $\rightarrow$ Admin Console (`/`) | `RACHEL_PROXY_KEY` check | External SSO JWT (Clerk, Auth0, etc.) | Verified statelessly via JWKS (no DB session table) |
| **Outbound LLM Auth** | RACHEL $\rightarrow$ LLM Providers (OpenRouter, OpenAI, etc.) | BYOK / PKCE / env overrides (`OPENROUTER_API_KEY`) | BYOK / PKCE / Resold Provisioned Keys | Envelope Encrypted in SQLite `tenant_credentials` (Local) / Envelope Encrypted in Postgres `tenant_credentials` (Cloud) |

---

## 5. Developer & Coding Agent Rules

To prevent security vulnerabilities and design confusion:

1. **NEVER Pass LLM Keys from Clients**: Incoming `/v1/chat/completions` requests must use `sk-tenant-...` (or `RACHEL_PROXY_KEY` in local mode) in the `Authorization` header. Do NOT accept raw LLM API keys in custom client headers (e.g. `X-OpenAI-Key`). Central key management belongs in the Admin Console.
2. **NEVER Return LLM Keys to Clients**: Upstream LLM credentials are strictly un-encrypted in memory during request execution and must NEVER be leaked in API responses, error logs, or turn state annotations.
3. **Keep Proxy Auth Separate from LLM Auth**: The token in `Authorization: Bearer ...` received at `/v1/chat/completions` is the **Proxy Access Key**, NOT the OpenRouter / OpenAI API key.
4. **Respect the Single Active Provider**: RACHEL uses an Active Provider setting configured per tenant. When `/v1/chat/completions` is invoked, the proxy forwards model parameters directly to the tenant's selected Active Provider.
5. **Protect Confidentiality in Logs**: Never log raw proxy keys (`sk-tenant-...`), SSO JWT tokens, or decrypted upstream LLM API keys.
