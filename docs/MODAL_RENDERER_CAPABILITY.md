# Modal renderer capability gate

Lua in a local Linux worker uses the verified Landlock/seccomp policy. A Modal
worker cannot assume that its runtime supports Landlock; its Lua backend instead
requires a separately certified, immutable, credential-free VM image. Backend
selection and identity are resolved before render-cache lookup. Source metadata
cannot choose an image, policy, or capability.

The server-owned deployment configuration requires all three values:

- `MODAL_ENGINE_VM_CERTIFIED=true`
- `MODAL_ENGINE_VM_IMAGE_ID=im-...` for an already built, bare TeX image
- `MODAL_ENGINE_VM_ASSETS_FINGERPRINT` equal to that image's actual 64-character
  hexadecimal `/opt/latexy-renderer-version.json` fingerprint

The backend hashes the pinned image ID, assets fingerprint, and
`lua-credential-free-vm-v1` policy together. The VM preflight verifies the actual
marker before source upload. It never substitutes the application-worker image,
inherits its secrets, builds an image during a request, or uses its fingerprint
as evidence for the VM's assets. A selected unavailable capability fails closed.
Immutable Docker image digests permit cache reuse; mutable Docker tags do not.

## Durable automatic-deployment inputs

After independently certifying the intended image and supported profile, an
authorized operator supplies the three non-secret values above as GitHub Actions
repository configuration variables. The deployment workflow explicitly maps
`vars.MODAL_ENGINE_VM_CERTIFIED`, `vars.MODAL_ENGINE_VM_IMAGE_ID` and
`vars.MODAL_ENGINE_VM_ASSETS_FINGERPRINT` into its job environment. Keep any
same-named `Production` environment variables consistent with the reviewed tuple.
This source change does not create or populate those variables.

Before installing the Modal CLI or starting cloud work, the workflow requires
the flag to be exactly `true`, an immutable `im-...` identifier and a lowercase
64-hex asset fingerprint. Missing or malformed values fail closed with fixed
boolean diagnostics. Passing this input check is not image certification; its
report deliberately retains `certification_verified: false`.

The job-scoped values reach every subsequent Modal invocation. The existing
`_renderer_capability_env` image construction passes the same tuple into both
`api_image` and `latex_image`, including the compile and orchestrator workers.
The bound-runtime renderer preflight still runs after billing checks and before
migrations. A manual invocation must supply the same reviewed tuple in its
invoking environment; it must not rely on an unrelated local shell's state.

Do not replace `latexy-backend-secrets`, `latexy-storage` or `latexy-redis` to
deliver these non-secret values. The previous documentation's generic environment
requirements did not wire repository variables into future automatic deploys.
If an existing bound secret already contains conflicting renderer values, stop
and resolve that configuration through an authorized operator; this workflow
does not inspect, rewrite or claim precedence over opaque secret contents.

## Deployment configuration preflight

The Modal deployment workflow runs `modal_app.py::renderer_preflight` before
database migrations and the rolling backend update. It uses the candidate API
image and the same existing secret bindings as that API. It checks only accepted
compiler/default configuration, the required VM tuple, and the existing backend
resolver. It makes no provider or database request, creates no VM, and changes no
configuration. Failure leaves the existing serving backend and schema untouched
by this workflow. The frontend's protocol fallback handles frontend/backend skew.

Because LuaLaTeX is accepted and is the new-resume default, a missing or malformed
tuple blocks this rollout. A report with `configuration_ready: true` means only
that configuration is well formed; `certification_verified` is always `false`.
This is not proof that an image exists, matches its asset marker, supports the
required languages/templates, or has passed certification. Before setting the
tuple, the operator must have separately certified the exact immutable bare image
ID, its actual asset marker, and the intended supported profile. Do not set the
flag merely to pass deployment. The runtime compilation gate remains unchanged.

Each document's VM has one deadline, no network, secrets, mounted volumes, or
OIDC identity. Engine processes run as UID/GID 65534 under a closed environment.
The root controller reaps that UID before bounded, no-follow artifact export.
Convergence and BibTeX reuse the same VM and original policy. Closing or cancelling
the outer render terminates that session. This is a dedicated VM trust boundary,
not a claim of per-file Landlock enforcement inside Modal.

## Actual certification status

On 2026-10-07, the final bounded test of cached bare image
`im-1fho7eMXjj9Z60ziS7Kf6J` (TeX Live 2022) returned:

- Fontspec and hostile reads: exit 0, PDF present, all three private-access
  probes denied. VM network and parent-process preflight also passed.
- Hindi: exit 0, PDF present.
- CJK: exit 1, PDF present. This is a failure; PDF presence is insufficient.

The CJK failure's log was lost because the original certification script retained
only the first case's failure artifacts. The script now retains multilingual
failure artifacts too. The cause remains unknown.

On 2026-10-11, an ordinary functional smoke on that same historical image
successfully compiled one fixed synthetic English, Hindi and CJK document with
zero missing-glyph or font warnings. [The redacted execution evidence](audits/resume-engine/historical-modal-functional-2026-10-11.json)
records zero image builds and confirmed sandbox termination. This direct
compilation did not run the candidate renderer bridge or repeat its confinement
certification. The image has no renderer asset marker, so its assets cannot be
compared with the candidate fingerprint. The earlier CJK failure was not
reproduced; its original cause remains unresolved.

The image is not certified for a broad multilingual production default. A new
TeX image or asset fingerprint must receive its own certification; passing local
TeX Live 2025 tests does not attest this cloud image. Keep the production gate
closed until the intended supported profile and actual asset marker are verified.
