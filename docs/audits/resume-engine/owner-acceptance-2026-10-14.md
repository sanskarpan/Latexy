# Owner acceptance evidence

The isolated staging API passed one real, normal free-plan owner compile from a newly created minimal guided-builder resume. The resume reloaded with its stored `lualatex` default, and the job was submitted without an explicit compiler. The account’s `compilations` quota moved from 0 to 1.

The generated PDF matched its manifest hash and size. Geometry, SyncTeX, database finalization, Redis manifest, and private object-store checks matched the same owner, resume, source revision, and artifact. All 10 anonymous and second-user requests across the owner-only result and artifact endpoints were denied. Renderer identity matched the pinned Lua renderer image and assets fingerprint in the private manifest.

The source revision was `62a92cc7ade16f8cd62b0948fd6002f482384571`; the backend tree was `25ea300185880cbebce5fd1c9c076dd5a78f7393`. PR 1888 merged as `9b9abb6ac045812443c71bc673982774fa420b20`. Its exact 62a check run passed “Isolated Real Compile and Preview” and “Cross-Browser Quality.” These are CI check names; the isolated owner acceptance compile above is reported separately.

Two independent HTTPS CookieJar runs each returned sign-in 200 and session lookup 200 with both user and session present. Each sign-in response set one Secure, HttpOnly, SameSite=Lax host-only Better Auth session cookie. No cookie values were recorded here.

After a private packaging repair using the same immutable frontend build, `/try?mode=visual` rendered the Résumé Studio shell with fields and PDF placeholders. A synthetic owner signed in through the browser and saw the authenticated workspace shell. Browser workspace API GETs aborted, and direct in-app navigation to the API readiness endpoint reported `net::ERR_BLOCKED_BY_CLIENT`; the reason remains undetermined. Independently, HTTPS health, readiness, and job-health endpoints returned 200 and reported healthy/ready on acceptance revision 62a.

The earlier visual-route error boundary and service worker 404 were followed by the packaging repair and successful shell rendering; no further cause is inferred. Interactive editing and browser PDF preview/download remain unverified. This evidence covers the minimal owner compile path and the named exact 62a CI checks only; other templates, paid flows, production services, and broad end-to-end profile certification were not tested.

At 14:00:20 UTC all owned acceptance Apps were confirmed stopped with zero running tasks, including both temporary infrastructure sessions, the frontend, backend and bridge operator. The production recovery snapshot and validation branch were retained. Production and the owner's backup Redis were not reconfigured by these acceptance checks.
