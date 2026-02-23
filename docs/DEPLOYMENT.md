# Niles AI -- Deployment Guide

> **Stand:** 2026-02-23

Dieser Guide beschreibt die komplette Einrichtung von Niles AI -- von der leeren Maschine zum laufenden System.

Fuer technische Details zur Architektur und Entwicklung siehe [Development.md](Development.md).

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#1-voraussetzungen)
2. [Schnellstart](#2-schnellstart)
3. [Ollama (LLM Backend)](#3-ollama-llm-backend)
4. [Google OAuth (Web-UI Login)](#4-google-oauth-web-ui-login)
5. [WhatsApp (Evolution API)](#5-whatsapp-evolution-api)
6. [Kontakte (CardDAV)](#6-kontakte-carddav)
7. [Kalender (CalDAV + Google Calendar)](#7-kalender-caldav--google-calendar)
8. [Aufgaben (Vikunja)](#8-aufgaben-vikunja)
9. [HTTPS & Remote-Zugriff (Tailscale + Caddy)](#9-https--remote-zugriff-tailscale--caddy)
10. [Backup & Wartung](#10-backup--wartung)
11. [Fehlerbehebung](#11-fehlerbehebung)
12. [Referenz](#12-referenz)

---

## 1. Voraussetzungen

### Hardware

- Mac Mini (Apple Silicon empfohlen fuer lokale LLM-Inference)
- Mindestens 8 GB RAM (16 GB empfohlen)
- Mindestens 20 GB freier Speicher

### Software

| Software | Version | Zweck |
| -------- | ------- | ----- |
| Docker Desktop | aktuell | Container-Runtime (PostgreSQL, Evolution API, Caddy, Vikunja) |
| Ollama | >= 0.13 | Lokale LLM-Inference (GPU-beschleunigt) |
| Git | aktuell | Repository klonen |
| Tailscale | optional | Sicherer Remote-Zugriff von unterwegs |

### Konten (optional, je nach gewuenschten Features)

| Konto | Wofuer |
| ----- | ------ |
| Google Cloud | OAuth-Login fuer Web-UI + Google Calendar Sync |
| CardDAV-Anbieter (z.B. mailbox.org) | Kontakt-Sync |
| CalDAV-Anbieter (z.B. mailbox.org) | Kalender-Sync |

---

## 2. Schnellstart

### Repository klonen

```bash
git clone <repo-url> Niles
cd Niles
```

### .env erstellen

```bash
cp .env.example .env
```

Die zwei **Pflicht-Variablen** setzen:

```bash
# Frei waehlbar -- wird beim ersten Start als DB-Passwort gesetzt
EVOLUTION_POSTGRES_PASSWORD=ein-sicheres-passwort

# Frei waehlbar -- authentifiziert Niles gegenueber Evolution API
EVOLUTION_API_KEY=ein-sicherer-api-key
```

### Starten

```bash
./scripts/start.sh
```

Das Script:
1. Prueft ob Docker laeuft
2. Baut das Niles-Core-Image
3. Startet alle Container (PostgreSQL, Evolution API, Vikunja, Caddy, Niles Core)
4. Erstellt automatisch die `vikunja_db` Datenbank
5. Gibt die Service-URLs aus

### Health-Check

```bash
curl -sk https://localhost/health
# Erwartete Antwort: {"status":"ok"}
```

Web-UI: `https://localhost/ui/login` (self-signed Zertifikat -- Browser-Warnung akzeptieren)

### Alternativ: Interaktives Setup

```bash
./scripts/setup-interactive.sh
```

Fuehrt Schritt fuer Schritt durch die Einrichtung mit Status-Checks.

---

## 3. Ollama (LLM Backend)

Ollama laeuft **nativ auf dem Host** (nicht in Docker), um volle GPU-Performance zu nutzen.

### Installation

```bash
brew install ollama
```

### Modell laden

```bash
ollama pull llama3.1:8b
```

Ollama startet automatisch und lauscht auf Port `11434`.

### Verifizierung

```bash
curl http://localhost:11434/v1/models
```

### Konfiguration

Die Standardwerte in `.env` passen fuer die meisten Setups:

```bash
# Nur aendern wenn ein anderes Modell oder ein anderer Host gewuenscht ist
#LLM_BASE_URL=http://host.docker.internal:11434/v1
#LLM_MODEL=llama3.1:8b
```

`host.docker.internal` ist die Docker-interne Adresse des Host-Systems -- so erreicht Niles Core (im Container) den Ollama-Server (auf dem Host).

---

## 4. Google OAuth (Web-UI Login)

Ohne Google OAuth ist die Web-UI nur per API-Key erreichbar. Mit Google OAuth koennen sich Benutzer komfortabel per Google-Login anmelden.

### Schritt 1: Google Cloud Projekt

1. [Google Cloud Console](https://console.cloud.google.com/) oeffnen
2. Neues Projekt erstellen (z.B. "Niles AI")
3. **APIs & Services > OAuth consent screen** konfigurieren:
   - User Type: External
   - App-Name: "Niles AI"
   - Scopes: `email`, `profile`, `openid`
   - Fuer Google Calendar zusaetzlich: `https://www.googleapis.com/auth/calendar.readonly`

### Schritt 2: OAuth Client erstellen

1. **APIs & Services > Credentials > Create Credentials > OAuth client ID**
2. Application type: **Web application**
3. Name: "Niles"
4. **Authorized redirect URIs** (beide eintragen!):

```
https://<DEINE-URL>/ui/callback/google
https://<DEINE-URL>/ui/callback/google/calendar
```

Beispiele:
- Lokal: `https://localhost/ui/callback/google`
- Tailscale: `https://niles.example.ts.net/ui/callback/google`

### Schritt 3: .env konfigurieren

```bash
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxx

# Komma-separierte Whitelist (leer = alle Google-Accounts erlaubt)
GOOGLE_ALLOWED_EMAILS=user@gmail.com

# Muss gesetzt sein wenn hinter Reverse Proxy
BASE_URL=https://niles.example.ts.net
```

### Schritt 4: Neustart & Test

```bash
./scripts/start.sh
```

`https://<DEINE-URL>/ui/login` oeffnen -- der Google-Login-Button sollte erscheinen.

---

## 5. WhatsApp (Evolution API)

### Funktionsweise

- Niles nutzt die **Evolution API** fuer WhatsApp-Integration
- Jeder Benutzer erhaelt eine eigene WhatsApp-Instanz (`niles-wa-<user-id>`)
- Die WhatsApp-Session wird in `~/.evolution/instances/` persistiert
- Webhooks werden automatisch konfiguriert

### Verbinden

1. In der Web-UI einloggen: `https://localhost/ui/login`
2. **Settings** oeffnen
3. Im Abschnitt "WhatsApp" auf **Verbinden** klicken
4. **QR-Code mit WhatsApp scannen** (Telefon > Verknuepfte Geraete > Geraet hinzufuegen)
5. Status wechselt zu "Verbunden"

### Evolution API Manager

Die Evolution API hat eine eigene Web-Oberflaeche:

```
https://localhost:8443/manager
```

Login mit dem `EVOLUTION_API_KEY` aus der `.env`.

### Troubleshooting

| Problem | Loesung |
| ------- | ------- |
| QR-Code erscheint nicht | Container neustarten: `docker restart niles_evolution_api` |
| Session verloren | Neu verbinden ueber Settings > WhatsApp > Verbinden |
| Nachrichten kommen nicht an | Webhook pruefen: `./scripts/status.sh` |

---

## 6. Kontakte (CardDAV)

Kontakte werden per CardDAV synchronisiert (z.B. von mailbox.org, Nextcloud, iCloud).

### Konfiguration via .env

```bash
CARDDAV_USER=dein-benutzername
CARDDAV_PASSWORD=dein-passwort
FEATURE_CARDDAV_SYNC=true
```

Alternativ ueber die Web-UI: **Settings > Kontakte**.

### Sync-Zeitplan

- Automatischer Sync: taeglich um 03:00 UTC
- Manueller Sync: Settings > Kontakte > **Jetzt synchronisieren**

### Standard-URL

Standardmaessig wird `https://dav.example.com/carddav/` verwendet. Fuer andere Anbieter die `CARDDAV_URL` in `.env` anpassen:

```bash
CARDDAV_URL=https://cloud.example.com/remote.php/dav/addressbooks/users/USER/contacts/
```

---

## 7. Kalender (CalDAV + Google Calendar)

Niles unterstuetzt mehrere Kalenderquellen gleichzeitig. Die Verwaltung erfolgt ueber die **Web-UI** (Settings > Kalenderquellen).

### CalDAV-Quellen hinzufuegen

1. Web-UI oeffnen: Settings > Kalenderquellen
2. **Neue Quelle hinzufuegen**
3. Typ: CalDAV
4. URL, Benutzername und Passwort eingeben
5. **Speichern** -- Niles synchronisiert automatisch

### Google Calendar verbinden

1. Google OAuth muss konfiguriert sein (siehe [Abschnitt 4](#4-google-oauth-web-ui-login))
2. Settings > Kalenderquellen > **Google Calendar verbinden**
3. Google-Login durchfuehren und Kalender-Zugriff erlauben
4. Gewuenschte Kalender auswaehlen

### Legacy-Migration

Die alten `CALDAV_*` Variablen aus der `.env` werden beim ersten Start automatisch in die Datenbank migriert. Neue Kalenderquellen werden ausschliesslich ueber die Web-UI verwaltet.

### Sync-Zeitplan

- Automatischer Sync: taeglich um 03:20 UTC
- Manueller Sync: Settings > Kalenderquellen > **Jetzt synchronisieren**

---

## 8. Aufgaben (Vikunja)

Vikunja ist ein Open-Source-Aufgabenmanager. Niles kann darueber Aufgaben erstellen, auflisten und erledigen.

### Ersteinrichtung

#### 1. JWT Secret generieren

```bash
openssl rand -hex 32
```

In `.env` eintragen:

```bash
VIKUNJA_JWT_SECRET=<generierter-hex-string>
```

#### 2. Weitere .env-Variablen setzen

```bash
VIKUNJA_API_URL=http://vikunja:3456/api/v1
VIKUNJA_API_TOKEN=               # kommt in Schritt 5
FEATURE_VIKUNJA=true

# Bei Tailscale/Remote-Zugriff: Externe URL setzen (fuer E-Mail-Links etc.)
#VIKUNJA_PUBLIC_URL=https://niles.example.ts.net:3457
```

**Wichtig:** `VIKUNJA_API_URL` muss den Docker-internen Hostnamen `vikunja` verwenden (nicht `localhost`). `VIKUNJA_PUBLIC_URL` hingegen muss die **extern erreichbare** URL sein.

#### 3. Container starten

```bash
./scripts/start.sh
```

Erstellt automatisch die `vikunja_db` Datenbank.

#### 4. Admin-Account erstellen

1. `https://localhost:3457` oeffnen (oder `https://<tailscale-ip>:3457`)
2. **Konto erstellen** -- Username und Passwort waehlen
3. Ein Standard-Projekt anlegen (z.B. "Inbox")

Danach **Registrierung deaktivieren** in `docker/docker-compose.yml`:

```yaml
VIKUNJA_SERVICE_ENABLEREGISTRATION: "false"
```

> **Sicherheitshinweis:** Solange `ENABLEREGISTRATION=true`, kann **jeder mit Netzwerkzugriff** auf Port 3457 ein Vikunja-Konto erstellen. Auf Tailscale-only Setups ist das durch Netzwerk-ACLs geschuetzt. Wenn der Host im Internet erreichbar ist, Registrierung nach Account-Erstellung unbedingt deaktivieren.

#### 5. API-Token generieren

1. In Vikunja einloggen
2. Settings > API Tokens > **Create Token**
3. Rechte: mindestens `tasks` (Read + Write)
4. Token in `.env` eintragen:

```bash
VIKUNJA_API_TOKEN=<token-aus-vikunja>
```

#### 6. Niles neu starten

```bash
./scripts/start.sh
```

### Per-User Tokens

Jeder Benutzer kann seinen eigenen Vikunja-Token hinterlegen (Settings > Aufgaben). So hat jeder Benutzer seine eigenen Aufgabenlisten. Der Token aus der `.env` dient als Fallback.

### Verifizierung

Im Chat fragen: "Was steht auf meiner Todo-Liste?" -- Niles ruft `list_tasks` auf.

### Deaktivieren

`FEATURE_VIKUNJA=false` in `.env` setzen. Task-Tools werden dann nicht an das LLM gesendet.

---

## 9. HTTPS & Remote-Zugriff (Tailscale + Caddy)

### Caddy (Reverse Proxy)

Caddy laeuft als Docker-Container und terminiert TLS mit **self-signed Zertifikaten**. Konfiguration in `docker/Caddyfile`.

#### Hostnamen anpassen

Die Caddyfile enthaelt vorkonfigurierte Hostnamen:

```
https://localhost, https://192.168.1.x, https://192.168.1.x, https://niles.example.ts.net {
    tls internal
    reverse_proxy niles_core:8000
}
```

**Wichtig:** Die Caddyfile enthaelt hartcodierte IPs (`192.168.1.x` = Tailscale, `192.168.1.x` = LAN). Diese muessen fuer jede Deployment-Umgebung angepasst werden -- in **allen drei** Server-Bloecken (Niles Core :443, Evolution API :8443, Vikunja :3457).

Eigene IPs/Hostnamen hier eintragen. Nach Aenderungen:

```bash
docker restart niles_caddy
```

#### Ports

| Port | Service | Zugriff |
| ---- | ------- | ------- |
| 443 | Niles Web-UI + API | HTTPS via Caddy |
| 8443 | Evolution API Manager | HTTPS via Caddy |
| 3457 | Vikunja Web-UI | HTTPS via Caddy |
| 11434 | Ollama API | HTTP lokal |

### Tailscale (Remote-Zugriff)

Tailscale ermoeglicht sicheren Zugriff von ueberall -- ohne Port-Forwarding oder VPN-Konfiguration.

#### Einrichtung

1. [Tailscale installieren](https://tailscale.com/download)
2. Auf dem Mac Mini anmelden: `tailscale up`
3. Die Tailscale-IP oder den MagicDNS-Namen notieren (z.B. `niles.example.ts.net`)
4. In `docker/Caddyfile` den Hostnamen eintragen (siehe oben)
5. `BASE_URL` in `.env` setzen:

```bash
BASE_URL=https://niles.example.ts.net
```

6. Neustart: `./scripts/start.sh`

Nun ist Niles von jedem Geraet im Tailscale-Netzwerk erreichbar.

---

## 10. Backup & Wartung

### Backup erstellen

```bash
./scripts/backup.sh
```

Sichert:
- WhatsApp-Sessions (`~/.evolution/`)
- PostgreSQL-Datenbank (Docker Volume)
- Konfigurationsdateien (`docker/`, `config/`, `scripts/`, `.env`)
- Restore-Script

Speicherort: `~/Backups/Niles/` (komprimiertes `.tar.gz`-Archiv). Alte Backups werden automatisch bereinigt (letzte 7 behalten).

### Restore

```bash
tar -xzf niles-backup-YYYYMMDD_HHMMSS.tar.gz
cd YYYYMMDD_HHMMSS
./restore.sh
```

Danach: `./scripts/start.sh`

### Container-Updates

```bash
# Images neu bauen (mit Cache)
./scripts/build.sh

# Images neu bauen (ohne Cache, bei Problemen)
./scripts/build.sh --clean

# Starten
./scripts/start.sh
```

Bei Aenderungen an `src/` ist kein Rebuild noetig -- das Verzeichnis wird per Volume-Mount eingebunden und der uvicorn-Server laedt automatisch neu.

### Komplett-Reset

```bash
./scripts/cleanup.sh
```

Loescht alle Container und Docker-Volumes (PostgreSQL-Daten). WhatsApp-Sessions (`~/.evolution/`) werden **nicht** geloescht.

---

## 11. Fehlerbehebung

### Service startet nicht

```bash
# Logs aller Container anzeigen
docker compose -f docker/docker-compose.yml logs -f

# Nur Niles Core
docker compose -f docker/docker-compose.yml logs -f niles_core

# Status pruefen
./scripts/status.sh
```

| Symptom | Ursache | Loesung |
| ------- | ------- | ------- |
| `ValidationError` beim Start | Pflicht-Variable fehlt in `.env` | `EVOLUTION_POSTGRES_PASSWORD` und `EVOLUTION_API_KEY` setzen |
| Port 443 belegt | Anderer Service nutzt den Port | `docker ps` pruefen, ggf. anderen Service stoppen |
| Container startet und stoppt sofort | Fehler im Startup | `docker logs niles_core` pruefen |

### WhatsApp

| Symptom | Ursache | Loesung |
| ------- | ------- | ------- |
| QR-Code erscheint nicht | Evolution API nicht erreichbar | `docker restart niles_evolution_api`, dann erneut verbinden |
| Session verloren nach Neustart | Volume nicht gemountet | Pruefen ob `~/.evolution/instances/` existiert |
| "Geraet wurde entfernt" | Zu lange offline gewesen | Neu verbinden ueber Settings > WhatsApp |

### LLM antwortet nicht

| Symptom | Ursache | Loesung |
| ------- | ------- | ------- |
| Timeout / keine Antwort | Ollama nicht gestartet | `ollama serve` oder `brew services start ollama` |
| Modell nicht gefunden | Modell nicht geladen | `ollama pull llama3.1:8b` |
| Verbindungsfehler | Falscher LLM_BASE_URL | Pruefen: `curl http://localhost:11434/v1/models` |

### OAuth-Fehler

| Symptom | Ursache | Loesung |
| ------- | ------- | ------- |
| "redirect_uri_mismatch" | Redirect URI in Google Console falsch | Beide URIs pruefen: `/ui/callback/google` und `/ui/callback/google/calendar` |
| Login funktioniert, Calendar nicht | Zweite Redirect URI fehlt | `<BASE_URL>/ui/callback/google/calendar` in Google Console hinzufuegen |
| "access_denied" | Email nicht in Whitelist | `GOOGLE_ALLOWED_EMAILS` in `.env` pruefen (leer = alle erlaubt) |
| Fehler nach IP-Wechsel | BASE_URL stimmt nicht mehr | `BASE_URL` in `.env` aktualisieren, `./scripts/start.sh` |

### Vikunja

| Symptom | Ursache | Loesung |
| ------- | ------- | ------- |
| 400 Bad Request | `due_date` ohne Uhrzeit | Niles normalisiert automatisch seit v0.8. Bei aelteren Versionen: Update |
| 401 Unauthorized | Token abgelaufen oder falsch | Neuen Token in Vikunja generieren, in `.env` eintragen |
| "tasks" Tool nicht verfuegbar | Feature deaktiviert | `FEATURE_VIKUNJA=true` in `.env` setzen |
| Datenbank-Fehler | `vikunja_db` existiert nicht | `docker exec niles_evolution_postgres createdb -U evolution vikunja_db` |

---

## 12. Referenz

### Environment-Variablen

| Variable | Pflicht | Default | Beschreibung |
| -------- | ------- | ------- | ------------ |
| `EVOLUTION_POSTGRES_PASSWORD` | ja | -- | PostgreSQL-Passwort |
| `EVOLUTION_API_KEY` | ja | -- | Evolution API Authentifizierung |
| `NILES_API_KEY` | nein | auto-generiert | API-Key fuer `/chat`-Endpoint |
| `SESSION_SECRET` | nein | auto-generiert | Cookie-Signierung (Web-UI Sessions) |
| `BASE_URL` | nein | aus Request | Basis-URL fuer OAuth Redirects |
| `LLM_BASE_URL` | nein | `http://host.docker.internal:11434/v1` | Ollama API URL |
| `LLM_MODEL` | nein | `llama3.1:8b` | LLM-Modell |
| `TIMEZONE` | nein | `Europe/Vienna` | Zeitzone fuer Kalender/Prompts |
| `GOOGLE_CLIENT_ID` | nein | -- | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | nein | -- | Google OAuth Client Secret |
| `GOOGLE_ALLOWED_EMAILS` | nein | alle erlaubt | Komma-separierte Email-Whitelist |
| `CARDDAV_URL` | nein | `https://dav.example.com/carddav/` | CardDAV-Server URL |
| `CARDDAV_USER` | nein | -- | CardDAV-Benutzername |
| `CARDDAV_PASSWORD` | nein | -- | CardDAV-Passwort |
| `CALDAV_URL` | nein | `https://dav.example.com/caldav/` | CalDAV-Server URL (Legacy) |
| `CALDAV_USER` | nein | -- | CalDAV-Benutzername (Legacy) |
| `CALDAV_PASSWORD` | nein | -- | CalDAV-Passwort (Legacy) |
| `VIKUNJA_JWT_SECRET` | nein | -- | JWT Secret fuer Vikunja-Container |
| `VIKUNJA_PUBLIC_URL` | nein | `https://localhost:3457` | Oeffentliche Vikunja-URL (fuer E-Mail-Links, Passwort-Reset) |
| `VIKUNJA_API_URL` | nein | -- | Vikunja API Endpoint |
| `VIKUNJA_API_TOKEN` | nein | -- | Vikunja API Token (Fallback) |
| `FEATURE_VIKUNJA` | nein | `false` | Vikunja aktivieren/deaktivieren |
| `FEATURE_WHATSAPP_AUTO_REPLY` | nein | `false` | Automatische WhatsApp-Antworten |
| `FEATURE_TOOL_SEND_WHATSAPP` | nein | `true` | WhatsApp-Senden Tool verfuegbar |
| `POSTGRES_HOST_PORT` | nein | zufaellig | Postgres-Port auf Host (Debugging) |

### Ports

| Port | Service | Protokoll |
| ---- | ------- | --------- |
| 443 | Niles Web-UI + API | HTTPS (Caddy, self-signed) |
| 8443 | Evolution API Manager | HTTPS (Caddy, self-signed) |
| 3457 | Vikunja Web-UI | HTTPS (Caddy, self-signed) |
| 11434 | Ollama API | HTTP (nur lokal) |
| 8000 | Niles Core (intern) | HTTP (nicht direkt erreichbar) |
| 8080 | Evolution API (intern) | HTTP (nicht direkt erreichbar) |

### Scripts

| Script | Beschreibung |
| ------ | ------------ |
| `./scripts/start.sh` | Alle Container starten (build + up) |
| `./scripts/stop.sh` | Alle Container stoppen |
| `./scripts/status.sh` | Status aller Services pruefen |
| `./scripts/build.sh` | Docker-Images bauen (`--clean` fuer ohne Cache) |
| `./scripts/backup.sh` | Vollstaendiges Backup erstellen |
| `./scripts/cleanup.sh` | Alle Container und Volumes loeschen (Reset) |
| `./scripts/dev.sh` | Lokaler Dev-Server ohne Docker |
| `./scripts/test.sh` | Tests ausfuehren |
| `./scripts/setup-interactive.sh` | Interaktiver Setup-Assistent |

### Weitere Dokumentation

- [Development Guide](Development.md) -- Architektur, Tests, Entwicklung
- [Technische Spezifikation](Niles-Core-Spec.md) -- Komponenten, Konfiguration, Roadmap
- [API Reference](API.md) -- Endpoints, Payloads, Beispiele
