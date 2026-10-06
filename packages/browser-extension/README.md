# Latexy Job Companion

A least-privilege Manifest V3 extension for explicitly initiated job workflows.

- **Capture:** reads schema.org `JobPosting` data first, then visible page fields,
  and opens an authenticated Latexy tracker review form with company, role,
  location, description, and URL.
- **Autofill:** fills supported, empty identity/contact fields only after a click.
  It never fills file inputs, overwrites an existing value, or submits a form.
- **Privacy:** the optional autofill profile remains in extension-local storage.
  Job captures expire after 15 minutes and are deleted after the Latexy page
  acknowledges import. No reusable Latexy credential enters the extension.
- **Permissions:** `activeTab`, `scripting`, and `storage`; there is no
  `<all_urls>` host grant. Persistent content-script access is restricted to the
  production app and documented local-development origins solely for the
  one-time capture handoff.

For local use, open `chrome://extensions`, enable Developer mode, choose **Load
unpacked**, and select this directory. Choose the localhost app origin in the
extension settings when testing against `pnpm --dir frontend dev`.

Run `pnpm --filter @latexy/browser-extension test` and
`pnpm --filter @latexy/browser-extension check` from the repository root.
