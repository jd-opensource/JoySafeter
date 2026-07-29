# Documentation Assets

This directory contains images and assets for documentation.

## Current Assets

| File | Description | Used In |
|------|-------------|---------|
| `joysafter.png` | JoySafeter logo mark used in the README hero | README.md / README_CN.md |
| `APK-case.gif` | APK vulnerability detection demo | README.md / README_CN.md Real-World Cases |
| `pentest-case.gif` | Penetration testing agent demo | README.md / README_CN.md Real-World Cases |
| `wechat-group-3.png`, `wechat-group-4.png` | WeChat user group QR codes | README.md Community section |
| `web-chat-group-2.jpg` | Additional community QR code asset | Reserved for community docs |

Additional architecture assets live in `docs/`:

| File | Description | Used In |
|------|-------------|---------|
| `docs/architecture-diagram.png` | Static architecture overview image | README.md / README_CN.md Architecture section |
| `docs/architecture-diagram.html` | Interactive architecture diagram | README.md / README_CN.md Architecture section |
| `docs/architecture-diagram.mmd` | Mermaid source for architecture diagram | Architecture maintenance |
| `docs/architecture-unified-event-model.mmd` | Mermaid source for event model | Architecture maintenance |

## Missing Assets (TODO)

These optional images would improve product walkthrough material:

| File | Description | Recommended Size | Priority |
|------|-------------|------------------|----------|
| `screenshot-agent-editor.png` | Current `/managed/agents/[agentId]/edit` interface screenshot or GIF | 1200x800 px | Medium |
| `screenshot-session-events.png` | Current `/managed/sessions/[sessionId]` event stream screenshot or GIF | 1200x800 px | Medium |
| `screenshot-quickstart.png` | Current `/managed/quickstart` flow screenshot or GIF | 1200x800 px | Medium |

## Image Guidelines

- Use PNG format for screenshots
- Use SVG for logos when possible
- Optimize images before committing (use tools like `pngquant` or `imageoptim`)
- Keep file sizes under 500KB per image

## Placeholder

The README currently references only committed assets. New screenshots should be added only when they match the current `/managed/**` UI.
