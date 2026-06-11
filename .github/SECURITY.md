# Security Policy

## Scope

Niles ist ein selbst gehosteter AI Butler auf einem Mac Mini.
Alle Daten bleiben lokal — kein Cloud-Upload fuer Kernfunktionalitaet.

## Security-Scanning im SDLC

| Schicht | Tool | Trigger |
|---------|------|---------|
| Secret-Scan | gitleaks | Pre-commit + CI |
| Secret-Baseline | detect-secrets | Pre-commit |
| SAST (Python) | bandit 1.8.3 | Pre-commit + CI |
| SAST (Cross-file) | semgrep 1.164.0 | Pre-commit + CI |
| SCA (Python) | pip-audit 2.8.0 | CI |
| Image-Scan | trivy (CRITICAL+HIGH) | CI |
| SBOM | CycloneDX (syft) | CI |

## GitHub-natives Secret Scanning

GitHub Advanced Security (Secret Scanning, Code Scanning) ist auf dem Free-Plan fuer
private Repositories nicht verfuegbar (dokumentierte Ausnahme).

Ersatz: gitleaks (Pre-commit + CI) + detect-secrets (Pre-commit-Baseline).

## Sicherheitsluecken melden

Schwachstellen bitte **nicht** als oeffentliches GitHub Issue melden.
Stattdessen: GitHub → Security → "Report a vulnerability" (Private Disclosure) oder direkt an den Repository-Owner.
Kein Bug-Bounty-Programm; Meldungen werden zeitnah beantwortet.
