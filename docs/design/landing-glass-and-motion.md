# Homepage materials, motion and sound

## Visual references

These references informed the homepage refinement. The implementation is original CSS and React; no paid component source or third-party templates were copied.

| Reference | What informed the design |
| --- | --- |
| [Apple: Materials](https://developer.apple.com/design/human-interface-guidelines/materials) and [Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/) | Glass belongs to navigation and controls. Keep document content crisp, foreground text legible, and provide opaque alternatives. |
| [Skiper UI component catalog](https://skiper-ui.com/components) | Compact interactive controls and restrained response to user input. |
| [Skiper: Music toggle](https://skiper-ui.com/v1/skiper25) | A small, explicit sound preference rather than autoplay. |
| [Skiper: Scroll progress](https://skiper-ui.com/v1/skiper89) | A thin reading-progress line in the floating navigation. |
| [Manus website examples](https://manus.im/features/webapp) and its [official showcase](https://awesome.manus.space/?category=web-app) | Examples were selected from the published showcase, then inspected on the live sites. |
| [Small Actions by Eric Sim](https://ericsim.manus.space/) | Clear interaction hierarchy and useful, compact choices near the main message. |
| [The Rise of OpenClaw](https://openclaw-story.manus.space/) | Chapter pacing and scroll progress. Its editorial claims are not reused. |

## Applied treatment

- A floating, sticky navigation surface uses a subtle highlight, translucent fill and a small backdrop blur. Its menu uses an opaque reading surface with the same rim and highlight: nested backdrop filters cannot reliably blur page content through a filtered parent. The menu has a viewport-bounded scrolling area, including in short landscape windows.
- The Classic / Modern / Minimal selector has a sliding glass pill. Classic remains first and selected by default; keyboard and touch selection retain their existing behavior.
- The selected résumé has a shallow material rim. Its content is real, selectable HTML; the existing optional Three.js enhancement is retained.
- Buttons respond to hover, focus and press. FAQ answers enter gently. Feature labels and header progress use native CSS scroll timelines where supported.
- Existing builder, ATS, tailoring, application-board and LaTeX demonstrations remain interactive. The glass treatment does not cover reading surfaces with blur.

## Sound behavior

Interface sounds are **off by default**, available in the homepage menu under Preferences. The choice is remembered locally when storage is available.

- Enabling sound plays a short confirmation. Subsequent control actions have a quiet selection cue.
- A section entering view can play one softer cue, at most once per section and no faster than every 1.4 seconds. Scrolling never creates or resumes an AudioContext.
- The Web Audio context is created only after an opted-in click. No audio files are downloaded and no audio graph runs on page load.
- Hidden tabs suspend sound; mute and route cleanup close the context. Each oscillator disconnects after its bounded 55–80 ms lifetime.
- Unsupported audio APIs and blocked storage cannot interrupt a product action.

## Accessibility and performance

- Reduced motion disables decorative CSS transitions, section reveals and scroll-timeline effects. Existing static HTML and no-WebGL behavior remain available.
- High contrast and reduced transparency use opaque navigation with no backdrop blur. Browsers without backdrop-filter also receive an opaque fallback.
- No dependencies, audio media requests, new JavaScript scroll listeners, animation-frame loops, video backgrounds or full-screen animated filters were added. The sound settings UI is loaded on demand.
- Blur is limited to the small header. This still has a compositing cost; it is not a claim of zero GPU work. Most feedback animates transform or opacity.

## Verification

The sound module has six unit tests for allocation, saved preferences, bounded cues, rate limiting, visibility, mute, unavailable APIs and blocked storage. The browser contract checks that scrolling allocates no audio context, explicit opt-in creates one, changing layouts reuses it, muting closes it, no media requests occur, and high contrast removes the computed backdrop filter.

The first browser pass exposed a CSS prefix normalization issue that removed the `none` backdrop-filter reset. Putting the prefixed reset before the standard declaration fixed the emitted CSS; both desktop and phone integration checks then passed. Existing functional tests were not changed to conceal this regression.

Final production screenshots, cross-browser results and source hashes are recorded in the PR and its accompanying `design-qa.md` evidence report.
