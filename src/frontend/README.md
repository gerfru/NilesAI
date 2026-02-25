# Niles Frontend

Placeholder for a future dedicated frontend (React, Svelte, or native macOS app).

## Current State

The web interface is currently implemented **server-side** as part of Niles Core:

- **Location:** `src/niles/sources/web.py` + `src/niles/templates/`
- **Stack:** Jinja2 templates, Tailwind CSS, htmx, SSE streaming
- **Auth:** Google OAuth 2.0 + API-Key fallback, signed session cookies

This approach was chosen for simplicity (no separate build step, no Node.js dependency).

## What the Current Web UI Provides

- Chat with SSE streaming (word-by-word responses)
- Settings dashboard (feature flags, LLM config, timezone)
- WhatsApp connection management (QR code pairing)
- Calendar source management (CalDAV, Google Calendar, ICS)
- Contact sync management (CardDAV)
- Dark mode toggle

## Future Plans

A dedicated frontend would make sense when:

- More complex UI interactions are needed (drag-and-drop, rich editors)
- Mobile-native experience is desired
- Real-time WebSocket communication replaces SSE

Until then, the server-rendered htmx approach works well for the current feature set.
