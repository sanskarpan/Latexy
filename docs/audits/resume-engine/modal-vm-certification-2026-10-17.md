# Modal renderer VM certification — 17 October 2026

This is the dated record of the boundary certification that lets
[L01](LAUNCH_CHECKLIST.md) supply its three non-secret deployment inputs. It
covers the **fixture-level boundary proof only**. It is not a claim that the
default production resume flow, the complete supported profile, or a production
rollout have been accepted; those remain separate gates.

## Certified tuple

| Input | Value |
|---|---|
| `MODAL_ENGINE_VM_CERTIFIED` | `true` |
| `MODAL_ENGINE_VM_IMAGE_ID` | `im-mF0rpCXgH2MBjw3TKMYXEf` |
| `MODAL_ENGINE_VM_ASSETS_FINGERPRINT` | `db98401df2e8c2d2b5a158ef96dcca6be5cfc36f2fc8451c693cb4018bf6c4a9` |

The image is an immutable, bare TeX image. The fingerprint is that image's actual
`/opt/latexy-renderer-version.json` marker, compared rather than assumed.

## Why this tuple

The same image/assets pair is already bound by earlier retained acceptance:

- [Modal bridge execution report](resume-engine/modal-bridge-acceptance-2026-10-14.json) — multipass/BibTeX, cancellation, bounded waits, observed termination.
- [Owner acceptance](resume-engine/owner-acceptance-2026-10-14.md) — a saved guided-builder résumé through admission, quota, workers and private artifacts.
- [October 15 acceptance](resume-engine/acceptance-2026-10-15/README.md) — 15 representative renderer profiles, all 61 shipped LuaLaTeX templates and 4 actual bridge scenarios, after the 2 GiB reservation and the multilingual font repairs in #1895/#1896.

## This run

Prerequisites established first: Modal client `1.5.5` and **Poppler `pdftotext`
25.07.0**. The harness deliberately refuses to start unless `pdftotext` is
Poppler, because Xpdf's layout extraction misreads shaped Hindi text.

```bash
# from backend/
python scripts/certify_modal_vm_engine.py \
  --image-id im-mF0rpCXgH2MBjw3TKMYXEf \
  --expected-assets db98401df2e8c2d2b5a158ef96dcca6be5cfc36f2fc8451c693cb4018bf6c4a9
```

Recorded output:

```json
{"image_id": "im-mF0rpCXgH2MBjw3TKMYXEf", "assets_fingerprint": "db98401df2e8c2d2b5a158ef96dcca6be5cfc36f2fc8451c693cb4018bf6c4a9", "asset_fingerprint_discovered": true, "asset_identity_comparison": "matched"}
{"case": "fontspec_and_hostile_reads", "returncode": 0, "pdf": true, "three_private_denied": true, "text_and_glyphs_checked": true}
{"case": "hindi", "returncode": 0, "pdf": true, "text_and_glyphs_checked": true}
{"case": "cjk", "returncode": 0, "pdf": true, "text_and_glyphs_checked": true}
{"fixtures_passed": true, "intended_image_and_assets_verified": true, "default_resume_flow_certified": false}
```

### What this establishes

- The serving VM's own asset marker **matches** the configured fingerprint, so
  the pinned image and the pinned assets are the same object rather than an
  assumption about a string literal.
- `fontspec` compiles and produces a PDF whose text and glyphs were extracted
  and checked.
- **All three private-access probes were denied** (`ROOT` read, `/proc/1/environ`
  read, sandbox-bootstrap write). Confinement held.
- Hindi and CJK both compiled with text and glyphs verified.

### The CJK regression is closed

The historical blocker was a CJK failure against the older cached image
(`im-1fho7eMXjj9Z60ziS7Kf6J`, TeX Live 2022) that exited 1 while still emitting
a PDF, whose diagnostic was lost because the script retained only the first
case's failure artifacts. On the current image CJK exits 0 with extracted text
verified. The script now retains multilingual failure artifacts, so a future
failure will keep its evidence. The original cause remains unestablished; the
failure itself is no longer reproduced on the certified tuple.

## Explicit limits

- `default_resume_flow_certified: false` is the harness's own output. This run
  proves the VM boundary and asset identity for three fixtures, not the complete
  supported profile or the default new-resume flow.
- It is **not** a production rollout, a schema cutover, or acceptance of paid
  billing.
- Broad cloud Lua remains uncertified. `--safer` on a fontspec/luaotfload
  document disables required font loading; that historical failure stands.
- L01, L02, L03 and the paid-launch gate L13 remain open. Setting these inputs
  unblocks the deployment pipeline; it does not close any of them.

## Resulting deployment effect

Before these inputs, `Deploy Modal Backend` failed within seconds at
`Validate renderer deployment inputs` with
`configuration_inputs_valid: false`, and had failed ~45 consecutive times.
With them set, the run at `1c657f64` passed that gate and continued through
`Validate read-only billing rollout safety` and
`Check renderer configuration before migrations`, and stopped at the next
gate — `Require schema cutover and recovery approval` — which needs a
separate, commit-scoped operator attestation about the recovery image and
drained public artifact readers.