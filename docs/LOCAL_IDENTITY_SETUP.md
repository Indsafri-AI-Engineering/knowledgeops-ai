# Local Keycloak identity setup

This configures real OIDC authentication for local development. It is not a
production identity deployment. Use only generated test users and synthetic
documents. The imported realm has no seeded users or passwords.

## Windows prerequisite

Docker Desktop's Linux engine requires WSL 2 and hardware virtualization.
Open PowerShell as Administrator and enable the Windows features if they are
not already enabled:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

Restart Windows. If `wsl --status` still reports that virtualization is
disabled, enable Intel VT-x or AMD SVM in the computer's UEFI/BIOS settings.
Then run `wsl --update` and `wsl --set-default-version 2`. Before continuing,
verify that `wsl --status` reports WSL 2 available and `docker info` shows a
Server section; the Docker CLI alone is not enough.

## 1. Start Keycloak

From the repository root, set throwaway bootstrap credentials in the
PowerShell process and start the local container:

```powershell
$env:KEYCLOAK_ADMIN = "local-admin"
$env:KEYCLOAK_ADMIN_PASSWORD = Read-Host "Enter a throwaway local Keycloak admin password"
docker compose up -d keycloak
```

Open `http://localhost:8080`, sign in to the Keycloak administration console,
and select the imported `knowledgeops` realm. Create a generated test user,
set a local test password, and assign exactly one appropriate group under
`/knowledge`; the groups are the source of authorization. Use
`/knowledge/manager` to test document uploads without granting
system-administrator access. Create a separate test account in
`/knowledge/security` to test threat scans; its capability mapping is
`threat_scans:scan`. Update the local `OIDC_GROUP_CAPABILITIES` mapping from
`.env.example` if the group does not yet include
`security_alerts:read` and `security_alerts:manage`.

## 2. Configure the API

In the backend PowerShell terminal:

```powershell
$env:APP_ENV = "development"
$env:OIDC_ISSUER_URL = "http://localhost:8080/realms/knowledgeops"
$env:OIDC_AUDIENCE = "knowledgeops-api"
$env:OIDC_GROUPS_CLAIM = "groups"
$env:OIDC_GROUP_CAPABILITIES = Get-Content .env.example | Where-Object { $_ -like "OIDC_GROUP_CAPABILITIES=*" } | ForEach-Object { $_.Substring("OIDC_GROUP_CAPABILITIES=".Length) }
python -m uvicorn backend.app.main:app --reload
```

The API obtains signing keys from the local realm's OIDC JWKS endpoint. To
override discovery, configure `OIDC_JWKS_URL`. The API validates RS256
signature, issuer, audience, expiry, and required token claims. It converts
only explicitly configured, allowlisted group capabilities to backend
permissions; no UI-supplied permissions are trusted.

The Jira Cloud integration uses separate backend service-account
configuration (`JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`). OIDC user
capabilities still control access in the app; the Jira service account should
be restricted to the minimum approved projects and actions.

## 3. Configure the frontend

In `frontend`, copy `.env.example` to `.env.local` and run:

```powershell
Copy-Item .env.example .env.local
npm run dev
```

The SPA uses the OIDC authorization-code flow with PKCE and stores OIDC state
in browser session storage. The imported `knowledgeops-web` client allows the
common local Vite ports 5173 and 5174 on both `localhost` and `127.0.0.1`.
The API uses bearer access tokens. During local development, Vite forwards
same-origin `/api` requests to `http://localhost:8000`, avoiding browser
cross-origin restrictions. Leave `VITE_API_BASE_URL` empty for this setup;
set it to an absolute API origin only when the frontend is served separately
without a development proxy.

## Sign-in troubleshooting

Verify the API at `http://localhost:8000/api/v1/health` and the provider
discovery document at
`http://localhost:8080/realms/knowledgeops/.well-known/openid-configuration`.
Both should respond successfully.

If sign-in returns HTTP 400, open browser Developer Tools → Network and inspect
the failing request's URL and response body. A 400 from Keycloak's
`/protocol/openid-connect/token` endpoint means the authorization-code exchange
was rejected; check that the browser uses the same host consistently
(`localhost` versus `127.0.0.1`), the client ID is `knowledgeops-web`, and
the exact callback (for example `http://localhost:5174/`) is allowed under
**Valid Redirect URIs**. If the realm was imported before adding port 5174,
update the existing client in Keycloak Admin Console → `knowledgeops` realm
→ Clients → `knowledgeops-web` → Settings; editing the import JSON alone
does not update an already imported client. Also confirm the browser session
storage still contains the OIDC flow state. Do not share authorization
codes, state values, access tokens, or request headers.

If `GET /api/v1/me` returns 401, verify the browser's Authorization header is
present without copying or sharing its bearer-token value. An API request ID
appears in the error message and can be used to correlate backend logs.

## 4. Verify the authorization boundary

1. Sign in with the manager test user; `/api/v1/me` should show
   `knowledge:manage` but not `system:admin`.
2. Upload a synthetic PDF, DOCX, TXT, Markdown, HTML, XLSX, or PPTX document
   and verify it appears in the stored-documents list.
3. Sign in as `/knowledge/employee`; verify the upload panel is hidden and
   upload/list API calls return `403`.
4. Sign out and call an authenticated API without a bearer token; it should
   return `401`.
5. Set an invalid issuer, audience, group mapping, or token and verify that
   authentication fails closed.

The local API must be reachable at `http://localhost:8000`; the browser and
API must resolve the same issuer URL used in the token's `iss` claim.
Development HTTP is restricted to this local setup. Production needs
TLS, approved identity ownership, a formal permission policy, secret
management, and security review before use.
