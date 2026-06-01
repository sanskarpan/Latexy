# Frontend Telemetry Strategy

## Current State

- The repo does not expose a production-ready frontend Prometheus endpoint.
- The previous scrape target `/api/metrics` was removed from Prometheus because it did not exist and created false confidence.
- Browser observability should be emitted as client telemetry, not as a server-side scrape target on the Next.js app.

## Recommended Model

1. Capture Web Vitals from the browser:
   - `LCP`
   - `CLS`
   - `INP`
   - `FCP`
   - `TTFB`
2. Attach context:
   - deployment environment
   - route pathname template when possible
   - authenticated vs anonymous session state
   - document type and editor mode for high-value product flows
3. Send telemetry to a backend ingestion endpoint or tracing pipeline, not directly to Prometheus from the browser.
4. Derive dashboards from aggregated server-side metrics and traces.

## Implementation Guidance

- Use Next.js `reportWebVitals` or `useReportWebVitals` in the app shell.
- Batch client events and sample aggressively on non-critical routes.
- Do not include resume content, job descriptions, OAuth tokens, cookies, or API keys in telemetry payloads.
- Normalize route labels to low-cardinality values such as:
  - `/`
  - `/try`
  - `/workspace/[resumeId]/edit`
  - `/billing`
  - `/admin`

## Initial Metrics To Add

- `web_vitals_lcp_ms`
- `web_vitals_inp_ms`
- `web_vitals_cls`
- `frontend_route_transition_ms`
- `editor_boot_ms`
- `pdf_preview_render_ms`
- `cover_letter_generation_click_to_result_ms`

## Why This Is Deferred

- It needs a backend telemetry sink and retention policy.
- It should share correlation IDs with backend requests and worker jobs.
- It is more useful once tracing is in place so browser events can join backend spans.
