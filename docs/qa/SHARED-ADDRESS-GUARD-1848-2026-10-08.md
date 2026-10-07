# Public URL guard — shared-address regression

[Issue #1848](https://github.com/sanskarpan/Latexy/issues/1848) tracks a verified
public-only network admission defect, not a demonstrated production exploit.
No internal address, production importer, paid provider or customer record was
accessed during this test.

## Reproduction and repair

On main `0d628cba`, `_ip_is_public` accepted `100.64.0.0/10`, including an
IPv4-mapped IPv6 representation. The existing negative flags do not cover that
range: [Python's address classification documentation](https://docs.python.org/3.12/library/ipaddress.html#ipaddress.IPv4Address.is_global)
explicitly distinguishes shared addresses from globally reachable addresses.
The shared scraper/portfolio importer therefore admitted them at preflight and
DNS-pinned transport boundaries.

The new focused regressions first produced **9 failures / 3 passes** on the
unchanged implementation. They exercise address classification, mixed DNS
answers, a direct transport request and a redirect through the actual default
URL-import client. DNS and the inner HTTP transport are mocked; the failing
redirect received a synthetic body, not a real private response.

The repair adds a positive `is_global` requirement and retains every existing
private, loopback, link-local, reserved, multicast and unspecified exclusion.
It does not change DNS pinning, TLS SNI, Host headers, per-host pools, public
redirects, timeouts, quotas, caching or extraction.

## Verification boundary

- Scraper and URL-import suites: **116 passed, 0 skipped/errors/failures**.
- Includes public IPv4/IPv6 controls and existing multicast/private denials.
- Ruff on both changed files and Git whitespace checks passed.
- Actual isolated PostgreSQL on port 5547 and Redis on port 6397, databases
  9/8; infrastructure checks were not skipped. Paid-provider keys were blank.
- JUnit: `/private/tmp/latexy-main-shared-address-20261008.xml`, SHA-256
  `ca6d7d8005b855d87c9303662bbeff6377d9efd31f24480fe2ddd053bce641e2`.
- The run predates the publication-only rebase onto homepage checkpoint
  `d80afa55`; the backend implementation and test bytes are unchanged.

No full-suite, Linux CI, actual upstream connection, production rollout or
network-policy certificate is inferred from these focused mocked tests.
Protected PR checks and post-merge readiness remain separate release gates.
