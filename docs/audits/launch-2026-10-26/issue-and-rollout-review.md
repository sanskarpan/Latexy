# Issue and rollout review — October 26, 2026

Source reviewed: [`aa48fa10`](https://github.com/sanskarpan/Latexy/commit/aa48fa101861bb48f373355c31f0745e7c4c67b9).
[Canonical main CI 40208097584](https://github.com/sanskarpan/Latexy/actions/runs/40208097584)
passed. This is a dated observation, not production acceptance of that source.

## Production and checklist

- The observed main Modal App remains deployed at v87. A fresh read-only fleet
  sample found four containers and zero reported running inputs/backlog on the
  registered functions. The App was live: **this is not a drain certificate**,
  a Redis queue inventory, or proof of all serving container source identities.
- A narrowly scoped diagnostic using the existing main backend/primary Redis
  secret bindings found queue and cache on the same primary endpoint. Its
  read-only PING returned the provider's request-limit failure. No Redis keys,
  credentials, connection strings or customer documents are included here.
  A later isolated PING succeeded, but an ordinary read-only `EXISTS` on a unique
  operator probe key still returned the provider's request-limit failure, and
  the running backend remained degraded/not ready. PING success is not capacity
  or work-settlement evidence; the quota problem remains open.
- Candidate-source billing preflight, with the existing main API bindings,
  completed its read-only database report: revision `0059`, known mainline
  pre-Dodo schema, zero historical paid pointers/live mandates/team owners,
  zero existing Dodo intent users, and zero suspect legacy billing rows. Billing
  is disabled. The report status is blocked by disabled billing and the schema
  upgrade requirement; this report is **not** successful rollout acceptance.
- Fresh recovery-build availability, work settlement/change freeze, post-freeze
  recovery point, migration, held serving-SHA verification and production E2E
  remain open. No approval marker was filled merely to bypass these checks.
- The checklist's checked inventory/CI/isolated-restore claims remain scoped to
  their dated evidence. The production restore, runtime release and paid launch
  gates remain unchecked. LatexyBackup was not changed by this review.

Recovery review found general-download and anonymous-share raw-cache acceptance
gaps shared by the candidate and proposed older recovery source. This change
repairs those readers and adds minimum source rejection checks. New anonymous
jobs carry document/revision identity; public anonymous PDFs require an accepted
terminal manifest bound to the current redacted source. Legacy or expired
anonymous artifacts without this proof require owner regeneration, with a
redacted text alternative remaining available. Passing the source checks does
not certify every reader, establish an available recovery image or authorize a
migration.

Anonymous dispatch now commits a derived `anonymous_share` finalization row and
the owner's share pointer before initializing the compiler lifecycle and calling
the broker. It does not insert a redacted `Compilation` into ordinary history.
An uncertain broker outcome retains the durable identity; only a proven
undispatched job may be terminalized and retried. Regeneration also checks the
compilation capability. Local validation passed 100 targeted cases using a
separate PostgreSQL database migrated through `0075` and a dedicated Redis
container, including the real public reader and manifest-only finalization.
Twenty dependency-free cutover gate tests passed. These checks do not establish
production Redis capacity or production deployment acceptance.

## Completed issues closed with evidence

Each linked closure comment includes the full commit ID, merged PR and acceptance
scope. No closure asserts that the latest backend was deployed.

| Issue | Merged implementation evidence | Closure record |
|---|---|---|
| #1801 scoped CI | #1803 `fc8d947b`; #1839 `5e42d42f`; scoped canonical CI | [comment](https://github.com/sanskarpan/Latexy/issues/1801#issuecomment-6415550179) |
| #1846 credential/URL handling | #1834 `fb68ae06`; #1929 `6470eb03`; targeted regressions and CodeQL review | [comment](https://github.com/sanskarpan/Latexy/issues/1846#issuecomment-6415763471) |
| #1843 quota credential scope | #1833 `c24531e2`; #1844 `0d628cba`; key/rotation/quota regressions | [comment](https://github.com/sanskarpan/Latexy/issues/1843#issuecomment-6415764855) |
| #1841 PDF import validation | #1833 `c24531e2`; bounded/encrypted/owner import regressions | [comment](https://github.com/sanskarpan/Latexy/issues/1841#issuecomment-6415766351) |
| #1772 React hydration repair | #1975 `9b9713e2`; #1983 `eeeecc8a`; production-renderer reproducer and current browser CI | [comment](https://github.com/sanskarpan/Latexy/issues/1772#issuecomment-6415767936) |
| #1817 semantic revisions/import identity | #1833 `c24531e2`; semantic/DB/CAS/import regressions | [comment](https://github.com/sanskarpan/Latexy/issues/1817#issuecomment-6415770571) |
| #1818 paid-stage ledger/lifecycle | #1833 `c24531e2`; reservation/fence/replay/refund regressions | [comment](https://github.com/sanskarpan/Latexy/issues/1818#issuecomment-6415771837) |

Issue #1815 was initially closed with the merged implementation evidence in
#1833 `c24531e2`, #1904 `4182705d` and #1905 `d35b00fe`, then reopened after this
review found the general-download and anonymous-share gaps. Its explicit
acceptance does not exclude legacy readers. Re-close only after this repair is
merged and canonical CI passes, citing the actual merged commit and PR.
Similarly, #1772 closure does not complete the real owner journey acceptance
still tracked in #1819.

## Issues kept open

All 45 issues open at the start of the review were considered. Eight were initially
closed, then #1815 was reopened after the additional reader findings. Seven
remain closed; the remaining 38 have these specific gaps. Staleness or a merged
dependency alone was not treated as completion.

| Issues | Remaining requirement |
|---|---|
| #1866 | Fresh safe-disabled production cutover, deployment and serving verification. |
| #1815 | Merge and verify the additional general-download and anonymous-share acceptance repairs before claiming complete preview/export separation. |
| #1865 | Exact deployed renderer/default-flow acceptance; historical 76-case controlled matrix does not establish production release. |
| #1863 | Deployed TXT conversion terminal success/error/cancel/refund acceptance. |
| #1862 | Actual cold worker first-task/native-import qualification. |
| #1819 | Real saved-owner edit/save/reload/conflict/cancel/reconnect/late-result and exact semantic UI acceptance; mocked quality tests are insufficient. |
| #1816 | Auxiliary lease replacement/loss, cancellation during save and concurrent same-document revision proof. All-61-template one-pass execution is not its criterion. |
| #1814, #1820 | Remaining engine release gates and controlled end-to-visible-PDF latency/resource distributions. |
| #1830 | Canonical Google callback/configuration and real OAuth session acceptance. |
| #1628 | Actual primary Redis capacity restoration, configuration and monitoring acceptance. |
| #1802 | Source-equivalent Vercel Not Affected certificate contract, not just a later successful deployment. |
| #1799 | Owner-isolation fixtures across the requested browser engines; the current owner suite is Chromium-only. |
| #1683 | Exposed production account rotation/disablement confirmation; removing published credentials is insufficient. |
| #1713 | Actual repository entitlement/configuration for non-provider patterns and validity checks. |
| #1732 | Remaining legal/entity/vendor/contact verification and privacy mailbox acceptance; engineering cannot invent legal approval. |
| #1670 | Released npm tarball acceptance of headless commands, beyond merged #1671 `45eab9f3`. |
| #1668 | npm trusted-publisher binding and actual release, beyond merged #1669 `622aa73e`. |
| #1621 | QA epic still includes unresolved Redis, TUI publishing, billing/access and E2E requirements. |
| #1405, #1406, #1339 | Lifetime/weekly products and approved integer INR amounts remain unconfigured. |
| #1401, #1403, #1338 | Named screen-reader and accessible-output acceptance; related source controls alone do not meet these commitments. |
| #1381, #1382, #1383, #1384, #1331 | Employer outcomes, responsiveness, viewed/downloaded and hirer-facing signals remain incomplete. |
| #1370, #1319 | Careers-centre tenant/revenue accounting scope remains incomplete despite completed SSO work. |
| #1288 | Tagged PDF/PDF-UA output is not implemented. |
| #1096 | Selectable Console/Cockpit themes remain unimplemented despite the Workbench dependency. |
| #1343, #1341 | Identity verification and referral programme requirements remain incomplete. |
| #1380, #1330 | Recruiter lookup was intentionally refused in #1751 `dce0bf41`; reconcile the product decision/parent scope before closing as not planned. Outreach generation alone does not complete the parent. |

No real payment, additional hostile VM probe, paid service upgrade, credential
rotation, Redis authority switch or backup-instance change was performed by this
review. Private diagnostic reports remain outside the repository.
