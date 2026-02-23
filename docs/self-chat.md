# Niles AI – WhatsApp Self-Chat mit "Hey Niles" Trigger

> **Version:** 1.1
> **Stand:** 2026-02-23
> **Status:** Entwurf
> **Autor:** System-Architekt / Product Manager

---

## 1. Übersicht

WhatsApp wird zum primären Chat-Interface für Niles. Der Benutzer schreibt
sich selbst eine Nachricht (eigener Chat), und wenn sie mit **"Hey Niles"**
beginnt, verarbeitet Niles die Nachricht und antwortet im selben Chat.

### Warum?

- WhatsApp ist auf jedem Handy installiert
- Kein separates Interface nötig (Web-UI bleibt als Alternative)
- Natürliches "Butler"-Gefühl: kurze Nachricht an sich selbst → Antwort kommt
- Andere Nachrichten an sich selbst (Notizen, Links, Fotos) werden ignoriert

### Design-Prinzip

```
Eigene WhatsApp-Nachricht
    │
    ├── Beginnt mit "Hey Niles" → Agent verarbeitet, Antwort senden
    │
    └── Alles andere → Ignorieren (Notizen, Links, etc.)
```

---

## 2. Änderung: Webhook-Handler

### 2.1 Aktuelles Verhalten

```python
# src/niles/sources/whatsapp.py (aktuell)

# Ignore own messages
if key.get("fromMe", False):
    return {"status": "ignored", "reason": "own message"}
```

**Problem:** Alle eigenen Nachrichten werden komplett ignoriert.

### 2.2 Neues Verhalten

```python
# src/niles/sources/whatsapp.py (neu)

TRIGGER_PHRASES = ("hey niles", "hi niles", "hallo niles", "niles")
"""Case-insensitive trigger phrases. Checked against the start of the message."""


def _is_niles_trigger(text: str) -> bool:
    """Check if a message starts with a Niles trigger phrase."""
    lower = text.strip().lower()
    for phrase in TRIGGER_PHRASES:
        if lower.startswith(phrase):
            return True
    return False


def _strip_trigger(text: str) -> str:
    """Remove the trigger phrase from the beginning of the message.

    Returns the remaining text after the trigger, stripped of leading
    whitespace, commas, and colons.

    Examples:
        "Hey Niles, was steht heute an?" → "was steht heute an?"
        "Hey Niles was steht heute an?"  → "was steht heute an?"
        "Niles: Termin morgen?"          → "Termin morgen?"
        "Hey Niles"                      → ""
    """
    lower = text.strip().lower()
    for phrase in TRIGGER_PHRASES:
        if lower.startswith(phrase):
            rest = text.strip()[len(phrase):]
            # Strip common separators: comma, colon, dash, whitespace
            return rest.lstrip(" ,:-").strip()
    return text.strip()
```

### 2.3 Angepasster Webhook-Flow

```python
@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, token: str = Query(default="")):
    # ... Auth + JSON parsing (unverändert) ...

    data = payload.get("data", {})
    key = data.get("key", {})
    is_from_me = key.get("fromMe", False)
    remote_jid = key.get("remoteJid", "")
    message = data.get("message", {})

    text = (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
    )

    if not text:
        return {"status": "ignored", "reason": "no text content"}

    # --- NEU: Self-Chat Trigger-Logik ---
    if is_from_me:
        if not _is_niles_trigger(text):
            return {"status": "ignored", "reason": "own message without trigger"}

        # Trigger erkannt → Trigger-Phrase entfernen
        clean_text = _strip_trigger(text)
        if not clean_text:
            # Nur "Hey Niles" ohne Inhalt → Begrüßung
            clean_text = "Hallo!"

        logger.info("Self-chat trigger from %s: %s", remote_jid, clean_text[:100])

        # Self-Chat verwendet eigene chat_id für separate History
        sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
        chat_id = f"wa-self-{sender}"

        agent = request.app.state.agent
        event = {
            "type": "whatsapp",
            "from": chat_id,
            "content": clean_text,
            "metadata": {
                "jid": remote_jid,
                "sender": sender,
                "self_chat": True,
            },
        }

        try:
            response_text = await agent.process_event(event)
            if response_text:
                whatsapp_action = request.app.state.whatsapp_action
                # Antwort an die eigene Nummer senden
                await whatsapp_action.send_message(
                    to=remote_jid,
                    text=response_text,
                )
                logger.info("Self-chat reply sent to %s", remote_jid)
        except Exception:
            logger.exception("Failed to process self-chat message")

        return {"status": "processed", "trigger": "self-chat"}

    # --- Bestehende Logik für fremde Nachrichten ---
    # Agent verarbeitet die Nachricht (History, Memory), aber antwortet
    # NICHT automatisch. Niles antwortet fremden Personen nie von sich aus.
    sender = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
    logger.info("WhatsApp message from %s: %s", sender, text[:100])

    # Determine per-user chat ID from Evolution instance name
    instance_name = payload.get("instance")
    wa_store = getattr(request.app.state, "wa_store", None)
    chat_id = None

    if wa_store and instance_name:
        session = await wa_store.get_by_instance(instance_name)
        if session:
            chat_id = f"web-user-{session['user_id']}"

    # Fallback: use sender phone as chat ID
    if not chat_id:
        chat_id = f"wa-{sender}"

    # Process via agent (learn/remember), but NEVER send reply
    agent = request.app.state.agent
    event = {
        "type": "whatsapp",
        "from": chat_id,
        "content": text,
        "metadata": {"jid": remote_jid, "sender": sender},
    }

    try:
        response_text = await agent.process_event(event)
        if response_text:
            logger.info(
                "Agent generated reply for %s but auto-reply is disabled "
                "(only self-chat replies are sent)",
                sender,
            )
    except Exception:
        logger.exception("Failed to process WhatsApp message from %s", sender)

    return {"status": "processed"}
```

---

## 3. Wichtige Design-Entscheidungen

### 3.1 Separate Chat-History

Self-Chat bekommt eine eigene `chat_id`: `wa-self-{nummer}`

Das ist wichtig weil:
- Die Konversations-Historie getrennt bleibt von fremden Chats
- Niles den Kontext vorheriger Self-Chat-Befehle kennt
- Keine Vermischung mit Nachrichten von anderen Personen

### 3.2 Auto-Reply-Logik: Nur Self-Chat, nie fremde Chats

**Neue Regel (ersetzt `feature_whatsapp_auto_reply`):**

| Absender | Antwort |
|----------|---------|
| Eigene Nachricht mit "Hey Niles" | **Immer** antworten |
| Eigene Nachricht ohne Trigger | Ignorieren |
| Fremde Person | **Nie** automatisch antworten |

**Begründung:**
- Self-Chat ist eine explizite Interaktion — "Hey Niles" = klare Absicht
- Fremden Personen automatisch zu antworten ist unerwünscht und potenziell
  verwirrend (die Person weiß nicht, dass ein Bot antwortet)
- Der alte `feature_whatsapp_auto_reply` Toggle wird **entfernt** — er ist
  nicht mehr nötig, da die Logik jetzt eindeutig im Code verankert ist

**Auswirkung auf den Webhook-Handler:**

```python
# VORHER (bestehender Code):
if response_text and settings.feature_whatsapp_auto_reply:
    await whatsapp_action.send_message(to=remote_jid, text=response_text)

# NACHHER:
# Self-Chat: immer antworten (siehe Abschnitt 2.3)
# Fremde Chats: Agent wird aufgerufen, Ergebnis wird geloggt, aber
# NICHT gesendet. Die Nachricht wird verarbeitet (History, Memory),
# aber es geht keine Antwort raus.
```

Fremde Nachrichten werden weiterhin vom Agent verarbeitet (damit Niles
z.B. via Memory lernen kann wer schreibt), aber die Antwort wird
**nie automatisch gesendet**. Niles kann aber über den Self-Chat oder
die Web-UI angewiesen werden, einer Person aktiv zu schreiben
(`send_whatsapp`-Tool).

**Migration:**
- `feature_whatsapp_auto_reply` aus `config.py` entfernen
- `feature_whatsapp_auto_reply` aus `EDITABLE_SETTINGS` entfernen
- Setting in der `settings_overrides`-Tabelle ignorieren (kein DB-Cleanup nötig)
- Toggle in `settings.html` entfernen

### 3.3 Trigger-Phrase wird entfernt

"Hey Niles, was steht morgen an?" → Agent erhält "was steht morgen an?"

Damit muss die `soul.md` nicht angepasst werden. Der Agent sieht eine
normale Frage und verarbeitet sie wie aus jedem anderen Kanal.

### 3.4 Keine Änderung an der Evolution API Config

Die Evolution API liefert `fromMe: true` bereits bei Nachrichten, die der
Benutzer selbst gesendet hat. Die Webhook-Config muss nicht angepasst werden.

**Achtung:** Es muss sichergestellt sein, dass die Evolution API Nachrichten
aus dem eigenen Chat (Self-Chat / "Nachricht an mich selbst") auch als
`MESSAGES_UPSERT` Event liefert. Bei manchen Evolution API Versionen muss
dafür kein separates Event registriert werden — `MESSAGES_UPSERT` deckt
das bereits ab.

### 3.5 Niles' eigene Antworten nicht re-triggern

Wenn Niles an die eigene Nummer antwortet, erzeugt das theoretisch ein
neues `MESSAGES_UPSERT` Event mit `fromMe: true`. Da die Antwort von Niles
aber **nicht** mit "Hey Niles" beginnt, wird sie durch den Trigger-Check
automatisch ignoriert. Kein Endlos-Loop möglich.

---

## 4. Config-Änderungen: Feature-Flag-Umbau

### 4.1 Vorher → Nachher

```
VORHER (2 Flags, unklar):
┌─────────────────────────────────┬─────────┬──────────────────────────────┐
│ Flag                            │ Default │ Was es tut                   │
├─────────────────────────────────┼─────────┼──────────────────────────────┤
│ feature_whatsapp_auto_reply     │ false   │ Antwort an fremde Personen?  │
│ feature_tool_send_whatsapp      │ true    │ send_whatsapp-Tool aktiv?    │
└─────────────────────────────────┴─────────┴──────────────────────────────┘

NACHHER (1 Flag, eindeutig):
┌─────────────────────────────────┬─────────┬──────────────────────────────┐
│ Flag                            │ Default │ Was es tut                   │
├─────────────────────────────────┼─────────┼──────────────────────────────┤
│ feature_whatsapp_send_others    │ true    │ Darf Niles ANDEREN Personen  │
│                                 │         │ WhatsApp senden? (via Tool)  │
└─────────────────────────────────┴─────────┴──────────────────────────────┘
```

**Implizite Regeln (kein Toggle nötig):**

| Aktion | Erlaubt? | Warum |
|--------|----------|-------|
| Self-Chat Antwort ("Hey Niles") | **Immer** | WhatsApp verbunden = aktiv |
| Briefing an eigene Nummer | **Immer** | WhatsApp verbunden = aktiv |
| Antwort auf fremde Nachricht | **Nie** | Kein Auto-Reply, nie |
| Aktiv an andere senden (Tool) | **Konfigurierbar** | `feature_whatsapp_send_others` |

### 4.2 `config.py` Änderungen

```python
# ENTFERNEN:
feature_whatsapp_auto_reply: bool = False      # ← komplett weg
feature_tool_send_whatsapp: bool = True        # ← komplett weg

# NEU (Ersatz):
feature_whatsapp_send_others: bool = True      # Darf Niles anderen senden?
```

### 4.3 `settings_store.py` Änderungen

```python
EDITABLE_SETTINGS = {
    # ... bestehend ...

    # ENTFERNEN:
    "feature_whatsapp_auto_reply",       # ← weg
    "feature_tool_send_whatsapp",        # ← weg

    # NEU:
    "feature_whatsapp_send_others",      # ← Ersatz
}
```

### 4.4 `settings.html` Änderungen

```html
<!-- VORHER: Zwei verwirrende Toggles -->
<!-- feature_whatsapp_auto_reply  [OFF] -->   ← ENTFERNEN
<!-- feature_tool_send_whatsapp   [ON]  -->   ← ENTFERNEN

<!-- NACHHER: Ein klarer Toggle -->
<div class="flex items-center justify-between">
    <div>
        <span class="text-sm font-medium">An andere senden</span>
        <p class="text-xs text-zinc-500 dark:text-zinc-400">
            Darf Niles WhatsApp-Nachrichten an andere Personen senden?
            Antworten im eigenen Chat sind immer aktiv.
        </p>
    </div>
    <!-- Toggle für feature_whatsapp_send_others -->
</div>
```

### 4.5 `agent/core.py` — `_execute_tool_call()` Änderungen

```python
if name == "send_whatsapp":
    to = args["to"]
    text = args["text"]

    # Prüfe ob Empfänger die eigene Nummer ist
    own_number = self.config.briefing_whatsapp_number
    is_self = False
    if own_number:
        to_normalized = to.replace("+", "").replace(" ", "")
        is_self = to_normalized == own_number or to_normalized.endswith(own_number)

    # An andere senden: nur wenn Feature aktiv
    if not is_self and not self.config.feature_whatsapp_send_others:
        logger.info("send_whatsapp to others disabled via feature flag")
        return {
            "error": "Das Senden an andere Personen ist deaktiviert. "
                     "Du kannst diese Funktion in den Einstellungen aktivieren."
        }

    # ... restliche bestehende Logik (Kontaktauflösung, Senden etc.) ...
```

**Wichtig:** Wenn `to` ein Name ist (z.B. "Mama"), muss die Kontaktauflösung
**vor** dem Self-Check passieren. Die Logik wird:

```python
if name == "send_whatsapp":
    to = args["to"]
    text = args["text"]
    resolved_number = None

    # 1. Kontaktauflösung (wenn Name statt Nummer)
    if not to.replace("+", "").replace(" ", "").isdigit():
        contact = await self.contacts.find_by_name(to)
        if not contact:
            return {"error": f"Kontakt '{to}' nicht gefunden"}

        phones = contact.get("phones", [])
        if len(phones) > 1:
            # Multiple numbers → choose_phone (bestehende Logik)
            # ...
            return {"choose_phone": ...}

        resolved_number = contact.get("phone", "")
        if not resolved_number:
            return {"error": f"Keine Telefonnummer für '{to}'"}
    else:
        resolved_number = to

    # 2. Self-Check: Eigene Nummer = immer erlaubt
    own_number = getattr(self.config, "briefing_whatsapp_number", "")
    normalized = resolved_number.replace("+", "").replace(" ", "")
    is_self = bool(own_number and normalized.endswith(own_number))

    # 3. An andere: nur wenn Feature aktiv
    if not is_self and not self.config.feature_whatsapp_send_others:
        return {
            "error": "Das Senden an andere Personen ist deaktiviert. "
                     "Du kannst diese Funktion in den Einstellungen aktivieren."
        }

    # 4. Senden (bestehende Logik)
    instance = await self._resolve_wa_instance(chat_id) if chat_id else None
    result = await self.whatsapp.send_message(
        to=resolved_number, text=text, instance=instance,
    )
    result["to"] = resolved_number
    return result
```

### 4.6 Migration bestehender Settings

**DB:** Bestehende `settings_overrides`-Einträge für die alten Keys
werden ignoriert (Settings-Store lädt nur Keys die in `EDITABLE_SETTINGS`
sind). Kein DB-Cleanup nötig.

**`.env`:** Alte Variablen `FEATURE_WHATSAPP_AUTO_REPLY` und
`FEATURE_TOOL_SEND_WHATSAPP` werden nach Migration nicht mehr gelesen.
Sie können in `.env` stehen bleiben ohne Schaden (config `extra = "ignore"`).

### 4.7 Keine weiteren neuen Config-Felder

Das Self-Chat-Feature nutzt die bestehende WhatsApp-Infrastruktur.
Die `briefing_whatsapp_number` wird für den Self-Check wiederverwendet.

Optional (für mehr Kontrolle in v2):

```python
# config.py — optional, erst in v2
feature_whatsapp_self_chat: bool = True    # Self-Chat Trigger an/aus
whatsapp_trigger_phrases: str = "hey niles,hi niles,hallo niles,niles"
```

**Empfehlung für v1:** Kein zusätzlicher Config — Self-Chat ist immer
aktiv sobald WhatsApp verbunden ist. Die Trigger-Phrases sind hardcoded.

---

## 5. Erweiterung `config/soul.md`

Kein neuer Abschnitt nötig. Der Self-Chat-Text wird vom Trigger bereinigt
und sieht für den Agent aus wie jede andere Nachricht.

Optional kann ein Hinweis ergänzt werden:

```markdown
## Kanäle

- **Web-UI** — Browser-basierter Chat (SSE Streaming), interaktiv
- **WhatsApp Self-Chat** — Eigene Nachrichten mit "Hey Niles" Trigger, immer Antwort
- **WhatsApp (fremde Personen)** — Eingehende Nachrichten werden verarbeitet (Memory, History), aber Niles antwortet NICHT automatisch. Du kannst aktiv Nachrichten an andere senden wenn der Benutzer dich darum bittet (send_whatsapp-Tool) — aber nur wenn `feature_whatsapp_send_others` aktiviert ist. Wenn deaktiviert, sage dem Benutzer dass diese Funktion in den Einstellungen aktiviert werden kann.
- **API** — Programmatischer Zugriff via POST /chat

Dein Verhalten ist auf allen Kanälen identisch. Kontext und History sind
pro Kanal getrennt.
```

---

## 6. Ablauf-Diagramm

```
Benutzer tippt in WhatsApp (eigener Chat):
"Hey Niles, was steht morgen an?"

    │
    v
Evolution API → Webhook → POST /webhook/whatsapp
    │
    v
fromMe: true?
    ├── JA → _is_niles_trigger("Hey Niles, was steht morgen an?")?
    │       ├── JA → _strip_trigger() → "was steht morgen an?"
    │       │       │
    │       │       v
    │       │   agent.process_event({
    │       │       type: "whatsapp",
    │       │       from: "wa-self-436601234567",
    │       │       content: "was steht morgen an?"
    │       │   })
    │       │       │
    │       │       v
    │       │   Agent ruft find_event(date_from="morgen") auf
    │       │       │
    │       │       v
    │       │   WhatsAppAction.send_message(
    │       │       to="436601234567@s.whatsapp.net",
    │       │       text="Morgen hast du: ..."
    │       │   )
    │       │
    │       └── NEIN → ignore ("own message without trigger")
    │
    └── NEIN → Bestehende Logik (fremde Nachrichten)
```

---

## 7. Beispiel-Interaktionen

```
Du:    Hey Niles, was steht morgen an?
Niles: Morgen (Dienstag, 25.02.) hast du:
       • 09:00 — Standup Team
       • 14:00 — Projekt-Review
       Keine fälligen Aufgaben.

Du:    Hey Niles erinnere mich Milch zu kaufen
Niles: ✅ Aufgabe erstellt: "Milch kaufen"

Du:    Hey Niles, schick Julia eine Nachricht: Bin 10 Min später
Niles: ✅ Nachricht an Julia gesendet: "Bin 10 Min später"

Du:    Hey Niles
Niles: Hallo! Wie kann ich helfen?

Du:    Einkaufsliste für morgen (ohne Trigger → wird ignoriert)
       [Niles antwortet NICHT]
```

---

## 8. Verifikation

- [ ] Eigene Nachricht "Hey Niles, was steht an?" → Agent verarbeitet, Antwort kommt
- [ ] Eigene Nachricht "Einkaufsliste" (ohne Trigger) → Wird ignoriert
- [ ] "hi niles", "Hallo Niles", "NILES" → Alle Varianten triggern
- [ ] "Hey Niles" ohne Folgetext → Begrüßung "Hallo! Wie kann ich helfen?"
- [ ] "Hey Niles, schick Mama eine Nachricht" → Agent nutzt send_whatsapp
- [ ] Niles' Antwort löst keinen erneuten Trigger aus (kein Endlos-Loop)
- [ ] Fremde Nachrichten → Verhalten unverändert (auto_reply Flag)
- [ ] Self-Chat History ist getrennt von anderen Chat-IDs
- [ ] Mehrere aufeinanderfolgende Self-Chat-Nachrichten → Kontext bleibt erhalten
- [ ] `python -m pytest tests/ -v` → alle Tests bestehen

---

## 9. Test-Cases

Neue Datei: `tests/test_self_chat.py`

```python
"""Tests for WhatsApp self-chat trigger."""

from niles.sources.whatsapp import _is_niles_trigger, _strip_trigger


class TestIsNilesTrigger:
    def test_hey_niles(self):
        assert _is_niles_trigger("Hey Niles, was geht?") is True

    def test_hi_niles(self):
        assert _is_niles_trigger("Hi Niles was steht an") is True

    def test_hallo_niles(self):
        assert _is_niles_trigger("Hallo Niles!") is True

    def test_just_niles(self):
        assert _is_niles_trigger("Niles Termin morgen") is True

    def test_case_insensitive(self):
        assert _is_niles_trigger("HEY NILES was geht") is True
        assert _is_niles_trigger("hey niles") is True

    def test_with_leading_whitespace(self):
        assert _is_niles_trigger("  Hey Niles, test") is True

    def test_no_trigger(self):
        assert _is_niles_trigger("Einkaufsliste") is False
        assert _is_niles_trigger("Was macht Niles?") is False
        assert _is_niles_trigger("") is False

    def test_niles_in_middle(self):
        """'Niles' in the middle of a sentence should NOT trigger."""
        assert _is_niles_trigger("Ich frage Niles mal") is False


class TestStripTrigger:
    def test_hey_niles_comma(self):
        assert _strip_trigger("Hey Niles, was steht an?") == "was steht an?"

    def test_hey_niles_space(self):
        assert _strip_trigger("Hey Niles was steht an?") == "was steht an?"

    def test_niles_colon(self):
        assert _strip_trigger("Niles: Termin morgen") == "Termin morgen"

    def test_hey_niles_dash(self):
        assert _strip_trigger("Hey Niles - mach mal") == "mach mal"

    def test_only_trigger(self):
        assert _strip_trigger("Hey Niles") == ""

    def test_preserves_case(self):
        result = _strip_trigger("Hey Niles, Termin mit Julia")
        assert result == "Termin mit Julia"

    def test_case_insensitive_strip(self):
        result = _strip_trigger("HEY NILES was geht")
        assert result == "was geht"
```

---

## 10. Web-UI: Chat-Kanal-Auswahl

Die Web-UI zeigt standardmäßig den eigenen Web-Chat. Zusätzlich kann der
Benutzer den WhatsApp Self-Chat als **Read-Only-Log** einsehen. Kein
Schreiben in den WhatsApp-Kanal aus der Web-UI — nur lesen.

### 10.1 Konzept

```
┌────────────────────────────────────────┐
│  💬 Web-Chat  │  📱 WhatsApp-Log       │  ← Tabs / Pill-Toggle
├────────────────────────────────────────┤
│                                        │
│  (Chat-Nachrichten je nach Tab)        │
│                                        │
├────────────────────────────────────────┤
│  [ Nachricht eingeben... ] [Senden]    │  ← Nur bei Web-Chat aktiv
└────────────────────────────────────────┘
```

- **Web-Chat** (Standard): Interaktiver Chat wie bisher, SSE Streaming
- **WhatsApp-Log**: Read-Only Ansicht der Self-Chat-History (`wa-self-{nummer}`)

### 10.2 Änderung: `_user_chat_id()` flexibel machen

Aktuell gibt `_user_chat_id(user)` immer `web-user-{uid}` zurück.
Für die Kanal-Auswahl wird ein optionaler `channel`-Parameter eingeführt:

```python
# src/niles/sources/web.py

# Verfügbare Chat-Kanäle pro User
CHAT_CHANNELS = {
    "web": {
        "label": "💬 Web-Chat",
        "chat_id_fn": lambda user, settings: f"web-user-{user['uid']}",
        "readonly": False,
    },
    "whatsapp": {
        "label": "📱 WhatsApp",
        "chat_id_fn": lambda user, settings: f"wa-self-{settings.briefing_whatsapp_number}",
        "readonly": True,
    },
}


def _resolve_channel(user: dict, channel: str, settings) -> tuple[str, bool]:
    """Resolve channel name to (chat_id, readonly).

    Returns web-chat as fallback for unknown/invalid channels.
    """
    ch = CHAT_CHANNELS.get(channel, CHAT_CHANNELS["web"])
    chat_id = ch["chat_id_fn"](user, settings)
    return chat_id, ch["readonly"]
```

### 10.3 Änderung: Chat-Page mit Kanal-Parameter

```python
@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    channel: str = Query(default="web"),
):
    """Chat page with channel selection."""
    user = _get_session_user(request)
    if user is None:
        return RedirectResponse(url="/ui/login", status_code=303)

    settings = request.app.state.settings
    chat_id, readonly = _resolve_channel(user, channel, settings)

    history = request.app.state.history
    messages = await history.get_recent(chat_id, limit=_CHAT_PAGE_SIZE)
    has_more = len(messages) == _CHAT_PAGE_SIZE

    # Bestimme verfügbare Kanäle (WhatsApp nur wenn Nummer konfiguriert)
    available_channels = [("web", CHAT_CHANNELS["web"]["label"])]
    if settings.briefing_whatsapp_number:
        available_channels.append(("whatsapp", CHAT_CHANNELS["whatsapp"]["label"]))

    response = templates.TemplateResponse(request, "chat.html", {
        "messages": messages,
        "has_more": has_more,
        "next_offset": _CHAT_PAGE_SIZE,
        "active_page": "chat",
        "user": user,
        "channel": channel,
        "readonly": readonly,
        "available_channels": available_channels,
    })
    _ensure_csrf_cookie(request, response)
    return response
```

### 10.4 Änderung: History-Endpoint mit Kanal

```python
@router.get("/api/chat/history", response_class=HTMLResponse)
async def chat_history(
    request: Request,
    offset: int = Query(default=0, ge=0),
    channel: str = Query(default="web"),
):
    """Load older chat messages (pagination), channel-aware."""
    user = _get_session_user(request)
    if user is None:
        return Response(status_code=401, headers={"HX-Redirect": "/ui/login"})

    settings = request.app.state.settings
    chat_id, _readonly = _resolve_channel(user, channel, settings)

    history = request.app.state.history
    messages = await history.get_recent(chat_id, limit=_CHAT_PAGE_SIZE, offset=offset)
    has_more = len(messages) == _CHAT_PAGE_SIZE
    return templates.TemplateResponse(request, "fragments/history.html", {
        "messages": messages,
        "has_more": has_more,
        "next_offset": offset + _CHAT_PAGE_SIZE,
        "user": user,
        "channel": channel,
    })
```

### 10.5 Änderung: `chat.html` Template

Kanal-Tabs oberhalb des Chat-Bereichs + bedingtes Formular:

```html
{% extends "base.html" %}
{% from "macros/chat_bubble.html" import user_bubble, assistant_bubble %}
{% block title %}Chat - Niles AI{% endblock %}
{% block content %}
<div class="flex flex-col h-[calc(100dvh-120px)]">

    {# --- Kanal-Tabs --- #}
    {% if available_channels | length > 1 %}
    <div class="flex gap-1 mb-3 border-b border-zinc-200 dark:border-zinc-700 pb-2">
        {% for ch_key, ch_label in available_channels %}
        <a href="/ui/chat?channel={{ ch_key }}"
           class="px-4 py-1.5 rounded-full text-sm transition-colors duration-150
                  {% if ch_key == channel %}
                    bg-blue-500 text-white
                  {% else %}
                    text-zinc-500 dark:text-zinc-400
                    hover:bg-zinc-100 dark:hover:bg-zinc-800
                  {% endif %}">
            {{ ch_label }}
        </a>
        {% endfor %}
    </div>
    {% endif %}

    {# --- Read-Only Banner --- #}
    {% if readonly %}
    <div class="text-center text-xs text-zinc-400 dark:text-zinc-500
                bg-zinc-50 dark:bg-zinc-800/50 rounded-lg py-2 mb-2">
        📱 WhatsApp Self-Chat Log (nur lesen)
    </div>
    {% endif %}

    {# --- Chat Messages (unverändert) --- #}
    <div id="chat-messages" role="log" aria-live="polite"
         class="flex-1 overflow-y-auto py-4 thin-scrollbar"
         data-user-avatar="{{ user.avatar_url }}"
         data-channel="{{ channel }}"
         data-readonly="{{ 'true' if readonly else 'false' }}">
        {% if has_more %}
        <div id="load-more-container" class="text-center mb-4">
            <button hx-get="/ui/api/chat/history?offset={{ next_offset }}&channel={{ channel }}"
                    hx-target="#load-more-container"
                    hx-swap="outerHTML"
                    class="text-sm text-blue-500 dark:text-blue-400 border
                           border-blue-500 dark:border-blue-400 rounded-lg
                           px-4 py-2 bg-transparent hover:bg-blue-50
                           dark:hover:bg-zinc-800 cursor-pointer">
                Ältere Nachrichten laden
            </button>
        </div>
        {% endif %}
        {% if not messages and not has_more %}
        <div class="chat-empty flex items-center justify-center h-full
                    text-zinc-400 italic">
            {% if readonly %}
                Noch keine WhatsApp-Interaktionen.
            {% else %}
                Starte eine Unterhaltung...
            {% endif %}
        </div>
        {% endif %}
        {% for msg in messages %}
        {% if msg.role == 'user' %}
        {{ user_bubble(msg.content, msg.timestamp, user) }}
        {% else %}
        {{ assistant_bubble(msg.content, msg.timestamp) }}
        {% endif %}
        {% endfor %}
    </div>

    {# --- Thinking Indicator (nur Web-Chat) --- #}
    {% if not readonly %}
    <div id="thinking-indicator" class="hidden mb-4" aria-live="polite">
        {# ... bestehender Thinking-Indicator ... #}
    </div>
    {% endif %}

    {# --- Chat Form (nur Web-Chat) --- #}
    {% if not readonly %}
    <form id="chat-form" class="mt-2">
        {# ... bestehendes Formular unverändert ... #}
    </form>

    <div class="text-center mt-2">
        <button hx-post="/ui/api/chat/clear"
                hx-target="#chat-messages"
                hx-swap="innerHTML"
                hx-confirm="Chat-Verlauf wirklich löschen?"
                class="text-xs text-zinc-400 dark:text-zinc-500
                       hover:text-zinc-600 dark:hover:text-zinc-300
                       bg-transparent border-0 cursor-pointer
                       transition-colors duration-150">
            Verlauf löschen
        </button>
    </div>
    {% endif %}

</div>
{% endblock %}
```

### 10.6 Änderung: `history.html` Fragment

Der "Ältere Nachrichten laden"-Button muss den `channel`-Parameter weitergeben:

```html
{% if has_more %}
<div id="load-more-container" class="text-center mb-4">
    <button hx-get="/ui/api/chat/history?offset={{ next_offset }}&channel={{ channel | default('web') }}"
            hx-target="#load-more-container"
            hx-swap="outerHTML"
            class="text-sm text-blue-500 dark:text-blue-400 border
                   border-blue-500 dark:border-blue-400 rounded-lg
                   px-4 py-2 bg-transparent hover:bg-blue-50
                   dark:hover:bg-zinc-800 cursor-pointer
                   transition-colors duration-150">
        Ältere Nachrichten laden
    </button>
</div>
{% endif %}
{# ... Rest unverändert ... #}
```

### 10.7 WhatsApp-Log: Rollen-Labels

Im WhatsApp-Log sind die Rollen anders als im Web-Chat:

- `user`-Rolle = **Du** (deine "Hey Niles"-Nachricht, Trigger bereits entfernt)
- `assistant`-Rolle = **Niles** (die Antwort)

Die bestehenden `user_bubble` / `assistant_bubble` Macros passen bereits,
da sie "Du" und "Niles" als Labels verwenden.

### 10.8 Auto-Refresh des WhatsApp-Logs (optional)

Da der WhatsApp-Log asynchron wächst (neue Nachrichten kommen über den
Webhook), wäre ein Auto-Refresh praktisch. Einfachste Lösung:

```html
{# Nur im WhatsApp-Log: alle 30s automatisch refreshen #}
{% if readonly %}
<div hx-get="/ui/chat?channel=whatsapp"
     hx-trigger="every 30s"
     hx-target="body"
     hx-swap="outerHTML"
     hx-select="#chat-messages"
     hx-push-url="false">
</div>
{% endif %}
```

**Empfehlung für v1:** Kein Auto-Refresh. Manuelles Neuladen reicht.
Auto-Refresh kann als Folgeschritt ergänzt werden.

---

## 11. Dateien-Übersicht

| Aktion | Datei |
|--------|-------|
| Ändern | `src/niles/sources/whatsapp.py` (Trigger-Logik, fromMe Handling, Auto-Reply entfernt) |
| Ändern | `src/niles/sources/web.py` (Kanal-Auswahl, CHAT_CHANNELS, resolve) |
| Ändern | `src/niles/config.py` (2 Flags entfernen, 1 neues Flag) |
| Ändern | `src/niles/settings_store.py` (EDITABLE_SETTINGS: 2 raus, 1 rein) |
| Ändern | `src/niles/agent/core.py` (`_execute_tool_call`: Self-Check + neuer Flag-Name) |
| Ändern | `src/niles/templates/chat.html` (Tabs, readonly-Modus) |
| Ändern | `src/niles/templates/settings.html` (2 Toggles → 1 Toggle "An andere senden") |
| Ändern | `src/niles/templates/fragments/history.html` (channel-Parameter) |
| Ändern | `.env.example` (Flag-Rename dokumentieren) |
| **Neu** | `tests/test_self_chat.py` |
| Ändern | `tests/test_features.py` (Tests auf `feature_whatsapp_send_others` umstellen) |
| Optional | `config/soul.md` (Kanäle-Abschnitt) |

---

## 12. Zusammenfassung der WhatsApp-Kanäle nach Umsetzung

| Kanal | chat_id | Trigger | Antwort-Verhalten | Web-UI |
|-------|---------|---------|-------------------|--------|
| Self-Chat | `wa-self-{nummer}` | "Hey Niles" Prefix | **Immer** antworten | Read-Only Log |
| Fremde Person | `wa-{nummer}` | Keine | **Nie** auto-reply, Agent verarbeitet still | — |
| Per-User Instance | `web-user-{uid}` | Keine | **Nie** auto-reply, Agent verarbeitet still | — |
| Web-Chat | `web-user-{uid}` | Keine | **Immer** antworten (interaktiv) | Interaktiver Chat |
| Briefing (ausgehend) | — | Scheduled (APScheduler) | Ausgehend an eigene Nummer | — |

**Feature-Flags nach Umbau:**

| Flag | Default | Steuert was |
|------|---------|-------------|
| `feature_whatsapp_send_others` | `true` | Darf Niles via `send_whatsapp`-Tool an **andere** senden? |

**Kein Flag nötig für:**
- Self-Chat Antwort → immer (WhatsApp verbunden = aktiv)
- Briefing an eigene Nummer → immer (WhatsApp verbunden = aktiv)
- Auto-Reply an Fremde → nie (hardcoded, kein Toggle)

---

## 13. Verifikation (erweitert)

### Self-Chat Trigger
- [ ] Eigene Nachricht "Hey Niles, was steht an?" → Agent verarbeitet, Antwort kommt
- [ ] Eigene Nachricht "Einkaufsliste" (ohne Trigger) → Wird ignoriert
- [ ] "hi niles", "Hallo Niles", "NILES" → Alle Varianten triggern
- [ ] "Hey Niles" ohne Folgetext → Begrüßung
- [ ] Niles' Antwort löst keinen erneuten Trigger aus (kein Endlos-Loop)
- [ ] Self-Chat History ist getrennt von anderen Chat-IDs

### Fremde Nachrichten: Nie Auto-Reply
- [ ] Fremde Nachricht kommt an → Agent verarbeitet (History/Memory), aber keine Antwort gesendet
- [ ] Log zeigt "auto-reply is disabled (only self-chat replies are sent)"

### Feature-Flag: `feature_whatsapp_send_others`
- [ ] Flag `true` + "Hey Niles, schick Julia: Bin 10 Min später" → Nachricht an Julia gesendet
- [ ] Flag `false` + "Hey Niles, schick Julia: Bin 10 Min später" → Fehlermeldung "Senden an andere ist deaktiviert"
- [ ] Flag `false` + "Hey Niles, was steht morgen an?" → Funktioniert (Self-Chat, kein Senden an andere)
- [ ] Flag `false` + Briefing an eigene Nummer → Funktioniert (eigene Nummer, kein Senden an andere)
- [ ] Settings-UI zeigt **einen** Toggle: "An andere senden" mit Beschreibung
- [ ] Alte Flags `feature_whatsapp_auto_reply` und `feature_tool_send_whatsapp` existieren nicht mehr in config.py
- [ ] Alte Flags in `.env` verursachen keinen Fehler (config `extra = "ignore"`)

### Web-UI Kanal-Auswahl
- [ ] `/ui/chat` → Zeigt Web-Chat (Standard, interaktiv)
- [ ] `/ui/chat?channel=whatsapp` → Zeigt WhatsApp Self-Chat Log
- [ ] WhatsApp-Log ist read-only: kein Eingabefeld, kein Senden-Button
- [ ] WhatsApp-Log zeigt "📱 WhatsApp Self-Chat Log (nur lesen)" Banner
- [ ] Tab-Wechsel funktioniert, aktiver Tab ist hervorgehoben (blau)
- [ ] Ohne konfigurierte WhatsApp-Nummer: Kein WhatsApp-Tab sichtbar
- [ ] "Ältere Nachrichten laden" funktioniert im WhatsApp-Log (mit channel-Parameter)
- [ ] "Verlauf löschen" Button existiert nur im Web-Chat, nicht im WhatsApp-Log
- [ ] Leerer WhatsApp-Log zeigt "Noch keine WhatsApp-Interaktionen."
- [ ] `python -m pytest tests/ -v` → alle Tests bestehen