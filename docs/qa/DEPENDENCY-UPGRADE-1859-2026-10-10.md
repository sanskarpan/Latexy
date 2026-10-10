# PR #1859: dependency upgrade compatibility review

## Decision

Keep the dependency maintenance update after repairing the Better Auth 1.7
integration. The original dependency-only head (`d5e01dc3`) is not safe to
merge: its CI [build and browser run](https://github.com/sanskarpan/Latexy/actions/runs/37715392516)
reported the removed `genericOAuthClient` export and failed to render the root
page. Main still resolved Better Auth 1.6.25 before this change, so the update
was not redundant.

The final candidate integrates main `f5bf14a7`, preserving the merged OAuth
handoff retention and account-owned onboarding/settings fixes. The separate
admin draft is not part of this change.

## Better Auth compatibility

- Pin `better-auth` and `@better-auth/passkey` together at 1.7.7.
- Remove the obsolete client plugin and use the standard `signIn.social`
  request for the institutional provider.
- Keep the existing `/api/auth/oauth2/callback/<provider>` redirect URI in
  authorization and token exchange. Normalize only the configured provider's
  legacy callback to the core callback before rate limiting and handling.
  Cookies, query parameters and POST bodies are preserved. No provider-console
  configuration change is required.
- Require discovery verification metadata, preserve an explicit `OIDC_ISSUER`
  pin, reject token responses without an identity token, and retain the
  library's signature/issuer/audience/nonce verification. This additional
  missing-token check matters: 1.7.7's metadata requirement alone still allows
  an access-token/userinfo fallback.
- Preserve redirect-only institutional SSO by requiring the expected nonce
  from server-created OAuth state; do not add client ID-token sign-in.
- Preserve Latexy-only logout; do not newly log users out of their institution.
- Reserve built-in provider IDs to prevent a custom provider from shadowing
  Google, GitHub or password accounts on the shared social-provider path.
- Request and narrow the new two-factor enrollment response to `method: totp`
  before reading the authenticator URI and backup codes.
- Preserve the existing session hydration gate and passkey-to-2FA enforcement.
- Add optional chaining to the accepted tracker generation reads exposed by
  the build's strict-null check; retain owner and generation equality checks.

## Security and migration sources

- [1.7 upgrade guide](https://github.com/better-auth/better-auth/blob/main/docs/content/docs/guides/1-7-upgrade-guide.mdx)
- [1.7.7 release](https://github.com/better-auth/better-auth/releases/tag/v1.7.7)
- [Critical Magic Link advisory](https://github.com/better-auth/better-auth/security/advisories/GHSA-965c-763c-88jm)
- [Account schema correction in 1.7.3](https://better-auth.com/blog/1-7-account-schema)

Latexy does not enable Magic Link or OAuth Proxy, so this review does not claim
that the advisory's exploit configuration was present. The 1.6 maintenance
line was considered but does not contain the published 1.7.7 fix, so it was
not selected and the dependency audit was not weakened.

The core account schema requirement briefly introduced in 1.7.0–1.7.2 was
removed in 1.7.3. This direct upgrade from 1.6.25 to 1.7.7 does not need an
issuer-column migration. Before rollout, follow the upstream duplicate-account
preflight if the database contains legacy duplicate `(providerId, accountId)`
rows. Start a new OAuth flow after upgrading: pending states are version-bound
and should not be expected to survive the security-related storage changes.

## Verification

The new runtime suite uses the installed Better Auth implementation, its memory
adapter, a synthetic OIDC discovery document and locally signed test identity
tokens. It checks the real social-client request and complete callback/token
exchange, existing-account reuse and session creation, bad nonce, missing identity token, direct ID-token rejection, forged state,
issuer mismatch, missing JWKS metadata, reserved provider IDs, and legacy GET
and POST callback normalization. No live identity provider or real account
credentials are used.

Local checks use Node 22.23.3 and pnpm 10.10.0:

- Frozen lockfile installation passed.
- Frontend TypeScript and ESLint passed.
- Full frontend unit suite passed (including the added migration regressions).
- TUI typecheck, build and tests passed: 244 passed, 66 opt-in/live tests skipped.
- Browser extension tests and package validation passed: six tests.
- CI classifier, dependency audit and sharp runtime guards passed: 35 tests.
- Privacy, plaintext-document-credential and marketing-claim guards passed.
- Complete dependency audit passed with zero unresolved findings. The only
  reported advisory is the existing tested `braces` 3.0.3 patch exception.

A first local frontend build compiled successfully but was killed with exit
137 while concurrent verification was running. The serial rerun passed; hosted
build and browser checks for the final published head remain the merge gate.
Production login, live provider linking and opt-in TUI integrations were not
exercised by these local checks.
