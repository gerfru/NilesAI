# Stage 10: Google OAuth, Multi-User & GUI v2

> **Status:** Abgeschlossen

## Kontext

Niles hat einen funktionierenden MVP (Stage 9): Chat-UI, Settings, Cookie-Auth mit API-Key. Stage 10 umfasst:

1. **User Management**: Google OAuth statt API-Key fuer Web-UI (automatische User-Erstellung beim ersten Login)
2. **Bessere GUI**: Tailwind CSS (Migration von Pico CSS), SSE Streaming, Timestamps, Rollen-Badges, Dark Mode, Mobile, Markdown

CSS-Framework wurde von Pico CSS v2 (CDN) auf Tailwind CSS v3.4.17 (Standalone CLI) migriert. API-Key Auth bleibt fuer programmatischen API-Zugriff (WhatsApp-Webhook, `/chat`).

---

## Architektur-Ueberblick

```
Browser                          FastAPI                     Google
  |                                |                           |
  |-- GET /ui/login ------------>  | Login-Seite               |
  |-- Click "Login with Google" -> | redirect --------->       |
  |                                |              <-- callback |
  |<-- Set session cookie -------- | create/find user in DB    |
  |                                |                           |
  |-- POST /ui/api/chat/stream --> | SSE: Tool-calls -> Stream |
  |<-- SSE chunks (wort-fuer-wort) |                           |
```

**Zwei Auth-Systeme (parallel):**

- **Google OAuth** -> Web-UI (Session-Cookie mit signierter User-ID)
- **API-Key** (`X-API-Key` Header) -> Programmatischer Zugriff (unveraendert)

---

## Phase A: User Management & Google OAuth

### A1. Users Table + UserStore

**Neue Datei: `src/niles/user_store.py`**

```sql
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP DEFAULT NOW()
);
```

**Klasse `UserStore`:**

- `initialize()` -> Tabelle erstellen
- `get_by_email(email) -> dict | None`
- `create_or_update(email, display_name, avatar_url) -> dict` -> INSERT ON CONFLICT UPDATE last_login

**Keine Admin-Rolle noetig** (1-3 User, alle gleichberechtigt).

### A2. Google OAuth Config

**Aenderung: `src/niles/config.py`**

```python
# Google OAuth (optional -- Web-UI login)
google_client_id: str = ""
google_client_secret: str = ""
google_allowed_emails: str = ""  # Komma-getrennt, leer = alle erlaubt
```

**Aenderung: `.env.example`**

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_ALLOWED_EMAILS=user1@gmail.com,user2@gmail.com
```

**Neue Dependency: `pyproject.toml`**

```
"httpx-oauth>=0.16",
```

### A3. OAuth Flow

**Aenderung: `src/niles/sources/web.py`**

Neue Routen:

| Route                       | Funktion                                          |
| --------------------------- | ------------------------------------------------- |
| `GET /ui/login`             | Login-Seite mit "Login with Google" Button         |
| `GET /ui/login/google`      | Redirect zu Google OAuth Consent                   |
| `GET /ui/callback/google`   | Google Callback -> User anlegen -> Session setzen  |
| `GET /ui/logout`            | Session + CSRF Cookie loeschen                     |

**OAuth-Ablauf:**

1. User klickt "Login with Google"
2. Redirect zu Google mit `openid email profile` Scopes
3. Google Callback mit Auth-Code
4. Server tauscht Code gegen Tokens (httpx-oauth)
5. Server liest User-Info (Email, Name, Avatar)
6. Pruefe Email gegen `GOOGLE_ALLOWED_EMAILS` (wenn gesetzt)
7. `user_store.create_or_update(email, name, avatar_url)`
8. Session-Cookie setzen (signierte User-ID via `itsdangerous`)
9. Redirect zu `/ui/chat`

### A4. Session Management

**Signed Cookie statt API-Key Cookie:**

```python
from itsdangerous import URLSafeTimedSerializer

# Serializer mit NILES_API_KEY als Secret
serializer = URLSafeTimedSerializer(settings.niles_api_key)

# Login: Cookie setzen
token = serializer.dumps({"uid": user["id"], "email": user["email"]})
response.set_cookie("niles_session", token, httponly=True, secure=..., samesite="strict")

# Verify: Cookie pruefen
data = serializer.loads(token, max_age=30*24*3600)
user_id = data["uid"]
```

- Kein DB-Lookup bei jedem Request (signiert = vertrauenswuerdig)
- Cookie Name aendert sich: `niles_api_key` -> `niles_session`
- CSRF Double-Submit Pattern bleibt unveraendert

### A5. Per-User Chat History

**Aenderung: `src/niles/sources/web.py`**

- Bisher: `chat_id = "web-ui"` (alle User teilen sich einen Chat)
- Neu: `chat_id = f"web-user-{user_id}"` (jeder User eigener Verlauf)
- ConversationHistory braucht **keine Aenderung** (filtert bereits per chat_id)

### A6. Template-Aenderungen fuer User-Info

**Aenderung: `base.html`**

- Nav zeigt User-Name + Avatar (kleines Bild) statt nur "Logout"

**Aenderung: `login.html`**

- "Login with Google" Button statt API-Key Formular
- Fallback-Hinweis: API-Key Login bleibt optional (wenn kein Google konfiguriert)

---

## Phase B: Streaming Responses (SSE)

### B1. Agent Streaming Support

**Aenderung: `src/niles/agent/core.py`**

Neue Methode `process_event_stream()` neben bestehendem `process_event()`:

```python
async def process_event_stream(self, event: dict):
    """Async generator: yields status updates + streamed text chunks."""
    # ... gleicher Setup wie process_event() ...

    for _ in range(MAX_TOOL_ROUNDS):
        # Nicht-streaming Tool-Call Phase
        response = await self.llm.chat.completions.create(
            model=self.model, messages=messages, tools=all_tools,
        )
        if choice.finish_reason != "tool_calls":
            break
        # Tool calls ausfuehren (wie bisher)
        yield {"type": "status", "text": f"Tool: {tool_name}..."}

    # Finale Antwort streamen
    stream = await self.llm.chat.completions.create(
        model=self.model, messages=messages, stream=True,
    )
    full_response = ""
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            full_response += delta
            yield {"type": "chunk", "text": delta}

    # History speichern
    await self.history.add_message(chat_id, "assistant", full_response)
    yield {"type": "done"}
```

**Wichtig:** Tool-Calls laufen NICHT im Streaming-Modus. Nur die finale Text-Antwort wird gestreamt. Waehrend Tool-Calls wird "Niles denkt nach..." angezeigt.

### B2. SSE Endpoint

**Aenderung: `src/niles/sources/web.py`**

```python
from fastapi.responses import StreamingResponse

@router.post("/api/chat/stream")
async def chat_stream(request: Request, message: str = Form(...)):
    # Auth + CSRF Check

    async def event_generator():
        async for item in agent.process_event_stream(event):
            data = json.dumps(item, ensure_ascii=False)
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},  # Caddy/Nginx: kein Buffering
    )
```

**Bisheriger `POST /api/chat`** bleibt als Fallback (fuer einfache Clients).

### B3. Chat Streaming JS

**Aenderung: `src/niles/static/js/app.js`**

Chat-Form Submission wird von htmx auf Custom JS umgestellt (nur fuer Chat, der Rest bleibt htmx):

```javascript
document.getElementById("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = e.target.querySelector("input[name='message']");
    const message = input.value.trim();
    if (!message) return;

    // User-Bubble sofort anzeigen
    appendUserBubble(message);
    input.value = "";

    // Leere Assistant-Bubble erstellen
    const bubble = appendAssistantBubble();

    // SSE-Stream starten
    const response = await fetch("/ui/api/chat/stream", {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": getCookie("niles_csrf"),
        },
        body: "message=" + encodeURIComponent(message),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        // Parse SSE data lines, append to bubble
        for (const line of decoder.decode(value).split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const item = JSON.parse(line.slice(6));
            if (item.type === "chunk") bubble.textContent += item.text;
            if (item.type === "status") showStatus(item.text);
        }
    }

    scrollChat();
});
```

---

## Phase C: GUI Improvements

### C1. Message Timestamps

**Aenderung: `src/niles/memory/history.py`**

`get_recent()` gibt jetzt `created_at` zurueck:

```python
return [{
    "role": row["role"],
    "content": row["content"],
    "timestamp": row["created_at"].isoformat(),
} for row in reversed(rows)]
```

**Aenderung: Templates** (message.html, chat.html, history.html):

```html
<small class="message-time">{{ msg.timestamp | default('') }}</small>
```

### C2. User Avatare / Rollen-Badges

**Aenderung: Templates:**

```html
<div class="message message-{{ msg.role }}">
    <span class="role-badge">
        {% if msg.role == 'user' %}Du{% else %}Niles{% endif %}
    </span>
    <div class="message-content">{{ msg.content }}</div>
</div>
```

- User-Avatar: Google-Avatar (falls vorhanden) oder Initialen
- Assistant: "N" Badge oder Niles-Icon

### C3. Dark Mode Toggle

**Tailwind CSS Dark Mode via `class="dark"` auf `<html>`:**

```html
<!-- base.html: Dark Mode via CSS class -->
<html lang="de" class="">
```

**Toggle-Button in Nav:**

```html
<button data-theme-toggle class="...">🌙 / ☀️</button>
```

**JS:** Speichert Praeferenz in `localStorage` (`niles_theme`), setzt `classList.add/remove("dark")` auf `<html>`. Theme wird vor DOMContentLoaded angewendet (kein Flash).

### C4. Mobile Responsiveness

Mobile Responsiveness wird ueber Tailwind Utility Classes direkt in den Templates geloest (z.B. `max-w-[75%]` fuer Bubbles). Keine separaten Media-Query Overrides noetig.

### C5. Markdown Rendering

**Neue Dependency: CDN (kein Build noetig)**

```html
<!-- base.html -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

**CSP Update:** `script-src 'self' https://unpkg.com https://cdn.jsdelivr.net`

**JS:** Assistant-Antworten durch `marked.parse()` rendern:

```javascript
bubble.innerHTML = marked.parse(chunk);  // statt textContent
```

**Achtung:** XSS-Schutz via `marked` Sanitizer oder DOMPurify.

---

## Dateien-Uebersicht

| Aktion      | Datei                                                                     |
| ----------- | ------------------------------------------------------------------------- |
| **Neu**     | `src/niles/user_store.py`                                                 |
| Aendern     | `src/niles/config.py` (Google OAuth Settings)                             |
| Aendern     | `src/niles/main.py` (UserStore init, app.state)                           |
| Aendern     | `src/niles/sources/web.py` (OAuth Routes, SSE Endpoint, Session Auth)     |
| Aendern     | `src/niles/agent/core.py` (process_event_stream)                          |
| Aendern     | `src/niles/memory/history.py` (Timestamps in get_recent)                  |
| Aendern     | `src/niles/templates/base.html` (CSP, Dark Mode, User-Info, marked.js)    |
| Aendern     | `src/niles/templates/login.html` (Google Login Button)                    |
| Aendern     | `src/niles/templates/chat.html` (Timestamps, Avatare)                     |
| Aendern     | `src/niles/templates/settings.html` (Theme Toggle)                        |
| Aendern     | `src/niles/templates/fragments/message.html` (Timestamps, Rollen-Badge)   |
| Aendern     | `src/niles/templates/fragments/history.html` (Timestamps)                 |
| Aendern     | `src/niles/static/css/style.css` (Dark Mode, Mobile, Badges)              |
| Aendern     | `src/niles/static/js/app.js` (Streaming, Dark Mode, Markdown)             |
| Aendern     | `pyproject.toml` (httpx-oauth)                                            |
| Aendern     | `.env.example` (Google OAuth Vars)                                        |
| Aendern     | `docker/Caddyfile` (SSE Buffering deaktivieren)                           |
| **Neu**     | `tests/test_user_store.py`                                                |
| Aendern     | `tests/test_web.py` (OAuth, Streaming, neue Auth)                         |
| Aendern     | `tests/test_settings_store.py` (apply_overrides Rueckgabewert)            |

---

## Implementierungs-Reihenfolge

| Step | Was                                     | Dateien                                  |
| ---- | --------------------------------------- | ---------------------------------------- |
| 1    | UserStore + Users Table                 | `user_store.py`, `main.py`               |
| 2    | Google OAuth Config                     | `config.py`, `.env.example`, `pyproject.toml` |
| 3    | OAuth Flow + Session Auth               | `web.py`, `login.html`                   |
| 4    | Per-User Chat + User-Info in Templates  | `web.py`, `base.html`, `chat.html`       |
| 5    | Agent Streaming (process_event_stream)  | `agent/core.py`                          |
| 6    | SSE Endpoint + Streaming JS             | `web.py`, `app.js`                       |
| 7    | Timestamps in Messages                  | `history.py`, Templates                  |
| 8    | Avatare / Rollen-Badges                 | Templates, CSS                           |
| 9    | Dark Mode Toggle                        | `base.html`, `app.js`, CSS               |
| 10   | Mobile Responsiveness                   | CSS                                      |
| 11   | Markdown Rendering                      | `base.html`, `app.js`, CSP               |
| 12   | Tests                                   | `test_user_store.py`, `test_web.py`      |
| 13   | Caddy SSE Config + Integration          | `Caddyfile`, Gesamttest                  |

---

## Voraussetzung: Google Cloud Setup (vom User)

1. Google Cloud Console -> APIs & Services -> Credentials
2. "Create OAuth 2.0 Client ID" (Web Application)
3. Authorized redirect URI: `https://<DEINE-IP-ODER-DOMAIN>/ui/callback/google`
4. Client ID + Client Secret in `.env` eintragen

---

## Verifikation

1. `python -m pytest tests/ -v` -> alle Tests bestehen
2. `python -m ruff check src/ tests/` -> keine Lint-Fehler
3. Browser: `/ui/login` -> "Login with Google" -> Google Consent -> redirect zu `/ui/chat`
4. Chat: Nachricht senden -> Antwort streamt wort-fuer-wort
5. Chat: Seite reload -> History + Timestamps angezeigt
6. Dark Mode: Toggle -> Theme wechselt, bleibt nach Reload
7. Mobile: Responsive Layout auf Smartphone
8. Settings: Feature-Flags toggeln -> Toast-Feedback
9. Zweiter User: Eigener Chat-Verlauf, eigene Session
10. API: `curl -H "X-API-Key: ..." /chat` -> funktioniert weiterhin
