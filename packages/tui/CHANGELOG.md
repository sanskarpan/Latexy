# Changelog

## 1.0.0 (2026-06-16)

### Features

- Interactive terminal UI built with React + Ink v5
- 32 slash commands covering all Latexy features
- Real-time LaTeX compilation with streaming log output
- ATS scoring with inline progress bar
- BYOK (Bring Your Own Key) multi-provider LLM support
- Headless/CI mode with JSON output (`--json` flag)
- XDG-compliant TOML config storage
- WebSocket streaming with pre-drain event buffer
- LoginOverlay and ResumePicker overlays
- Design token system (`lib/theme.ts`)
- `ProgressBar` component with color-coded fill (green/yellow/red)
- `KeyboardHints` component with context-aware shortcuts
- Welcome banner on empty transcript
- Two-tier slash command dispatch (local vs API)
- Collapsible build log with error/warning/success line classification
- Polished status bar with brand icon, plan badge, and connection indicator
