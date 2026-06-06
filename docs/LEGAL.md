# Niles AI — Legal Notices & Third-Party Licenses

> **Last updated:** 2026-03-03

This document contains legal notices, third-party license obligations, risk disclosures, and disclaimers for operators deploying Niles AI. It is intended to be distributed alongside the software.

---

## Table of Contents

1. [Niles AI License](#1-niles-ai-license)
2. [Third-Party Components & Licenses](#2-third-party-components--licenses)
3. [WhatsApp Integration — Risk Disclosure](#3-whatsapp-integration--risk-disclosure)
4. [Signal Integration — License Obligations](#4-signal-integration--license-obligations)
5. [Vikunja — License Obligations](#5-vikunja--license-obligations)
6. [Evolution API — License Obligations](#6-evolution-api--license-obligations)
7. [Data Privacy (GDPR / DSGVO)](#7-data-privacy-gdpr--dsgvo)
8. [AI Disclosure (EU AI Act Art. 52)](#8-ai-disclosure-eu-ai-act-art-52)
9. [General Disclaimer](#9-general-disclaimer)

---

## 1. Niles AI License

Niles AI is released under the **MIT License**. See [LICENSE](../LICENSE) for the full text.

---

## 2. Third-Party Components & Licenses

### 2.1 License Audit Summary

Full audit performed 2026-03-03 via `pip-licenses`. All 148 transitive Python
dependencies were verified. No GPL-only dependencies found in the Python
dependency tree.

| License Category | Count | Commercial Use |
|---|---|---|
| MIT | ~65 | Permissive — no restrictions |
| Apache-2.0 | ~30 | Permissive — patent grant included |
| BSD (2/3-Clause) | ~25 | Permissive — no restrictions |
| MPL-2.0 | 3 | File-level copyleft — modifications to MPL files must stay open |
| LGPL | 1 (psycopg2-binary) | Weak copyleft — dynamic linking (Python import) does not trigger |
| ISC / PSF / Unlicense | ~5 | Permissive — no restrictions |

**Conclusion:** All Python dependencies are compatible with commercial,
closed-source distribution.

### 2.2 Direct Dependencies (Python packages)

| Component | License | Source |
|-----------|---------|--------|
| FastAPI | MIT | [github.com/fastapi/fastapi](https://github.com/fastapi/fastapi) |
| uvicorn | BSD-3-Clause | [github.com/encode/uvicorn](https://github.com/encode/uvicorn) |
| asyncpg | Apache-2.0 | [github.com/MagicStack/asyncpg](https://github.com/MagicStack/asyncpg) |
| httpx | BSD | [github.com/encode/httpx](https://github.com/encode/httpx) |
| tenacity | Apache-2.0 | [github.com/jd/tenacity](https://github.com/jd/tenacity) |
| openai | Apache-2.0 | [github.com/openai/openai-python](https://github.com/openai/openai-python) |
| mcp | MIT | [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |
| pydantic-settings | MIT | [github.com/pydantic/pydantic-settings](https://github.com/pydantic/pydantic-settings) |
| Jinja2 | BSD | [github.com/pallets/jinja](https://github.com/pallets/jinja) |
| structlog | MIT / Apache-2.0 | [github.com/hynek/structlog](https://github.com/hynek/structlog) |
| APScheduler | MIT | [github.com/agronholm/apscheduler](https://github.com/agronholm/apscheduler) |
| argon2-cffi | MIT | [github.com/hynek/argon2-cffi](https://github.com/hynek/argon2-cffi) |
| itsdangerous | BSD | [github.com/pallets/itsdangerous](https://github.com/pallets/itsdangerous) |
| aiofiles | Apache-2.0 | [github.com/Tinche/aiofiles](https://github.com/Tinche/aiofiles) |
| websockets | BSD-3-Clause | [github.com/python-websockets/websockets](https://github.com/python-websockets/websockets) |
| python-dateutil | Apache-2.0 / BSD | [github.com/dateutil/dateutil](https://github.com/dateutil/dateutil) |
| PyYAML | MIT | [github.com/yaml/pyyaml](https://github.com/yaml/pyyaml) |
| prometheus-client | Apache-2.0 | [github.com/prometheus/client_python](https://github.com/prometheus/client_python) |
| trafilatura | Apache-2.0 | [github.com/adbar/trafilatura](https://github.com/adbar/trafilatura) |
| json-repair | MIT | [github.com/mangiucugna/json_repair](https://github.com/mangiucugna/json_repair) |
| alembic | MIT | [github.com/sqlalchemy/alembic](https://github.com/sqlalchemy/alembic) |
| notion-client | MIT | [github.com/ramnes/notion-sdk-py](https://github.com/ramnes/notion-sdk-py) |
| SQLAlchemy | MIT | [github.com/sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) |
| **psycopg2-binary** | **LGPL** | [github.com/psycopg/psycopg2](https://github.com/psycopg/psycopg2) |

**psycopg2-binary (LGPL):** Python imports are dynamic linking. The LGPL
explicitly permits dynamic linking without triggering copyleft. Users can
replace the library via pip/uv. No source disclosure required.

### 2.3 Transitive Dependencies with Copyleft Elements

| Component | License | Notes |
|-----------|---------|-------|
| certifi | MPL-2.0 | Root CA bundle. File-level copyleft only. |
| pathspec | MPL-2.0 | Glob matching library. File-level copyleft only. |
| tqdm | MPL-2.0 + MIT | Dual-licensed. Progress bar (transitive via trafilatura). |
| tld | MPL-1.1 / GPL-2.0 / LGPL-2.1+ | Triple-licensed. Choose LGPL-2.1+. |

MPL-2.0 is file-level copyleft: if you modify MPL-licensed source files,
those modifications must remain under MPL. Using the libraries unmodified
(as Niles does) requires no source disclosure.

### 2.4 Docker Images (External Services)

| Component | License | Distribution | Source |
|-----------|---------|-------------|--------|
| Ollama | MIT | Host-installed (not bundled) | [github.com/ollama/ollama](https://github.com/ollama/ollama) |
| PostgreSQL | PostgreSQL License | Docker image | [postgresql.org](https://www.postgresql.org/) |
| Caddy | Apache-2.0 | Docker image | [caddyserver.com](https://caddyserver.com/) |
| SearXNG | AGPL-3.0 | Docker image | [github.com/searxng/searxng](https://github.com/searxng/searxng) |
| Evolution API | Modified Apache-2.0 | Docker image | [github.com/EvolutionAPI/evolution-api](https://github.com/EvolutionAPI/evolution-api) |
| **Vikunja** | **AGPL-3.0** | Docker image | [vikunja.io](https://vikunja.io/) |
| signal-cli-rest-api | MIT | Docker image | [github.com/bbernhard/signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) |
| **signal-cli** | **GPLv3** | Bundled in signal-cli-rest-api image | [github.com/AsamK/signal-cli](https://github.com/AsamK/signal-cli) |
| **libsignal** | **AGPLv3** | Bundled in signal-cli | [github.com/signalapp/libsignal](https://github.com/signalapp/libsignal) |

Licenses marked in **bold** have copyleft obligations. Niles communicates
with all Docker services exclusively via HTTP/WebSocket APIs — no linking.
See sections 4, 5, and 6 below for detailed analysis.

---

## 3. WhatsApp Integration — Risk Disclosure

### ⚠️ Important: Use at Your Own Risk

Niles AI integrates with WhatsApp through the **Evolution API**, which uses an unofficial, reverse-engineered WhatsApp Web protocol. This integration is **not endorsed or supported by Meta (WhatsApp)**.

### Known Risks

**Account suspension:** WhatsApp may suspend or permanently ban accounts used with unofficial automation tools without prior warning. Account bans have been documented by multiple sources (see [Baileys issue #1869](https://github.com/WhiskeySockets/Baileys/issues/1869)).

**Terms of Service violation:** Using unofficial APIs to interact with WhatsApp violates the [WhatsApp Terms of Service](https://www.whatsapp.com/legal/terms-of-service/). Additionally, since January 2026, Meta explicitly prohibits AI providers from using even the official WhatsApp Business API for AI-powered message processing (see [WhatsApp Business Solution Terms](https://www.whatsapp.com/legal/business-solution-terms/)).

**No recovery guarantee:** Suspended WhatsApp accounts may not be recoverable. Loss of message history, contacts, and groups may be permanent.

### Operator Responsibility

By enabling the WhatsApp integration, the operator acknowledges:

1. The WhatsApp integration uses unofficial, unsupported methods to communicate with WhatsApp servers.
2. Use of this integration may result in account suspension or permanent ban at any time.
3. The operator assumes full responsibility for any consequences arising from WhatsApp integration use, including but not limited to account loss, data loss, and business disruption.
4. **The software author provides no warranty or liability for WhatsApp-related account actions taken by Meta.**

### Recommendation

For commercial deployments, consider using **Signal** (included) or **Telegram** (planned) as primary messaging channels. These offer official APIs or documented integration paths with significantly lower risk.

---

## 4. Signal Integration — License Obligations

### Components

Niles communicates with Signal through the **signal-cli-rest-api** Docker container. This container bundles:

- **signal-cli** — licensed under **GPLv3** ([full license](https://www.gnu.org/licenses/gpl-3.0.html))
- **libsignal** — licensed under **AGPLv3** ([full license](https://www.gnu.org/licenses/agpl-3.0.html))
- **signal-cli-rest-api** — licensed under **MIT**

### Why Niles Can Remain Closed-Source

Niles communicates with signal-cli-rest-api exclusively via HTTP REST API and WebSocket. Under established GPL interpretation, communication over network protocols (HTTP, WebSocket) does **not** constitute "linking" and therefore does **not** create a derivative work. Niles AI's own source code is not subject to GPL copyleft obligations.

The AGPLv3 component (libsignal) is bundled inside signal-cli, which is bundled inside the signal-cli-rest-api Docker container. Niles does not link against libsignal directly — it communicates via HTTP. The AGPL "network use" clause applies to the container providing the service, not to HTTP clients consuming it.

No modifications are made to signal-cli, libsignal, or signal-cli-rest-api.

### Distribution Obligations

When distributing Niles AI (including the Docker Compose configuration that references signal-cli-rest-api), the following must be provided:

- **signal-cli source code link:** [https://github.com/AsamK/signal-cli](https://github.com/AsamK/signal-cli)
- **GPLv3 license text:** [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html)
- **signal-cli-rest-api source code link:** [https://github.com/bbernhard/signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
- **libsignal source code link:** [https://github.com/signalapp/libsignal](https://github.com/signalapp/libsignal)

These obligations are fulfilled by this document.

### Unofficial Integration Notice

Signal integration uses signal-cli as a **Linked Device** connected to the operator's existing Signal account. This is an unofficial integration not endorsed by the Signal Foundation. No SLA or availability guarantee is provided for Signal messaging functionality.

---

## 5. Vikunja — License Obligations

### License

Vikunja is licensed under **AGPL v3** ([full license](https://www.gnu.org/licenses/agpl-3.0.html)).

### Architecture

Niles communicates with Vikunja exclusively via its **HTTP REST API** (`/api/v1/`). Vikunja runs as a separate Docker container. Niles does not link against, modify, or bundle Vikunja source code.

### Why Niles Can Remain Closed-Source

Under established AGPL interpretation, communicating with an AGPL-licensed service over a network API (HTTP) does **not** make the client a derivative work. Niles AI's own source code is not subject to AGPL copyleft obligations.

The AGPL "network use" clause (Section 13) requires that users interacting with the AGPL software over a network can obtain its source code. This obligation applies to the **Vikunja service itself**, not to HTTP clients that call its API.

No modifications are made to Vikunja.

### Distribution Obligations

When distributing Niles AI (including the Docker Compose configuration that references the Vikunja image):

- **Vikunja source code:** [https://kolaente.dev/vikunja/vikunja](https://kolaente.dev/vikunja/vikunja)
- **AGPL v3 license text:** [https://www.gnu.org/licenses/agpl-3.0.html](https://www.gnu.org/licenses/agpl-3.0.html)

These obligations are fulfilled by this document.

### Note

[Not verified] The legal assessment that HTTP API communication does not trigger AGPL copyleft is based on widely accepted interpretation but has not been tested in court for this specific configuration. If you plan commercial distribution at scale, independent legal counsel is recommended.

---

## 6. Evolution API — License Obligations

### License

Evolution API is released under a **modified Apache 2.0 license** that includes a notification requirement.

### Notification Obligation

The Evolution API license requires a visible notice in products that use it:

> **"Evolution API is being utilized in this product."**

Source: [Evolution API LICENSE](https://github.com/EvolutionAPI/evolution-api/blob/main/LICENSE)

### Source Code

- **Evolution API:** [https://github.com/EvolutionAPI/evolution-api](https://github.com/EvolutionAPI/evolution-api)

---

## 7. Data Privacy (GDPR / DSGVO)

### On-Premise Architecture

Niles AI is designed as an **on-premise, self-hosted** application. All data processing occurs locally on the operator's hardware:

- **LLM inference:** Runs locally via Ollama (no cloud API calls)
- **Message storage:** PostgreSQL database on local Docker volume
- **Contact and calendar data:** Synced from operator's own accounts, stored locally

### Operator as Data Controller

When deploying Niles AI, the **operator** is the data controller under GDPR. The software author is not a data processor, as no data is transmitted to or processed by the author.

### Data Stored Locally

| Data Type | Storage | Source |
|-----------|---------|--------|
| WhatsApp messages | PostgreSQL (local) | Evolution API |
| Signal messages | PostgreSQL (local) | signal-cli-rest-api |
| Calendar events | PostgreSQL (local) | CalDAV / Google Calendar sync |
| Contacts | PostgreSQL (local) | CardDAV sync |
| Conversation history | PostgreSQL (local) | Web UI / messenger interactions |
| LLM memory (key-value) | PostgreSQL (local) | Agent tool calls |

### External Network Connections

The following outbound connections are made during normal operation:

| Destination | Purpose | Data Sent |
|-------------|---------|-----------|
| WhatsApp servers | Message send/receive | Message content (E2E encrypted) |
| Signal servers | Message send/receive | Message content (E2E encrypted) |
| CalDAV provider | Calendar sync | Calendar credentials |
| CardDAV provider | Contact sync | Contact credentials |
| Google APIs (optional) | OAuth login, Calendar sync | OAuth tokens |
| Open-Meteo API (optional) | Weather data & geocoding | Latitude, longitude (public API, no auth) |
| Ollama (localhost) | LLM inference | Prompt text (local only) |

No data is sent to the software author or any analytics service.

### Recommendation for Operators

Operators processing personal data of third parties (e.g., contacts, message contents) should maintain appropriate privacy documentation as required by GDPR, including a record of processing activities (Art. 30 GDPR).

---

## 8. AI Disclosure (EU AI Act Art. 52)

Niles AI is an **AI-powered personal assistant** that uses a locally-hosted
Large Language Model (LLM) for natural language understanding, task execution,
and text generation.

### System Description

| Property | Value |
| -------- | ----- |
| **AI System** | Niles AI (open-source, self-hosted) |
| **Default Model** | Llama 3.1 8B (via Ollama, locally hosted) |
| **Processing** | All LLM inference runs locally — no data sent to cloud AI providers |
| **Purpose** | Personal assistant: calendar management, messaging, task management, web search |
| **Risk Category** | Minimal risk (EU AI Act Art. 6) — personal productivity tool |

### Transparency

- All interactions with Niles AI are AI-generated responses.
- The system executes tool calls (send messages, create events, manage tasks)
  only after explicit user confirmation.
- LLM outputs may be inaccurate, incomplete, or inappropriate.
  Users should verify critical information independently.
- The operator can configure the specific LLM model used via settings.

### Limitations

- Niles AI does not perform autonomous decision-making with legal or
  significant personal effects.
- The system does not perform biometric identification, social scoring,
  or emotion recognition.
- Output quality depends on the locally deployed model and available
  hardware resources.

---

## 9. General Disclaimer

Niles AI is provided **"as is"**, without warranty of any kind, express or implied. See the [MIT License](../LICENSE) for the full warranty disclaimer.

In particular:

1. **Third-party services:** Niles AI integrates with third-party services (WhatsApp, Signal, Vikunja, calendar/contact providers). The availability, terms, and behavior of these services are outside the control of the software author.

2. **Unofficial integrations:** WhatsApp and Signal integrations use unofficial methods. Service disruption or account actions by the respective platform operators may occur without notice.

3. **Legal compliance:** The operator is solely responsible for ensuring that their use of Niles AI complies with applicable laws and regulations, including but not limited to GDPR, telecommunications regulations, and platform terms of service.

4. **LLM output:** Niles AI uses a local large language model for natural language processing. LLM outputs may be inaccurate, incomplete, or inappropriate. The operator should not rely on LLM outputs for critical decisions without independent verification.

5. **No legal advice:** This document provides general information about licenses and risks. It does not constitute legal advice. For specific legal questions, consult qualified legal counsel.