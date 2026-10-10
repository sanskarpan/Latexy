# Self-hosting Latexy

Latexy can run on one Docker host with its web application, API, background
workers, PostgreSQL with pgvector, Redis, private MinIO object storage, nginx,
and the bundled observability stack. Runtime secrets remain in an untracked
`.env.production` file.

## Requirements

- A Linux host with Docker Engine and Docker Compose v2
- DNS for the public hostname pointing at the host
- A TLS certificate and private key for that hostname
- At least 4 CPU cores, 8 GB RAM, and persistent disk space
- Outbound access to the configured email, payment, and optional AI providers

The default stack publishes only nginx on ports 80 and 443. Flower, MinIO's
console, Prometheus, Alertmanager, Tempo, and Grafana bind to loopback only;
reach them through an SSH tunnel.

## Configure

From the repository root:

```bash
cp .env.production.example .env.production
```

Replace every placeholder in `.env.production`. In particular:

- Set `NGINX_SERVER_NAME`, `BETTER_AUTH_URL`, `NEXT_PUBLIC_WS_URL`, and every
  `CORS_ORIGINS` entry to the same public deployment hostname.
- Keep `NEXT_PUBLIC_WS_URL` as an absolute `wss://` origin. It is embedded in
  the frontend image at build time.
- Keep `DATABASE_URL` aligned with `POSTGRES_DB`, `POSTGRES_USER`, and
  `POSTGRES_PASSWORD` when using the bundled database.
- Generate independent, high-entropy values for `BETTER_AUTH_SECRET`,
  `JWT_SECRET_KEY`, the database, MinIO, Flower, and Grafana passwords.
- Generate `API_KEY_ENCRYPTION_KEY` as a Fernet key. For example:

  ```bash
  python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
  ```

- Configure `RESEND_API_KEY` and `EMAIL_FROM`; production authentication does
  not silently fall back to logging email links.
- Referrals are disabled by default. To enable the B59 user-referral programme,
  set `REFERRAL_PROGRAM_ENABLED=true` and a reviewed positive
  `REFERRAL_REWARD_DAYS`, then configure
  `REFERRAL_QUALIFYING_PLAN_FAMILIES` as a JSON list. The API enforces the
  account-age window, first-touch attribution, and payment-after-attribution
  checks; no cash or affiliate commission is created. Keep the browser token
  lifetime at or below the server maximum of seven days.

### Google and GitHub sign-in

Set both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the frontend server
runtime to enable Google sign-in; GitHub similarly uses `GITHUB_CLIENT_ID` and
`GITHUB_CLIENT_SECRET`. Keep secrets out of browser bundles and source control.
The forms discover provider availability at runtime; separate
`NEXT_PUBLIC_OAUTH_*` build flags are not required.

Register the exact Google web-client redirect URI
`${BETTER_AUTH_URL}/api/auth/callback/google`. For production Latexy this is
`https://latexy.xyz/api/auth/callback/google`, not `/workspace` (the post-login
destination). Configure the Google consent application's domain and public
audience appropriately before enabling public sign-in. Basic social sign-in
does not require Google Drive scopes or a new hosting platform.

### Institutional SSO and LDAP-backed directories

Latexy accepts one standards-based OpenID Connect provider per deployment. This
covers Keycloak, Authentik, Authelia, Okta, Microsoft Entra ID, Auth0, and other
OIDC-compliant identity providers. For an existing LDAP or Active Directory
directory, connect LDAP to an identity broker such as Keycloak and point Latexy
at the broker; Latexy never receives or stores LDAP passwords.

Set all four required values together (partial configuration stops startup):

```dotenv
OIDC_PROVIDER_ID=university_sso
OIDC_PROVIDER_LABEL=Example University
OIDC_DISCOVERY_URL=https://id.example.edu/realms/example/.well-known/openid-configuration
OIDC_CLIENT_ID=latexy
OIDC_CLIENT_SECRET=replace-with-provider-secret
```

`OIDC_ISSUER` is optional; when set, it must exactly match the discovered issuer.
Discovery must publish its issuer, signing algorithms, and JWKS endpoint so
identity tokens can be verified. Choose a distinct provider ID; `google`,
`github`, and `credential` are reserved. Register this exact callback URL at the
identity provider:

```text
https://your-latexy-host.example/api/auth/oauth2/callback/university_sso
```

Latexy preserves this registered callback URL when upgrading to Better Auth
1.7, translating it internally to the core social callback. Existing providers
do not need a redirect-URI change. Signing out remains local to Latexy and does
not log the user out of their institutional account. Start a new sign-in after
an upgrade; pending OAuth state from the previous version may have expired or
use an older storage format.

Authorization remains separate from authentication: an SSO login creates or
finds the Latexy account, while an email-bound tenant/cohort invitation grants
institution access. Custom tenant domains must pass Latexy's DNS TXT ownership
check and must be listed explicitly in `BETTER_AUTH_TRUSTED_ORIGINS`; wildcard
auth origins are rejected. The TXT check proves control of a hostname but does
not provision it at the edge: separately attach the hostname to the frontend
deployment (for example, as a Vercel project domain), point its DNS record at
that deployment, and provision TLS before enabling it for users.

Install the certificate and key using these exact paths:

```text
nginx/ssl/latexy.crt
nginx/ssl/latexy.key
```

Do not commit `.env.production` or the TLS private key.

## Start and migrate

The guarded startup helper validates the rendered Compose model, builds the
exact application images first, waits for the stateful services, creates the
object-storage bucket, applies all Alembic migrations with that already-built
backend image, and then starts the complete stack without rebuilding. A
migration failure aborts before any new revision application process starts
(an already-running revision is not stopped by the stateful-only preflight):

```bash
make self-host-up
```

To use an environment file at a different path:

```bash
LATEXY_ENV_FILE=/secure/latexy.env bash scripts/self-host-up.sh
```

`make run-prod` remains available for an attached foreground run, but expects
an existing `.env.production` and does not apply migrations itself.

## Verify

```bash
curl -fsS http://localhost/health
curl -fsS https://your-domain.example/health
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 backend celery-worker frontend nginx
```

Then create an account, create and compile a resume, reload the editor, and
open the generated PDF. This exercises authentication, PostgreSQL, Redis,
Celery, the compiler, MinIO, and both HTTP and WebSocket proxy paths.

## Upgrade

Back up PostgreSQL and object storage before upgrading. Pin `LATEXY_VERSION` to
the release tag being deployed, fetch the new repository revision, and rerun:

```bash
make self-host-up
```

The migration step runs before new application services are started. Review
release notes before downgrading; database downgrade compatibility is not
guaranteed.

Database backup and restore helpers live under `scripts/backup/`. Test restores
regularly on a separate host. A complete disaster-recovery plan must also copy
the `minio_data` volume, `.env.production`, and TLS material to encrypted backup
storage.

## Managed services

PostgreSQL, Redis, and S3-compatible storage can be replaced with managed
services through a Compose override. Keep the service environment names used in
`docker-compose.prod.yml`, disable only the replaced containers, and validate
the merged model with `docker compose ... config --quiet` before deployment.
Never expose the backend directly while `TRUST_PROXY_HEADERS=true`; that flag is
safe only behind the bundled nginx (or a proxy that overwrites client-IP
headers).
