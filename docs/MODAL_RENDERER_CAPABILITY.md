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
failure artifacts too. The cause remains unknown. No further cloud retry was run.
The image is not certified for a broad multilingual production default. A new
TeX image or asset fingerprint must receive its own certification; passing local
TeX Live 2025 tests does not attest this cloud image. Keep the production gate
closed until the intended supported profile and actual asset marker are verified.
