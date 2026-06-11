## Was ändert dieser PR?

<!-- Kurze Beschreibung der Änderung und warum sie gemacht wird -->

## Art der Änderung

- [ ] Bug fix
- [ ] Feature
- [ ] Refactoring
- [ ] Security fix
- [ ] Docs / Config

## Test-Checkliste

- [ ] `uv run pytest tests/ -v` läuft grün
- [ ] `pre-commit run --all-files` läuft durch
- [ ] Neue Tests für neue Funktionalität hinzugefügt

## Security

- [ ] Keine Secrets im Code oder Logs
- [ ] Input-Validierung an Systemgrenzen
- [ ] Auth-Check in neuen Routen (Middleware → Route → Data Access)
