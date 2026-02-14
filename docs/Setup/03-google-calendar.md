# Phase 3: Google Calendar Integration

## Übersicht

Integration von Google Calendar in n8n via OAuth2 für Kalender-Management durch den AI-Agenten.

## Video-Tutorial

**Google Cloud Console Setup:** [YouTube Tutorial](https://www.youtube.com/watch?v=k77cJ5txWYs)

Dieses Video zeigt die komplette Einrichtung der Google Cloud Console für OAuth2-Authentifizierung.

## Voraussetzungen

- n8n läuft auf Port 5678
- Google Account
- **WICHTIG:** Google "Erweitertes Sicherheitsprogramm" muss deaktiviert sein!

## Schritte

### 1. Google Cloud Console - Projekt erstellen

1. Browser: https://console.cloud.google.com
2. Neues Projekt erstellen: "Niles AI"
3. Projekt auswählen

### 2. Google Calendar API aktivieren

1. **APIs & Services** → **Library**
2. Suche: "Google Calendar API"
3. **Enable**

### 3. OAuth Consent Screen konfigurieren

1. **APIs & Services** → **OAuth consent screen**
2. User Type: **External**
3. App Information:
   - App name: "Niles Local"
   - User support email: Deine Email
   - Developer contact: Deine Email
4. **Save and Continue**

### 4. Test User hinzufügen

1. Im OAuth consent screen → **Test users**
2. **"+ ADD USERS"**
3. Deine Gmail-Adresse einfügen
4. Save

### 5. Scopes/Bereiche hinzufügen

1. Im Menü: **"Datenzugriff"** (nicht "Bereiche"!)
2. Folgende Scopes aktivieren (Checkbox):
   - `.../auth/calendar` - "Alle Kalender... aufrufen, bearbeiten, freigeben..."
   - `.../auth/calendar.events` - "Termine in allen Kalendern abrufen und bearbeiten"
3. **Speichern**

**WICHTIG:** Warnung "Dieser Bereich wurde noch nicht bestätigt" ignorieren - ist normal für private Apps!

### 6. OAuth Client erstellen

1. **APIs & Services** → **Credentials**
2. **"+ Create Credentials"** → **OAuth Client ID**
3. Application type: **Web application** (NICHT Desktop!)
4. Name: "Niles n8n"
5. **Authorized redirect URIs:**
   - Zuerst in n8n die URL holen (siehe nächster Schritt)
6. Save

### 7. Redirect URI von n8n holen

**In n8n:**
1. Credentials → "+ Add Credential"
2. Suche: "Google Calendar OAuth2 API"
3. **OAuth Redirect URL kopieren:**
   - Format: `http://localhost:5678/rest/oauth2-credential/callback`

**Zurück zu Google Cloud Console:**
1. Credentials → Dein OAuth Client bearbeiten
2. **Authorized redirect URIs** → "+ ADD URI"
3. n8n URL einfügen
4. Save

### 8. Client ID & Secret laden

1. In Google Cloud Console → Credentials
2. OAuth Client anklicken → JSON download
3. JSON öffnen:
   ```json
   {
     "web": {
       "client_id": "583300848422-...",
       "client_secret": "GOCSPX-...",
       ...
     }
   }
   ```

### 9. In n8n konfigurieren

**In n8n:**
1. Credentials → Google Calendar OAuth2 API
2. Eintragen:
   - **Client ID:** Aus JSON kopieren
   - **Client Secret:** Aus JSON kopieren
3. **"Connect my account"** klicken

### 10. Google Authorization durchführen

1. Google Login öffnet sich
2. **WICHTIG:** Falls "Google erweitertes Sicherheitsprogramm" Fehler:
   - Google Account → Sicherheit
   - "Erweitertes Sicherheitsprogramm" **deaktivieren**
   - Nochmal versuchen
3. Warnung: **"App nicht verifiziert"** erscheint (normal!)
4. **"Erweitert"** klicken (klein unten)
5. **"Zu Niles AI wechseln (unsicher)"**
6. **Zugriff erlauben** für Calendar-Scopes
7. Fertig! → Zurück zu n8n mit "Connection successful"

## Test-Workflow

```yaml
Workflow: "Kalendereintrag erstellen"

Nodes:
1. Manual Trigger
2. Google Calendar Node
   - Resource: Event
   - Operation: Create
   - Calendar: [Dein Kalender auswählen]
   - Start: {{ $now.plus({hours: 1}).toISO() }}
   - End: {{ $now.plus({hours: 2}).toISO() }}
   - Summary: "Test Event von Niles"
   - Description: "Erstellt via n8n"
3. Execute Workflow

Ergebnis: Event sollte in Google Calendar erscheinen
```

## Wichtige Dateien

- `~/.n8n/database.sqlite` - Credentials (verschlüsselt)
- `~/Downloads/client_secret_*.json` - Google OAuth Credentials (kann gelöscht werden nach Setup)

## Verifikation

- [ ] Google Calendar API aktiviert
- [ ] OAuth Consent Screen konfiguriert
- [ ] Test User hinzugefügt (deine Email)
- [ ] Scopes aktiviert (calendar + calendar.events)
- [ ] OAuth Client erstellt (Web Application)
- [ ] Redirect URI konfiguriert
- [ ] n8n Credential verbunden
- [ ] Test-Event erstellt und in Google Calendar sichtbar

## Troubleshooting

### Fehler: "Error 400: policy_enforced"

**Ursache:** Scopes nicht aktiviert oder Google Workspace Admin blockiert

**Lösung:**
1. Datenzugriff → Scopes aktivieren (siehe Schritt 5)
2. Falls Workspace Account: Admin muss App freigeben

### Fehler: Google "Erweitertes Sicherheitsprogramm"

**Symptom:** OAuth-Login schlägt fehl mit Security-Warnung

**Lösung:**
1. Google Account → Sicherheit
2. **"Erweitertes Sicherheitsprogramm" deaktivieren**
3. Nochmal "Connect my account" in n8n

### "App nicht verifiziert" Warnung

**Normal für private Apps!**
- "Erweitert" → "Zu Niles wechseln (unsicher)" klicken
- Ist safe, da nur du Zugriff hast (Test User)

### Redirect URI Mismatch

- Prüfe dass die URI in Google Cloud Console EXAKT mit n8n übereinstimmt
- Format: `http://localhost:5678/rest/oauth2-credential/callback`
- Kein Trailing Slash!

## Nächste Schritte

→ [Phase 4: Email Integration](04-email.md)
