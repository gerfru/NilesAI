# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.x     | ✅        |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report vulnerabilities privately via [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) (Security → Report a vulnerability).

**Include:**
- Description and potential impact
- Steps to reproduce
- Affected version(s)

**Response time:** I aim to acknowledge reports within 7 days and publish a fix within 30 days for confirmed vulnerabilities.

## Security Design

Niles is designed as a self-hosted local AI butler. Key security properties:

- All data stays on your server — no third-party data sharing
- Passwords hashed with Argon2id
- CSRF protection on all state-changing routes
- SQL injection prevented via parameterized queries (asyncpg)
- CSP with per-request nonces (`'strict-dynamic'`)
- Session cookies: `httpOnly`, `secure`, `SameSite=Lax`
- Per-user credentials encrypted with Fernet (AES-128-CBC + HMAC)
- Rate limiting on authentication endpoints
- No-delete policy — data is never silently removed

## Scope

In scope: authentication, session management, data access controls, injection vulnerabilities, credential handling.

Out of scope: denial-of-service attacks on self-hosted instances, issues requiring physical access to the server.
