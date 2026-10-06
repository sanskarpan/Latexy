# Latexy brand mark

The primary mark is [Imprint Open Corner](imprint-open.svg). Two measured corners form an L with a deliberate gap. The wordmark uses the product's Bricolage Grotesque display face in the UI.

| Use | Asset |
| --- | --- |
| Browser tab and shortcuts | `frontend/src/app/icon.svg`, `frontend/public/favicon.ico` |
| Installed app | `frontend/public/icons/icon-192.png`, `icon-512.png`, `icon-512-maskable.png` |
| Apple home screen | `frontend/public/icons/apple-touch-icon.png` |
| Notification | `frontend/public/icons/icon-192.png` |
| Transparent mark | `frontend/public/brand/latexy-mark.svg`, `latexy-mark-reversed.svg` |
| UI lockup | `frontend/src/components/brand/BrandLogo.tsx` |
| Trial editor home button | `BrandMark` from the shared UI component |
| Figma importer header | Imprint vector in `frontend/figma-plugin/ui.html` |
| Browser extension toolbar, manager, popup, settings, and tabs | `packages/browser-extension/icons/icon-{16,32,48,128}.png` |
| Terminal interface | `└┐` text approximation in `packages/tui/src/lib/theme.ts` |
| GitHub Action badge | Blue `file-text` badge in `action.yml` |

Colors: ink `#19375D`, paper `#F7F3E9`. The mark may be used in one color on contrasting backgrounds. Keep at least one stem width of clear space around it. Use the standalone mark at 16 px or larger; use the full wordmark for larger surfaces.

Rebuild all browser, install, and extension assets with `python docs/brand/export-icons.py` (requires Pillow). The SVG path in that script is the source for the exports. Extension icons must also be included in the install archive; its manifest and package check enumerate them.

Use `BrandMark` or `BrandLogo` for new app brand placements, including standalone page headers. Do not substitute a text initial or an illustrative icon for the Latexy mark. Static integrations use the same Imprint geometry and the generated icons above.
