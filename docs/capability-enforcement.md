# Capability controls: execution and recovery

The catalog combines legacy feature groups with the 129 audited user-facing
capabilities. A child permission also requires its configured parent. Optional use intersects global, current account-role, plan-family and exact-SKU grants; anonymous is a separate context. Document/workspace/tenant ACLs still apply independently. Product
capabilities are checked against current server-side grants before admitting a
new operation; administrative privileges do not grant product access.

## What disabling a capability does

- Stops new submissions, generation, mutations, provider sync, publication and
  other external actions for that capability, including use of existing API
  keys, provider connections, saved builders and installed snippets.
- Stops serving existing public share links and portfolios when their owner's
  publication permission is disabled. Public reviews use the owner's grant,
  rather than assigning anonymous reviewers a free subscription.
- Rechecks active collaboration connections before accepting an update or chat
  frame. Authentication and document permissions still apply independently.
- Does not interrupt an already admitted provider call or queued job. Admitted
  work completes or fails under its existing ownership/finalization protocol.
  Failed work follows the existing exactly-once quota refund rules. A feature
  switch never cancels a job or manufactures a refund by itself.

## Safe downgrade and recovery

Owners retain source reads and edits, ordinary compilation, individual source
and PDF downloads, existing job status/results, historical artifacts, deletion,
key revocation, integration disconnect, sharing revocation, and account/billing
recovery. Those endpoints still enforce their original authentication and
ownership checks. Premium format conversion and bulk convenience export are
separate operations. Public sharing is not an owner-data export exemption.

Disabling BYOK rejects use of an existing stored key before decryption. It never
silently substitutes a platform-funded call for that rejected use.

## Enforcement map

`backend/app/middleware/capability_router.py` contains the inspectable endpoint
map and payload-sensitive policies. `CapabilityRouter` attaches dependencies
at registration, so production and isolated router tests share the policy.
Resource-dependent decisions (public ownership, specialty templates, structured
imports, API-key scope and provider-key use) are checked in the relevant route
or service after its normal resource/identity validation. Core source editing
is intentionally not parsed to prevent users writing LaTeX that resembles a
disabled optional UI tool.

Client-only editor tools are disabled at their UI entry points. CLI, MCP and
GitHub Action clients inherit the server policy of each operation they call.
These controls never disable authentication, security checks, tenant isolation,
or the administrative controls needed to reverse a configuration mistake.

Previously downloaded/cached artifacts cannot be recalled. Previously issued
presigned storage URLs remain valid until their original expiry (currently up
to one hour for shared PDFs and 24 hours for template assets); the capability
check stops issuing new URLs. Gated template API responses use `no-store`.

The additional [role/UI/service review](audits/admin-capabilities/role-review.md) records the current account-role matrix, race/recipient fixes and precise tested/unverified boundaries.
