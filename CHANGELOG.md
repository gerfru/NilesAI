# Changelog

All notable changes to this project will be documented in this file.

## [0.2.3](https://github.com/gerfru/NilesAI/compare/niles-core-v0.2.2...niles-core-v0.2.3) (2026-06-15)


### Miscellaneous

* **infra:** repo & container hardening (PR1) ([#167](https://github.com/gerfru/NilesAI/issues/167)) ([7761043](https://github.com/gerfru/NilesAI/commit/77610432fb73ecf0a485ec3bace20547c905305e))

## [0.2.2](https://github.com/gerfru/NilesAI/compare/niles-core-v0.2.1...niles-core-v0.2.2) (2026-06-15)


### Bug Fixes

* **deps:** update dependency langfuse to v4 ([#165](https://github.com/gerfru/NilesAI/issues/165)) ([3464ffb](https://github.com/gerfru/NilesAI/commit/3464ffb03234a6a8a46f98f036f712d66d580c0f))


### Miscellaneous

* **deps:** pin dependencies ([#163](https://github.com/gerfru/NilesAI/issues/163)) ([644ff09](https://github.com/gerfru/NilesAI/commit/644ff097795162efc06ddf83fe66bb86556cded9))
* **deps:** update anthropics/claude-code-action digest to d5726de ([#161](https://github.com/gerfru/NilesAI/issues/161)) ([8684a44](https://github.com/gerfru/NilesAI/commit/8684a44e6501de1985c5017a76153cf27489b295))
* **deps:** update langfuse/langfuse docker tag to v3 ([#164](https://github.com/gerfru/NilesAI/issues/164)) ([c7bc9ff](https://github.com/gerfru/NilesAI/commit/c7bc9fff5ec42ab8c5313683764bc2e0e351581d))

## [0.2.1](https://github.com/gerfru/NilesAI/compare/niles-core-v0.2.0...niles-core-v0.2.1) (2026-06-13)


### Features

* 12-factor compliance — logging, metrics, shutdown, config ([ff5d195](https://github.com/gerfru/NilesAI/commit/ff5d195ebdb7fc1e4cb03ebacf49fb6a0799ea32))
* 12-factor compliance — structured logging, metrics, graceful shutdown ([9e96ec9](https://github.com/gerfru/NilesAI/commit/9e96ec95f58196cf5523da364a3cc719c531878a))
* add Alembic database migrations, remove ad-hoc schema creation ([d755a38](https://github.com/gerfru/NilesAI/commit/d755a38093b55ee71e560fec0f52c129e46a9ff0))
* Add calendar integration workflows ([0db1f51](https://github.com/gerfru/NilesAI/commit/0db1f51f7baf747ff6cc8e6c2f401d94fe5cfcd7))
* add conversation history pruning (M2) ([#131](https://github.com/gerfru/NilesAI/issues/131)) ([fc23463](https://github.com/gerfru/NilesAI/commit/fc234633b21e9851c1391dad0c75249e44b0bf08))
* add daily_overview composite tool for reliable daily briefings ([b9b34b0](https://github.com/gerfru/NilesAI/commit/b9b34b0766a59797fe2c66793696d0b50c25031a))
* add DB pool saturation metrics (M17) ([#100](https://github.com/gerfru/NilesAI/issues/100)) ([815a64d](https://github.com/gerfru/NilesAI/commit/815a64df39238d35678d4de395e53fcc20f1caad))
* add Evolution API license footer and /ui/legal page ([d6ce868](https://github.com/gerfru/NilesAI/commit/d6ce868dc6af2548c26e7524600391d0b6a74462))
* add Evolution API license footer and /ui/legal page ([d4f24c2](https://github.com/gerfru/NilesAI/commit/d4f24c29d1dc9dd78b00ec85592d396a595f1b9b))
* Add feature flags for WhatsApp auto-reply and send tool ([336b87b](https://github.com/gerfru/NilesAI/commit/336b87b48ad7d3b8542150195c0eb3dc9c0ba044))
* add hierarchical chunking for Notion RAG ([fff2b05](https://github.com/gerfru/NilesAI/commit/fff2b0552a351942bbee4d620e0f911937ffd1d9))
* Add hybrid AI Agent workflow for WhatsApp messaging ([13d1448](https://github.com/gerfru/NilesAI/commit/13d14484f4d48516cfe3e6f7b1aef2eedd56af50))
* add LLM benchmark framework for model evaluation ([4fac7eb](https://github.com/gerfru/NilesAI/commit/4fac7ebc44e7842a27d09badc61dc28396ff64ec))
* add LLM benchmark framework with 17 new judge tests ([bc61731](https://github.com/gerfru/NilesAI/commit/bc61731ae87f390e516d785709e69d02604bc9a9))
* add manual briefing test buttons in Settings UI ([dbc1fc7](https://github.com/gerfru/NilesAI/commit/dbc1fc7891d0419921b8a1fde55e7f637343c5fa))
* add Notion RAG knowledge base integration ([3182bc9](https://github.com/gerfru/NilesAI/commit/3182bc94610d9e369987d6286cc47e238d84ae59))
* add opt-in Sentry error tracking (H14, H15) ([#99](https://github.com/gerfru/NilesAI/issues/99)) ([06aa021](https://github.com/gerfru/NilesAI/commit/06aa021840baa4aa09f161268e9e82dc72b0da07))
* add per-message web search toggle button in chat UI ([33fefe4](https://github.com/gerfru/NilesAI/commit/33fefe4f90425e80ee0f34f9fcf0482df185e2b7))
* add PII pre-commit hook for IP/hostname scanning ([75e0bde](https://github.com/gerfru/NilesAI/commit/75e0bde62a5fa898882b871299f5567660d4a5fa))
* add PulseBase service configuration to Caddy and update docker-compose for Garmin API ([7b6d35e](https://github.com/gerfru/NilesAI/commit/7b6d35e27d66a33f800f49851f523bd526c2023e))
* add recherche-mode system prompt instructions ([6b44b78](https://github.com/gerfru/NilesAI/commit/6b44b78b74f547ff2207fc03316fa7f5d1f4005c))
* add retry decorator for transient HTTP failures ([520de47](https://github.com/gerfru/NilesAI/commit/520de4706e078519fc900a321c219d39c88c9b8e))
* add shared proxy network for PulseBase/Caddy routing ([b3ab4a3](https://github.com/gerfru/NilesAI/commit/b3ab4a31232b5aae61269ce23f7d542961f9c69b))
* add Signal integration via signal-cli-rest-api ([611a147](https://github.com/gerfru/NilesAI/commit/611a147a5b93c6a4d51919de25f5f843db8def06))
* add Signal integration via signal-cli-rest-api ([817f862](https://github.com/gerfru/NilesAI/commit/817f862b018428a597610cec5ee9e1ed3f5e2d21))
* add TRANSP (busy/free) field to calendar events ([64184ff](https://github.com/gerfru/NilesAI/commit/64184ffe3e8f441938067851b1183181285d038b))
* add user_id column to calendar_sources table ([1094e8f](https://github.com/gerfru/NilesAI/commit/1094e8f286c61ced798ad78eda2b678be7211b7f))
* add Weather MCP server + Signal disconnect button ([7111667](https://github.com/gerfru/NilesAI/commit/7111667eda1aeb6c78a18089c545a8738f76bc5c))
* add weather tools section to soul.md ([102126e](https://github.com/gerfru/NilesAI/commit/102126e15c06b2db89f765ac503ce6d2fae036bf))
* add web fetch MCP server for URL content extraction ([613d586](https://github.com/gerfru/NilesAI/commit/613d586d8188981d970dd171f120c6c7b3a38b86))
* add web search via SearXNG + MCP ([f58b083](https://github.com/gerfru/NilesAI/commit/f58b083cda3d74364134ff4e9dea953c2108a530))
* **agent:** add source links to Notion context output ([82e04be](https://github.com/gerfru/NilesAI/commit/82e04beabc4433df89a15f1bc4eb1b2d9b6422b8))
* Alembic database migrations ([8788963](https://github.com/gerfru/NilesAI/commit/878896304cd01b874b97773dee2d80fba20fd5dc))
* **api:** unified error response format per CLAUDE.md spec ([0f29f5e](https://github.com/gerfru/NilesAI/commit/0f29f5e6e472e0a39105a2f83cd55e86888ba2a2))
* ask user to choose phone number when contact has multiple ([be9ebd7](https://github.com/gerfru/NilesAI/commit/be9ebd7670846df876ea598161e724ce21082083))
* auto-provision Vikunja accounts on Niles login ([08e730f](https://github.com/gerfru/NilesAI/commit/08e730f4605d0bd89381b34fb93b358984baeaea))
* bypass LLM for multi-phone choice flow ([848de43](https://github.com/gerfru/NilesAI/commit/848de4356bd24c77ebaf82169097660fc0a2c110))
* Caddy HTTPS reverse proxy, security review fixes ([3a0bce5](https://github.com/gerfru/NilesAI/commit/3a0bce54f12ef78b42092c67e26ddf18f7577b6c))
* CalDAV REPORT sync, multi-calendar selection & agent datetime awareness ([bede831](https://github.com/gerfru/NilesAI/commit/bede831f81f42779233ed045d27d0e61a9665706))
* CLAUDE.md compliance — security, CI/CD, Docker hardening ([2671237](https://github.com/gerfru/NilesAI/commit/2671237fecceddf994f9a2c8c3dac1e8c4b0a9e7))
* CLAUDE.md compliance — security, CI/CD, Docker hardening ([0a020bc](https://github.com/gerfru/NilesAI/commit/0a020bc698577982942f9fad499658a887075a8e))
* clean up settings page and add weather to briefings ([33ecaa7](https://github.com/gerfru/NilesAI/commit/33ecaa74168a9fd9d5e25cb4692f659e963c16b3))
* clean up settings page and add weather to briefings ([ff8f6eb](https://github.com/gerfru/NilesAI/commit/ff8f6eb574fdd80d3018e11c7ab10aa2b0331ff7))
* daily & weekly WhatsApp briefing ([13fb6e5](https://github.com/gerfru/NilesAI/commit/13fb6e5e540abc51bb85c6d11665f3ab2963cdf9))
* daily & weekly WhatsApp briefing + merge self-chat docs ([b3669a2](https://github.com/gerfru/NilesAI/commit/b3669a29383830708ffe063b3e1358606b1e1ed0))
* editable CardDAV credentials in Settings UI with manual sync ([c36cb33](https://github.com/gerfru/NilesAI/commit/c36cb33c3607fd0ab086efe5dd0d21086c436d4f))
* **embeddings:** add task prefixes and force re-embed support ([261c1b7](https://github.com/gerfru/NilesAI/commit/261c1b7d1a6f625db4c7ea08f4108a0cf3131219))
* expand recurring CalDAV/ICS events (RRULE) into individual occurrences ([e5bf14f](https://github.com/gerfru/NilesAI/commit/e5bf14f31b9ed76238e3a090811be5a4117c8954))
* fix weekday offset, all-day display, and add birthday calendar priority ([83fe6e4](https://github.com/gerfru/NilesAI/commit/83fe6e4f3d408a1d55478e5abfb798d09bc7a981))
* Google Calendar OAuth sync (Phase B) ([f6c6d4e](https://github.com/gerfru/NilesAI/commit/f6c6d4e801be8b55a9598909f43d7a7e77a9b5d3))
* Google Calendar OAuth sync (Phase B) ([a92e7ca](https://github.com/gerfru/NilesAI/commit/a92e7caae8a0bf11777f5d83c4f5cc0f33ae1de2))
* hierarchical chunking for Notion RAG ([d54109c](https://github.com/gerfru/NilesAI/commit/d54109c85dbfda7bb6e21c5fc94086c842940854))
* implement CardDAV configuration via Settings UI and enhance sync status display ([d7e6329](https://github.com/gerfru/NilesAI/commit/d7e632997f80b4a6ce78333f421574c7b10c62ba))
* implement password reset functionality in CLI ([0ebf323](https://github.com/gerfru/NilesAI/commit/0ebf3230a16e5fc8a62b26971e282713f9ab5cb1))
* implement password reset functionality in CLI ([6be8c9e](https://github.com/gerfru/NilesAI/commit/6be8c9ea748d0fad46bc655d5a577f58e15b9bb9))
* implement Vikunja password sync functionality and related tests ([c197b73](https://github.com/gerfru/NilesAI/commit/c197b736d7bfa71f4e85457d058636cfe7492411))
* improve WhatsApp summarization, add no-delete policy & MCP safety ([8fa2560](https://github.com/gerfru/NilesAI/commit/8fa2560358d9408657250991eb0153cb40cef785))
* keyword-boost scoring for Notion RAG retriever ([4ce036e](https://github.com/gerfru/NilesAI/commit/4ce036ec824f8b1bae47f5e4b1b7931bc5806db1))
* LLM audit — security hardening, agent safety & observability ([#162](https://github.com/gerfru/NilesAI/issues/162)) ([beea88e](https://github.com/gerfru/NilesAI/commit/beea88e82d0461fa644ef417498ccbaf0dbb45f0))
* markdown-aware chunking with heading boundaries and breadcrumbs ([65ea711](https://github.com/gerfru/NilesAI/commit/65ea711318bc398b584685175fe00d8801073e21))
* markdown-aware chunking with heading context and breadcrumbs ([32b40c6](https://github.com/gerfru/NilesAI/commit/32b40c6da97fbcf92f05f5885f498f33c026a3e0))
* Notion RAG knowledge base integration ([aeeb90c](https://github.com/gerfru/NilesAI/commit/aeeb90cd7afcde3194a0f52a2d316b605ea4cb17))
* password auth + admin panel ([c5736df](https://github.com/gerfru/NilesAI/commit/c5736dfecd9b470e34c49329e0c0006ea754f842))
* per-contact multi-phone support via contact_phones table ([38f3fe5](https://github.com/gerfru/NilesAI/commit/38f3fe5ee39109fb20b8d8f36c6b2d832022ad06))
* per-message web search toggle in chat UI ([57a6057](https://github.com/gerfru/NilesAI/commit/57a60571d0ca402417e1248dfb98523dee4d9e28))
* per-user Google Calendar via gws MCP server ([541af02](https://github.com/gerfru/NilesAI/commit/541af02ab5017b4264d3959b1272fdd5b1004524))
* per-user WhatsApp sessions + CardDAV settings UI + CSS build fix ([76a6cc9](https://github.com/gerfru/NilesAI/commit/76a6cc9109c223a216071e7e5a80f16d87853f44))
* per-user WhatsApp sessions via Evolution API + CSS build fix ([21de243](https://github.com/gerfru/NilesAI/commit/21de2433c67b974eb9afde0353d68ffb29bba5bf))
* Rate limiting, .env.example, webhook risk docs, secrets rotation ([ef163a2](https://github.com/gerfru/NilesAI/commit/ef163a22f837f386c45a637425bdf0e1225177e0))
* read WhatsApp messages via Evolution API ([8466442](https://github.com/gerfru/NilesAI/commit/846644228c7ab41f39c3678e0df5242f19fac57b))
* replace API-key login with email/password auth + admin panel ([dd21bb7](https://github.com/gerfru/NilesAI/commit/dd21bb7d772f4eab380113bf14d6f5dccc05c839))
* replace broken SearXNG MCP server, fix WhatsApp history, harden tool-call handling ([a47d54d](https://github.com/gerfru/NilesAI/commit/a47d54da923c18b8e17c46f221307da01d12825d))
* Replace CardDAV live lookup with PostgreSQL contact cache ([5b7096a](https://github.com/gerfru/NilesAI/commit/5b7096a0f423eb1d081f676156664b4ad1417284))
* replace Google CalDAV sync with per-user gws MCP server ([ebad3cc](https://github.com/gerfru/NilesAI/commit/ebad3cccff2875c29b7e3c18fd0a04480b682005))
* scope calendar data layer to user_id ([03fc6bd](https://github.com/gerfru/NilesAI/commit/03fc6bd9c8e0fa7cfe8a47e92c978e5b6c44bf2e))
* scope memory store to per-user (M3) ([#106](https://github.com/gerfru/NilesAI/issues/106)) ([bd2bc49](https://github.com/gerfru/NilesAI/commit/bd2bc498669ecb1c576911b509407441f9f18ada))
* Security hardening -- endpoint auth, Docker non-root, DB port removal ([c73b819](https://github.com/gerfru/NilesAI/commit/c73b819f57ce1499240aaf9fac8cc8ba243a7172))
* Security hardening follow-up -- headers, access logs, memory safeguard, integration tests ([aa3ce47](https://github.com/gerfru/NilesAI/commit/aa3ce4762595abfcb381bf76111ce1767449c951))
* **security:** add CSP violation report endpoint ([2a90a87](https://github.com/gerfru/NilesAI/commit/2a90a8727d68b10eb67a15ef0f28480ce3d1e009))
* **security:** enforce encryption key, deduplicate SSRF, validate URLs ([334bb09](https://github.com/gerfru/NilesAI/commit/334bb09cea2f19b38f5ae8bd149a756ab813157d))
* serve Vikunja via Caddy HTTPS on port 3457 ([bc9d3fa](https://github.com/gerfru/NilesAI/commit/bc9d3fad12d47d4fd2177185d92415eb12318399))
* Signal integration + Weather MCP server ([000dd8d](https://github.com/gerfru/NilesAI/commit/000dd8df038c40adb0b37e859fae5f14c706d48a))
* Stage 1 scaffold – FastAPI core, Docker, pytest, docs restructure ([40d0441](https://github.com/gerfru/NilesAI/commit/40d0441933cc06b75ac72a9b8de32d1ab5acaed1))
* Stage 10 Google OAuth + multi-user + signed sessions ([e489f8e](https://github.com/gerfru/NilesAI/commit/e489f8e686df7b5fc9f662818bd615520fd7bca2))
* Stage 2 WhatsApp loop – receive, process with LLM, reply ([6171e91](https://github.com/gerfru/NilesAI/commit/6171e91411cbac5e57ee226429bf2e40961724e1))
* Stage 3 Memory – persistent key-value store and chat history ([a41825e](https://github.com/gerfru/NilesAI/commit/a41825e25bedbd549d9fde8996ef207d5950fb2f))
* Stage 4 CardDAV sync -- native contact sync replacing n8n ([67f75d4](https://github.com/gerfru/NilesAI/commit/67f75d407e1d0af33f6f871097b499a62588924d))
* Stage 6 MCP integration -- dynamic tool loading from external servers ([6f27ac6](https://github.com/gerfru/NilesAI/commit/6f27ac6442239c2e76dc8bd97db31156f16745a4))
* Stage 7 CalDAV calendar sync -- find and create events ([e15187c](https://github.com/gerfru/NilesAI/commit/e15187c0bf6bcc578878137ddf766231705f635b))
* Stage 9 Web GUI + n8n removal ([6139293](https://github.com/gerfru/NilesAI/commit/6139293b6f48a32147c1090feadcfd3d83c56927))
* store incoming WhatsApp messages in separate inbox table ([a70325f](https://github.com/gerfru/NilesAI/commit/a70325f016850b06de4848b830a2e981e16049a7))
* Switch LLM backend from LM Studio to Ollama (native host) ([00bcbf9](https://github.com/gerfru/NilesAI/commit/00bcbf989abbd00adf725317d9ec0c63dcf3cf20))
* Tailwind CSS migration, SSE streaming, documentation update ([09c7fcb](https://github.com/gerfru/NilesAI/commit/09c7fcb44067c126d6af382cc605030a19d3cb19))
* **tests:** add E2E test suite with FakeLLM pipeline and Claude-as-Judge ([7869423](https://github.com/gerfru/NilesAI/commit/7869423cd8d8872b15e870f23030e81ad8162bdb))
* **tests:** add E2E test suite with FakeLLM pipeline and Claude-as-Judge ([405010f](https://github.com/gerfru/NilesAI/commit/405010f51f33fff566c209996e0ec340ec840fd1))
* **tests:** add integration test suite against real services ([2dff897](https://github.com/gerfru/NilesAI/commit/2dff89799581dbf7b182af8d14a9d2565d47956e))
* unified calendar source management (Phase A) ([e0498e0](https://github.com/gerfru/NilesAI/commit/e0498e0ef1e454b9d271bb116b2b7ae28e283894))
* unified calendar source management (Phase A) ([7715d26](https://github.com/gerfru/NilesAI/commit/7715d26c6a023525f0d1c71e0759db918a4bddef))
* Vikunja auto-provisioning + subdomain ([5ef7ff2](https://github.com/gerfru/NilesAI/commit/5ef7ff26c4704cf2e3982039cc9b7ff259b7db41))
* Vikunja task management with per-user API tokens ([0975dff](https://github.com/gerfru/NilesAI/commit/0975dffb35085f48cfa240056b6d0758f33239be))
* Vikunja task management, text tool-call fallback, deployment docs ([9a362c6](https://github.com/gerfru/NilesAI/commit/9a362c6f6238c760a0e851819fe9d4953603333e))
* web search (SearXNG) + web fetch MCP server ([e30d607](https://github.com/gerfru/NilesAI/commit/e30d6070bd34b70081a76111c7656bc53764cdc7))
* WhatsApp self-chat with "Hey Niles" trigger ([17194fd](https://github.com/gerfru/NilesAI/commit/17194fd1e79f9aa1a9a741e7b4efbb0cf746164f))
* WhatsApp self-chat with Hey Niles trigger ([2efebf3](https://github.com/gerfru/NilesAI/commit/2efebf3b3c65237ff3adce04d6a66fd750d25261))
* WhatsApp self-chat, calendar improvements, TRANSP support ([5514701](https://github.com/gerfru/NilesAI/commit/5514701ab95a0e148fde90b941d8e70d9d990340))
* WhatsApp summarization, no-delete policy & MCP safety ([04144eb](https://github.com/gerfru/NilesAI/commit/04144ebba4383a006d7e7a7bf655d38fbf482e64))
* wire user_id through calendar routes and agent tools ([d2ab543](https://github.com/gerfru/NilesAI/commit/d2ab543f9b6d329feff7822b7b9bb424c43bc821))


### Bug Fixes

* **a11y:** add missing labels, skip-link, and table scopes ([818dd45](https://github.com/gerfru/NilesAI/commit/818dd4509d3758b247290788d8b7f41473571214))
* Add --env-file flag to all docker compose commands ([2d59ca4](https://github.com/gerfru/NilesAI/commit/2d59ca49d4a6416e28f2d4d46f4fbe6dd90087bf))
* add --env-file to status.sh compose command ([07bad82](https://github.com/gerfru/NilesAI/commit/07bad8296b6da7b44ef5c4ee6ea6314252397cff))
* add /.cache tmpfs for Vikunja read-only container ([3ce9804](https://github.com/gerfru/NilesAI/commit/3ce9804d83dab6962bfefb174f0259951859e78f))
* add doi_resolvers to SearXNG settings to fix KeyError crash ([288e1b2](https://github.com/gerfru/NilesAI/commit/288e1b21b5940162e548c98acc08870282452baf))
* add mypy per-module overrides for all pre-existing type errors ([3c56000](https://github.com/gerfru/NilesAI/commit/3c56000ddb71cf6d730bc5b0b3315efb4e8181de))
* add ruff to dev dependencies for CI pipeline ([99793d8](https://github.com/gerfru/NilesAI/commit/99793d87f97081312e6c032a26ada2c874f1cf1c))
* add SSRF protection to CardDAV test_connection endpoint ([#140](https://github.com/gerfru/NilesAI/issues/140)) ([d1805ee](https://github.com/gerfru/NilesAI/commit/d1805ee1271b88f64aea7ea085b3e3f35a7db52b))
* add system prompt instruction for Notion context injection ([e475a9e](https://github.com/gerfru/NilesAI/commit/e475a9edc775922f6200b52d859cfe770eca66a6))
* add Tailscale hostname to Evolution API and Vikunja Caddy blocks ([6441836](https://github.com/gerfru/NilesAI/commit/6441836ffb70d9635d24cfdef090740d7a91fb85))
* add user context to /chat endpoint and message length limit (C1, L1) ([#125](https://github.com/gerfru/NilesAI/issues/125)) ([48ebdbe](https://github.com/gerfru/NilesAI/commit/48ebdbedb0f5c2ab1c77444cb0f6f30c92d448f2))
* address all 13 PR review issues ([496f0ce](https://github.com/gerfru/NilesAI/commit/496f0cee3a4c8c7f66d366a70858f3bf35036959))
* address all 5 PR review findings ([862dfe0](https://github.com/gerfru/NilesAI/commit/862dfe0bd18e1878e2de73c68435880962575419))
* address all 5 PR review findings ([42e1171](https://github.com/gerfru/NilesAI/commit/42e11714d99120ceb6931a97357118992981f2e7))
* address all 6 PR review findings ([09cede4](https://github.com/gerfru/NilesAI/commit/09cede4e8f4409b8733cd7a1b1926c80fdaea121))
* address all 6 PR review findings + clean up .env.example ([623580a](https://github.com/gerfru/NilesAI/commit/623580a3ed1404a6ddbe0347b5ae75784fccd282))
* address PR [#32](https://github.com/gerfru/NilesAI/issues/32) review — CSRF, admin gates, DB verification, CLI security ([5880f48](https://github.com/gerfru/NilesAI/commit/5880f482c6afb53675e2b23eebe3cb375cf7bfbe))
* address PR [#33](https://github.com/gerfru/NilesAI/issues/33) review — auth, cardinality, token tracking, middleware order ([be758db](https://github.com/gerfru/NilesAI/commit/be758dbbf2cf5b61e68e06279f4e8961422281de))
* address PR [#34](https://github.com/gerfru/NilesAI/issues/34) review — Vikunja port, comment alignment ([d25c3d2](https://github.com/gerfru/NilesAI/commit/d25c3d206c9a45028f61e94b5209c88f3cb75ccb))
* address PR [#35](https://github.com/gerfru/NilesAI/issues/35) review — KISS refactoring + security + race guard ([a4874d4](https://github.com/gerfru/NilesAI/commit/a4874d40d268f74af89334da740ba10fc28c8633))
* Address PR [#4](https://github.com/gerfru/NilesAI/issues/4) review feedback ([6efaea9](https://github.com/gerfru/NilesAI/commit/6efaea9d89b75eb36e5eb66b7b8b67cb6c5fc04b))
* address PR [#40](https://github.com/gerfru/NilesAI/issues/40) review — SSRF redirect chain and weak secret key ([a2a0364](https://github.com/gerfru/NilesAI/commit/a2a0364db411ad0d39427f02d7d0706d7a40ebb6))
* address PR [#41](https://github.com/gerfru/NilesAI/issues/41) review — supply chain, Docker hardening, readiness probe ([59350af](https://github.com/gerfru/NilesAI/commit/59350af7757142bd5854284e457cff42f314f268))
* address PR [#42](https://github.com/gerfru/NilesAI/issues/42) review — server guard, prompt scope, CSS layers ([38480c1](https://github.com/gerfru/NilesAI/commit/38480c1d58bba19330a165635d6f5248fe05f0f4))
* address PR [#43](https://github.com/gerfru/NilesAI/issues/43) review — guards, imports, dead code ([2ad8936](https://github.com/gerfru/NilesAI/commit/2ad8936e617fd20f24ed9b13ccae9329baca438b))
* address PR [#44](https://github.com/gerfru/NilesAI/issues/44) review — error handling, cleanup, exports ([71f6c6a](https://github.com/gerfru/NilesAI/commit/71f6c6a748e7e3b74d771ced2485f9590e8e0632))
* address PR [#46](https://github.com/gerfru/NilesAI/issues/46) review findings ([be66113](https://github.com/gerfru/NilesAI/commit/be6611307d33efcd66b5fc1c91fba13a812ead43))
* address PR [#47](https://github.com/gerfru/NilesAI/issues/47) review findings ([bbae91b](https://github.com/gerfru/NilesAI/commit/bbae91b33090f23e44441e7060d33473a06f6b00))
* Address PR [#5](https://github.com/gerfru/NilesAI/issues/5) review feedback ([97afcca](https://github.com/gerfru/NilesAI/commit/97afcca7716682e31f719815479176f3985c75dd))
* address PR [#50](https://github.com/gerfru/NilesAI/issues/50) review findings ([c06c487](https://github.com/gerfru/NilesAI/commit/c06c487544bc89870decf29257c53fe162440291))
* address PR [#52](https://github.com/gerfru/NilesAI/issues/52) review findings ([3800d72](https://github.com/gerfru/NilesAI/commit/3800d72b4b14604a3306084aab7ff243ab2b474f))
* address PR [#54](https://github.com/gerfru/NilesAI/issues/54) review findings ([eb54835](https://github.com/gerfru/NilesAI/commit/eb54835eb7edae77e98cae5f442782e934b2cf76))
* Address PR [#6](https://github.com/gerfru/NilesAI/issues/6) review feedback ([ad72f56](https://github.com/gerfru/NilesAI/commit/ad72f565f153a862c9567904e24a9bad7fa79db8))
* address PR [#60](https://github.com/gerfru/NilesAI/issues/60) review findings ([1e2aed1](https://github.com/gerfru/NilesAI/commit/1e2aed105c6cead67ea723443e134b8fbef24734))
* address PR [#61](https://github.com/gerfru/NilesAI/issues/61) review findings ([1afd611](https://github.com/gerfru/NilesAI/commit/1afd611d10ae775ff120a251112011000ef89ea7))
* address PR [#62](https://github.com/gerfru/NilesAI/issues/62) review findings ([f0750ff](https://github.com/gerfru/NilesAI/commit/f0750ffa86ce7ceafd75967b3e1fbaf750ae276f))
* address PR review findings ([43c3799](https://github.com/gerfru/NilesAI/commit/43c37994b850e8f96e7e3b758bc942731609d0fc))
* address PR review findings ([f8b08e4](https://github.com/gerfru/NilesAI/commit/f8b08e4129b2d79803396ebc835c367292acbac8))
* address PR review findings ([2b4c856](https://github.com/gerfru/NilesAI/commit/2b4c856642886ef9ccdc1d33ca9e7d86005e1aa0))
* address PR review findings ([d2ea0b3](https://github.com/gerfru/NilesAI/commit/d2ea0b3acb74e9f6a83a956be1a1b24b6a4a612b))
* address PR review findings for action-layer extraction ([10ed824](https://github.com/gerfru/NilesAI/commit/10ed8246f9f6e9846fe3ec7ef3f374a9bdf379a1))
* address PR review findings for hierarchical chunking ([19f653b](https://github.com/gerfru/NilesAI/commit/19f653b61014df5dc366e8da5c71c416a62ddef5))
* address PR review findings for keyword-boost and chunking ([a0ea2b7](https://github.com/gerfru/NilesAI/commit/a0ea2b7e1cb0e26c01d2163c2764311573067404))
* address remaining PR [#44](https://github.com/gerfru/NilesAI/issues/44) review items ([6023f10](https://github.com/gerfru/NilesAI/commit/6023f101975012fae6a4bcf5e130615047af0989))
* **agent:** disable all tools when Notion toggle is active ([6e083ea](https://github.com/gerfru/NilesAI/commit/6e083eaf8cb37cf7efef09765795ddfd7849cee5))
* **agent:** improve Notion context prompt for small models ([0383d5f](https://github.com/gerfru/NilesAI/commit/0383d5fa3ec69f3a5b17846c9df9da6899633683))
* **agent:** use minimal RAG prompt for Notion mode ([ce0457b](https://github.com/gerfru/NilesAI/commit/ce0457b549d3ec95c9ee84fd7dceae8ef9e3abe9))
* **auth:** remove token response bodies from error logs ([3afba20](https://github.com/gerfru/NilesAI/commit/3afba206ffcdeb2753a574d43087ed886bff96b1))
* broaden JSON repair for more llama3.1 malformation variants ([979c4b8](https://github.com/gerfru/NilesAI/commit/979c4b8d5ec790073559bddd728bd93cc11ca8b0))
* CalDAV create_event discovers collection before PUT ([44ac3e7](https://github.com/gerfru/NilesAI/commit/44ac3e7a87b1b81fd5c18a71981c01c183aabf61))
* Calendar tool not used by LLM ([e12c840](https://github.com/gerfru/NilesAI/commit/e12c8402913d06f89b6924ab4e4a1488924d33ac))
* cap login rate limiter to prevent memory exhaustion ([#142](https://github.com/gerfru/NilesAI/issues/142)) ([64bcb83](https://github.com/gerfru/NilesAI/commit/64bcb8366f367bd576e455446bd0e5af92db9064))
* CardDAV contact lookup with namespace-agnostic regex ([ce0b24d](https://github.com/gerfru/NilesAI/commit/ce0b24d66a302bb78adcc95bb8832a9ac0cd8586))
* cast limit arg to int — LLM may pass string instead of int ([ea4d0b0](https://github.com/gerfru/NilesAI/commit/ea4d0b08297dbb23a07ca88309ab25c125897e9c))
* **ci:** extend bandit skip list for rules covered by ruff S-rules ([3b4d994](https://github.com/gerfru/NilesAI/commit/3b4d994711f33b6e47d4a7bb2e3964b42b5792d0))
* **ci:** skip bandit B101/B608 (handled by ruff S-rules with per-file-ignores) ([8cc143b](https://github.com/gerfru/NilesAI/commit/8cc143b9302ef23968879c0ab68e269ae7df8a1b))
* cleanup expired pending confirmations and phone choices (H2) ([#127](https://github.com/gerfru/NilesAI/issues/127)) ([1429fc5](https://github.com/gerfru/NilesAI/commit/1429fc5e6c9d793a76745cf340b372fb9a6e3aab))
* coerce MCP tool argument types from LLM string values ([3967a6d](https://github.com/gerfru/NilesAI/commit/3967a6df7371d6b4da52727d66e1310dc59e742c))
* contact search with multi-word names (e.g. "Thomas Brunner") ([48eb13b](https://github.com/gerfru/NilesAI/commit/48eb13bafc7b26c93b58b71aec9198fa9b151e31))
* CSS-driven search toggle via aria-pressed attribute ([7bd6e09](https://github.com/gerfru/NilesAI/commit/7bd6e094778c142934b335285e208a6041b9be17))
* decouple credential encryption gate from LOG_LEVEL ([#141](https://github.com/gerfru/NilesAI/issues/141)) ([7902308](https://github.com/gerfru/NilesAI/commit/7902308bf1c200907ea7bd9eb9d638ad4667dc4f))
* disable thinking mode for summaries, make auto-sync optional ([092e7f9](https://github.com/gerfru/NilesAI/commit/092e7f942b884eac093f6f4c5a22caf846f03eb4))
* Docker postgres port env var guard ([8f97a61](https://github.com/gerfru/NilesAI/commit/8f97a61f19355471e37dc9ee9e453b1fb43fb3e4))
* **docker:** add resource limits and named volume (M1, M2) ([7347413](https://github.com/gerfru/NilesAI/commit/7347413a7f7d6091befb76a9957f4ff7d0075f14))
* **docker:** modernize Dockerfile to uv sync --frozen with venv (H12) ([d8c211d](https://github.com/gerfru/NilesAI/commit/d8c211da0a300224a11f0a87a10c481533cf6492))
* **embeddings:** switch to nomic-embed-text-v2-moe for cross-language retrieval ([662138f](https://github.com/gerfru/NilesAI/commit/662138ff15ac5129cf4e4085f31ae72a582d0b43))
* enable Evolution API message storage for findMessages ([8186dfb](https://github.com/gerfru/NilesAI/commit/8186dfbbcd738437510a355cac07da86b8b63bf2))
* enforce single worker process at startup (H3) ([#128](https://github.com/gerfru/NilesAI/issues/128)) ([f4b167b](https://github.com/gerfru/NilesAI/commit/f4b167b84c8059281f2ed0c9351eac3c75b5aa7a))
* export LLM_BASE_URL for local Ollama connectivity ([9d96b5b](https://github.com/gerfru/NilesAI/commit/9d96b5b62299e54277b4b61c731fe31e194b1dc5))
* extract ISO date from malformed LLM tool args ([b42b25a](https://github.com/gerfru/NilesAI/commit/b42b25a973a97a27fdbb5779e308afbef2d443c5))
* fetch last 30 days from Evolution API, not oldest N records ([8f7416c](https://github.com/gerfru/NilesAI/commit/8f7416c1a246e52f93b008664ef9ec02692b7f23))
* find_by_phone strips non-digits before comparing with contact_phones ([a0b8e2e](https://github.com/gerfru/NilesAI/commit/a0b8e2efa7277357d875a4248f3dd5b2e16fda7d))
* format WhatsApp messages as readable chat transcript for LLM ([fbab849](https://github.com/gerfru/NilesAI/commit/fbab8492452672ba897322cb4ca118c99696096f))
* get_whatsapp_messages fallback — resolve name→phone via contacts ([192255a](https://github.com/gerfru/NilesAI/commit/192255ad2895d29a93d4f7e66dc0aad034449492))
* Google OAuth verified_email field + remove auto-review workflow ([13f2dd3](https://github.com/gerfru/NilesAI/commit/13f2dd3eb31eeaec502d4a92290dd5a9cd0164ed))
* Grant write permissions to Claude Code GitHub Actions ([9fb2cf5](https://github.com/gerfru/NilesAI/commit/9fb2cf565f091a6dacfae29e76e73767230cd2c1))
* guard calendar filter against small-LLM misuse ([bf45e01](https://github.com/gerfru/NilesAI/commit/bf45e01eadec49fbcc6710b17df60d7c7a689633))
* guard calendar filter against small-LLM misuse ([f0eaa2d](https://github.com/gerfru/NilesAI/commit/f0eaa2d103d0d6a375eb03a0d22f381a66197d03))
* harden stale session handling + remove sync feature flags ([b45b738](https://github.com/gerfru/NilesAI/commit/b45b7388bed118319ca12fd0e3a03608a674aeac))
* harden tool-call handling and add model selector dropdown ([d7f9819](https://github.com/gerfru/NilesAI/commit/d7f9819655ffddb2ed6f830f93e706c5e0a5b408))
* ICS parser — handle property params, Windows timezones, redirects ([d20348f](https://github.com/gerfru/NilesAI/commit/d20348ff81075b6f2e3f028820283db8d6834ceb))
* improve calendar query accuracy for small LLMs ([a84ab51](https://github.com/gerfru/NilesAI/commit/a84ab5187d4058fbba53845052f23752f30d5922))
* improve multi-phone choice display format ([a27c000](https://github.com/gerfru/NilesAI/commit/a27c0007dade6552c50ccfc9ca995adbb92f71d2))
* Improve tool descriptions for better LLM tool selection ([44f0360](https://github.com/gerfru/NilesAI/commit/44f036069fe6aaa358ca819cade8ec0213bad9cd))
* improve WhatsApp message summary prompting in soul.md ([36466fa](https://github.com/gerfru/NilesAI/commit/36466facf7e726b1f68b32159ee50899ffd44c12))
* include MCP tools in text-based tool call fallback ([1a01d75](https://github.com/gerfru/NilesAI/commit/1a01d756d2b0f2f369891626ff11b6142659a0d1))
* include search profile in stop, build, and status scripts ([cdf7146](https://github.com/gerfru/NilesAI/commit/cdf71463286a3b5fed4d3e40ceea0f3b78efa0ec))
* **lint:** set ruff target-version py314, update pre-commit hooks ([64af586](https://github.com/gerfru/NilesAI/commit/64af586941d40b9561357a80ed3a6366c424e17e))
* lock in notion_disconnect, remove stale scheduler on reconnect ([45dc0f7](https://github.com/gerfru/NilesAI/commit/45dc0f719e76afd419c7b6258a8fe9244cc9bf59))
* macOS compatibility for benchmark script ([d95a133](https://github.com/gerfru/NilesAI/commit/d95a133a74f3680c4e7c871622b7bad8be2b8662))
* make benchmark script compatible with macOS bash 3.2 ([5043d06](https://github.com/gerfru/NilesAI/commit/5043d06f1ca38ea34ba8bf22bfed87c636764849))
* make httpx client parameters required, remove fallback defaults (M5) ([#134](https://github.com/gerfru/NilesAI/issues/134)) ([17c1f0f](https://github.com/gerfru/NilesAI/commit/17c1f0ffd48418dab6173c637fd4033622108720))
* make phone country code configurable (M1) ([#130](https://github.com/gerfru/NilesAI/issues/130)) ([a67f96e](https://github.com/gerfru/NilesAI/commit/a67f96e6442c00c06ab06f5ad16ccd222233adb8))
* make search toggle visually distinct on click ([3c636f5](https://github.com/gerfru/NilesAI/commit/3c636f5790e0f986e5da27884be7551e53cc1203))
* merge process env into MCP subprocess environment ([445ef5b](https://github.com/gerfru/NilesAI/commit/445ef5b55e7c3b49f481acb5b611af6d02d1505c))
* model dropdown renders as plain text on settings page ([2922996](https://github.com/gerfru/NilesAI/commit/292299647b99902bf08074997f0d1eb4a8641a3b))
* model dropdown renders as plain text on settings page ([c5ee2e3](https://github.com/gerfru/NilesAI/commit/c5ee2e301299859f3b39893fbd37da0b2e64869e))
* move Kontakte (CardDAV) above Administration divider ([d2e43d3](https://github.com/gerfru/NilesAI/commit/d2e43d38a39960d1e5d953007b0fd397986deda9))
* narrow CalDAV sync inner loop exception handling (M4) ([#133](https://github.com/gerfru/NilesAI/issues/133)) ([bbd778d](https://github.com/gerfru/NilesAI/commit/bbd778d401831bbbe71f729366f408e387e680a7))
* narrow exception handling, add TypedDicts, complete AppState Protocol ([#108](https://github.com/gerfru/NilesAI/issues/108)) ([458bbd4](https://github.com/gerfru/NilesAI/commit/458bbd4b1f3b587f85d995b5631dc60210f9f139))
* normalize phone number before sending WhatsApp message ([04d2bb9](https://github.com/gerfru/NilesAI/commit/04d2bb939fd1d8a01c5f3bddd3cb463fd605c632))
* Notion RAG quality improvements and model upgrade ([d89ef77](https://github.com/gerfru/NilesAI/commit/d89ef775fcd6d760cccecf2b6ef25769509a78d1))
* only log "reply sent" on actual success, not on send failure ([14aeee5](https://github.com/gerfru/NilesAI/commit/14aeee5540ceacc72d6ef40019a25c791fc2b35b))
* patch Trivy CVEs — upgrade fastmcp 3.2.4 and openssl ([4bb4633](https://github.com/gerfru/NilesAI/commit/4bb46331ffebafe3a5ad49315978de7df388945b))
* pin fastmcp&lt;3 to fix SearXNG MCP server startup crash ([00af141](https://github.com/gerfru/NilesAI/commit/00af1411a8d6de3da77344d09b357189898ed6e8))
* PR [#13](https://github.com/gerfru/NilesAI/issues/13) re-review -- CSP/hx-vals, frame-ancestors, restart hint ([a8605ea](https://github.com/gerfru/NilesAI/commit/a8605eaa60c7314ff5b67541cbd475cf6421ce4d))
* PR [#13](https://github.com/gerfru/NilesAI/issues/13) review feedback -- all 17 security and quality items ([3f18d69](https://github.com/gerfru/NilesAI/commit/3f18d69effd781dcad9ba4ca0456e64162ab7a86))
* PR [#14](https://github.com/gerfru/NilesAI/issues/14) security review -- all 8 findings addressed ([efb6d45](https://github.com/gerfru/NilesAI/commit/efb6d451c00626e6208a6cb9bec217a5bf99d53f))
* PR [#15](https://github.com/gerfru/NilesAI/issues/15) re-review -- CSP, tests, code quality, docker security ([0a0b0fe](https://github.com/gerfru/NilesAI/commit/0a0b0fe921ef88adc4e8f879532e9238cfbc8e22))
* PR [#15](https://github.com/gerfru/NilesAI/issues/15) security review -- all 6 findings addressed ([2743b85](https://github.com/gerfru/NilesAI/commit/2743b85fe3c0f828cd8b60ead3d64e461337dc1f))
* PR [#15](https://github.com/gerfru/NilesAI/issues/15) third review -- stale config, empty selection, discovery cache ([14e8277](https://github.com/gerfru/NilesAI/commit/14e8277fca285f05bae0797521716af98b98156d))
* PR [#16](https://github.com/gerfru/NilesAI/issues/16) 3rd review -- all 7 findings addressed ([9e443a7](https://github.com/gerfru/NilesAI/commit/9e443a7bebc07b99cb25cb6975d993fba12f11f7))
* PR [#16](https://github.com/gerfru/NilesAI/issues/16) 4th review -- all 4 findings addressed ([0728ad0](https://github.com/gerfru/NilesAI/commit/0728ad088828ed3400fd9ea2d34e6a63ab64599b))
* PR [#16](https://github.com/gerfru/NilesAI/issues/16) 5th review -- CSP inline styles + empty response logging ([3a1fe12](https://github.com/gerfru/NilesAI/commit/3a1fe12ec2e82e49391bc8a3701446b29b860c8c))
* PR [#16](https://github.com/gerfru/NilesAI/issues/16) re-review -- all 8 findings addressed ([3b31d5c](https://github.com/gerfru/NilesAI/commit/3b31d5cb1a43ef8e00cdb096a390e4eefe311c70))
* PR [#16](https://github.com/gerfru/NilesAI/issues/16) review -- all 15 findings addressed ([d3b8fa1](https://github.com/gerfru/NilesAI/commit/d3b8fa1150e3fe30f55d0738e525958b548f4a21))
* PR [#17](https://github.com/gerfru/NilesAI/issues/17) 2nd review -- rename misleading test ([bf4a5b8](https://github.com/gerfru/NilesAI/commit/bf4a5b888ce9e452bb60d172c373f09b44a05300))
* PR [#17](https://github.com/gerfru/NilesAI/issues/17) review -- all 6 findings + UX thinking indicator ([3e05411](https://github.com/gerfru/NilesAI/commit/3e054116e289c7f66e1a8a6b31ddc1bb6b67caad))
* PR [#18](https://github.com/gerfru/NilesAI/issues/18) 2nd review -- all 4 findings addressed ([4741524](https://github.com/gerfru/NilesAI/commit/4741524cac99160581cab93086dd6d0a033b3560))
* PR [#18](https://github.com/gerfru/NilesAI/issues/18) review -- all 11 findings addressed ([fdd88fc](https://github.com/gerfru/NilesAI/commit/fdd88fcdef91eaa695213674a63da834629f0d30))
* PR [#20](https://github.com/gerfru/NilesAI/issues/20) review -- all 6 findings addressed ([24be9a1](https://github.com/gerfru/NilesAI/commit/24be9a100d0ff5585fedf0585e52e5f4b89545ad))
* PR [#21](https://github.com/gerfru/NilesAI/issues/21) review -- all 9 findings addressed ([7e769a8](https://github.com/gerfru/NilesAI/commit/7e769a8d8214707d50630708ab5e729e56e6ae30))
* PR [#22](https://github.com/gerfru/NilesAI/issues/22) review -- all 5 findings addressed ([096a9d0](https://github.com/gerfru/NilesAI/commit/096a9d0e6ac209655e6700a949a1dab23e565033))
* PR [#22](https://github.com/gerfru/NilesAI/issues/22) review — pop-before-validate, TTL, instance warning ([70402be](https://github.com/gerfru/NilesAI/commit/70402be88bf4d93f1b1c5beae6fed9bb0139f0f2))
* PR [#22](https://github.com/gerfru/NilesAI/issues/22) review — scheduler gap, LIKE injection, source cache, contact triggers ([7523675](https://github.com/gerfru/NilesAI/commit/75236757fe448bc1db68aea714feff69ffbc969a))
* PR [#22](https://github.com/gerfru/NilesAI/issues/22) review — sync_contacts guard + redundant uid check ([754b9d4](https://github.com/gerfru/NilesAI/commit/754b9d4206c3568a56c1b38e3ed889b418d57c11))
* PR [#23](https://github.com/gerfru/NilesAI/issues/23) re-review — public URL, root comment, Caddyfile IPs, registration ([eef6b96](https://github.com/gerfru/NilesAI/commit/eef6b96229ce5b063c66115016dd41fdc2c08386))
* PR [#23](https://github.com/gerfru/NilesAI/issues/23) review — SSRF, typo, buffering, due_date, dedup ([a95369e](https://github.com/gerfru/NilesAI/commit/a95369e11ec49439e422b6b6a862cfcd30681830))
* PR [#24](https://github.com/gerfru/NilesAI/issues/24) review — word boundary, self-check guard, webhook config, DB index ([3f89378](https://github.com/gerfru/NilesAI/commit/3f89378beded2e0dc348c466f8ea90669a72491d))
* PR [#25](https://github.com/gerfru/NilesAI/issues/25) review — CREATE TABLE transp, sync constants, regex tz, brittle test ([f2cba06](https://github.com/gerfru/NilesAI/commit/f2cba06647e2ac0235a699ae63e55ac9a00e13c2))
* PR [#25](https://github.com/gerfru/NilesAI/issues/25) review — DDL transp consistency, strict RFC 5545 TRANSP check ([21161e4](https://github.com/gerfru/NilesAI/commit/21161e400bc818e035963efe8dca395867111e9a))
* PR [#26](https://github.com/gerfru/NilesAI/issues/26) review — umlaut consistency, guard tests, known limitation ([66b6f0c](https://github.com/gerfru/NilesAI/commit/66b6f0c85e5a8a43700f5226e80c2c115bed9412))
* PR [#27](https://github.com/gerfru/NilesAI/issues/27) review — double API call, UTC date, time validation ([4a62919](https://github.com/gerfru/NilesAI/commit/4a629191843c4cc83fe416194fa66a8be78def18))
* PR [#27](https://github.com/gerfru/NilesAI/issues/27) review — false-success toast, overdue+today dedup ([1325714](https://github.com/gerfru/NilesAI/commit/132571401460a6f3f84a2f43d0bf938da816846e))
* PR [#29](https://github.com/gerfru/NilesAI/issues/29) review — group guard, int-cast messageTimestamp, debug log ([63315ff](https://github.com/gerfru/NilesAI/commit/63315ff02cacd9b09707326b774860afe6adc8b9))
* PR [#29](https://github.com/gerfru/NilesAI/issues/29) review — guard debug log, filter WA tools when unconfigured ([8411b70](https://github.com/gerfru/NilesAI/commit/8411b7015ec2bfbe3aebb9317f2709cf44d42fde))
* PR [#29](https://github.com/gerfru/NilesAI/issues/29) review — normalize phone, remove dead code, sort messages ([2325b13](https://github.com/gerfru/NilesAI/commit/2325b131a75a66892c416014158e7ee6ac2ee0a2))
* PR [#30](https://github.com/gerfru/NilesAI/issues/30) review — log count, clear prefix, UTC dates, test coverage ([42b24a9](https://github.com/gerfru/NilesAI/commit/42b24a95e94a9652753f46b4674ed7debe7ccbfc))
* PR [#30](https://github.com/gerfru/NilesAI/issues/30) review round 2 — all remaining observations ([ba07fbf](https://github.com/gerfru/NilesAI/commit/ba07fbf8a4a220c4be2a07afa54e436c72f29eda))
* PR [#31](https://github.com/gerfru/NilesAI/issues/31) review — translate comments, fix readability, add install note ([2c63aa1](https://github.com/gerfru/NilesAI/commit/2c63aa16580ed48879f496f2f3fa7886ff437e0d))
* PR review feedback -- security hardening, timeouts, validation ([18455c5](https://github.com/gerfru/NilesAI/commit/18455c5dbe9e769ed9e78107803f439e64b1085f))
* PR review feedback -- security, config, scheduler hardening ([c15593c](https://github.com/gerfru/NilesAI/commit/c15593ca25777ae44c6e00289d230a4ce90fa734))
* preserve char positions in code block masking ([a4015d9](https://github.com/gerfru/NilesAI/commit/a4015d9460488a5ed135143da7ae7abaae08c396))
* prevent LLM from hallucinating phone numbers ([fdbeddc](https://github.com/gerfru/NilesAI/commit/fdbeddc1afec2bc499760cfb106c2e6c1729a150))
* prevent self-chat echo loop + catch ValueError in all WA methods ([d7e6bc1](https://github.com/gerfru/NilesAI/commit/d7e6bc1765a8af59dd9a36c4e97feaf4ae4bddf2))
* protect LLM hot-reload with asyncio.Lock (H4) ([#129](https://github.com/gerfru/NilesAI/issues/129)) ([69f30a3](https://github.com/gerfru/NilesAI/commit/69f30a3ce4cf1fe2f5c97a64c99136def3de61a3))
* protect Vikunja _in_flight set with asyncio.Lock (M3) ([#132](https://github.com/gerfru/NilesAI/issues/132)) ([502d58f](https://github.com/gerfru/NilesAI/commit/502d58faf97d00adc1ddeddce68948f0bd7955cc))
* **quality:** narrow exception types, fix comma-syntax, add type:ignore comments ([#155](https://github.com/gerfru/NilesAI/issues/155)) ([6c0e554](https://github.com/gerfru/NilesAI/commit/6c0e5548b520c1f6e61d2ceeb432ecdfdea7c4a8))
* remove pool stats from unauthenticated /health endpoint (L2) ([#135](https://github.com/gerfru/NilesAI/issues/135)) ([88386c6](https://github.com/gerfru/NilesAI/commit/88386c6236d57aac800dcfc81cb65dcdc68e6bd5))
* remove stray docstring, add echo-guard observability + worker note ([4e0ce59](https://github.com/gerfru/NilesAI/commit/4e0ce59599fd62007040de4d28914840f00e192c))
* repair malformed JSON from llama3.1 text-based tool calls ([40e20dc](https://github.com/gerfru/NilesAI/commit/40e20dce02b5ef9ae792d01ba021851f13405d15))
* replace fragile source .env with grep in status.sh ([8be0e2b](https://github.com/gerfru/NilesAI/commit/8be0e2be3f0828c72eb95db96ba33f02c5f2597f))
* replace trivy-action with direct apt install ([5b01cda](https://github.com/gerfru/NilesAI/commit/5b01cda6f78c17ea14cd34fa7eb845204123b58c))
* **retriever:** raise similarity threshold and handle no-results ([ecdf1ed](https://github.com/gerfru/NilesAI/commit/ecdf1ed270e3937e6e315a63071dc6a37bff8c59))
* review Phase 1 — security hardening & Docker modernization ([e555801](https://github.com/gerfru/NilesAI/commit/e55580184af2b2129e0027ffcbf28d5eab3e1b0b))
* scope calendar sources and events to user_id ([5fb5cbb](https://github.com/gerfru/NilesAI/commit/5fb5cbb1241b4381275c2b26e203d1028f279c42))
* scope contact lookups to user_id (C2) ([#124](https://github.com/gerfru/NilesAI/issues/124)) ([7e794cb](https://github.com/gerfru/NilesAI/commit/7e794cb984e21d47a339dc4dde0a22377b96b56a))
* **scripts:** use python3.14 + pip upgrade for venv creation ([73bdac4](https://github.com/gerfru/NilesAI/commit/73bdac405028dd2099dc4f9279065f0aeeaec6db))
* security hardening (ready, OAuth, error sanitization, crypto docs) ([#144](https://github.com/gerfru/NilesAI/issues/144)) ([dca990b](https://github.com/gerfru/NilesAI/commit/dca990b7ff9b604682569d4a351478a6537d573d))
* **security:** fail-closed SSRF check on DNS failure (L6) ([b54bec9](https://github.com/gerfru/NilesAI/commit/b54bec903f9d517b7c260b0ce8c198d304be61bf))
* **security:** require admin for notion_connect and briefing_test (M4, M5) ([8fd04f4](https://github.com/gerfru/NilesAI/commit/8fd04f47c4f9b30951edd21c0e0c797093002982))
* **security:** restrict claude workflow to repo owner, broaden .env ignore ([#158](https://github.com/gerfru/NilesAI/issues/158)) ([f15bdf2](https://github.com/gerfru/NilesAI/commit/f15bdf2dd156d0cc2a7eb504f2cab91294c6fc13))
* **security:** SSRF, config validation, rate-limiter trusted proxy, OAuth ([#154](https://github.com/gerfru/NilesAI/issues/154)) ([5feee86](https://github.com/gerfru/NilesAI/commit/5feee86ed3f2020cfc22fe711aae2f152b744dd2))
* shared httpx client, race guard, api_url None check ([48c74b6](https://github.com/gerfru/NilesAI/commit/48c74b68f50aae2d0aa1e21b038411a9f9f7ac34))
* simplify MCP tool schemas for local LLM compatibility ([de145b8](https://github.com/gerfru/NilesAI/commit/de145b8d003c134177b337836710120548b4d2f0))
* skip LLM call for incoming WhatsApp messages ([8db46ea](https://github.com/gerfru/NilesAI/commit/8db46eaa4f3aa9687b003bb5d3f242116a8e7428))
* skip LLM call for incoming WhatsApp messages from others ([29a6597](https://github.com/gerfru/NilesAI/commit/29a65971da443a62b15b88f851c75736ad91c79d))
* static asset cache busting and search toggle visual feedback ([#146](https://github.com/gerfru/NilesAI/issues/146)) ([8c4d4ff](https://github.com/gerfru/NilesAI/commit/8c4d4ff681a3fcc968cc326f1f2c46120679ff0f))
* strip @ prefix from contact param in get_whatsapp_messages ([0276e22](https://github.com/gerfru/NilesAI/commit/0276e2285458b943a52587a3fc88993a63660046))
* support WhatsApp LID addressing in findMessages and webhook ([1381832](https://github.com/gerfru/NilesAI/commit/1381832d544a382c4caea04d28f6188d8528d4bd))
* suppress search_notion tool when Notion toggle is active ([c6474de](https://github.com/gerfru/NilesAI/commit/c6474de390b123f29cd18990106ac50b5908018e))
* switch Vikunja from subdomain to port 3457 ([a3010c4](https://github.com/gerfru/NilesAI/commit/a3010c47c7d1ed3a5aca480d9b1c2f7993d92547))
* **tests:** clear CREDENTIAL_ENCRYPTION_KEY in test env ([8060295](https://github.com/gerfru/NilesAI/commit/8060295b0dab6ca341fa03add69bae74dbd4a73a))
* **tests:** handle empty POSTGRES_HOST_PORT in e2e conftest ([859fa81](https://github.com/gerfru/NilesAI/commit/859fa8136f9ed67bc8f56f48459852fd70d5e116))
* **tests:** handle empty POSTGRES_HOST_PORT in e2e conftest ([ac9be42](https://github.com/gerfru/NilesAI/commit/ac9be422c5b4568fcaff9e07205dda972b901ba6))
* **tests:** isolate test_settings_defaults from env pollution ([93612af](https://github.com/gerfru/NilesAI/commit/93612af092903f3bf8c636514218dd283cf457aa))
* text-based tool call fallback for local LLMs ([1003f59](https://github.com/gerfru/NilesAI/commit/1003f590084c137b49c9ae1f84eab54da40b3dab))
* trivy --ignore-unfixed to skip unpatched OS vulns ([b265193](https://github.com/gerfru/NilesAI/commit/b265193671bff4f32c11f5b0e85648f43228dab9))
* Update Evolution API to v2.3.7 and implement hybrid workflow ([5f77eb3](https://github.com/gerfru/NilesAI/commit/5f77eb30cbe09df5b05b2321d79e644866bc24e6))
* update Quality Assessment scores and history after action layer extraction ([ad80ac6](https://github.com/gerfru/NilesAI/commit/ad80ac6df23a4887026d62ac52ff3337538d577c))
* update stale weather card hint text ([16e8154](https://github.com/gerfru/NilesAI/commit/16e81544bd189d2fd5c7b673bfbff8c7043e6612))
* update trivy-action to v0.34.1 — v0.30.0 install script broken ([f2a9d4a](https://github.com/gerfru/NilesAI/commit/f2a9d4aacfa6f8f272d8009bb2431faaa15a609d))
* use correct method name settings_store.get_all() ([dc5ad43](https://github.com/gerfru/NilesAI/commit/dc5ad43a0a676dacafbabc883eacb99984881f52))
* use default SearXNG engines instead of only 4 ([632aefb](https://github.com/gerfru/NilesAI/commit/632aefba9b0a90acf8379a265ea91d69da525cd5))
* use defusedxml for CalDAV XML parsing (H1) ([#126](https://github.com/gerfru/NilesAI/issues/126)) ([4a21789](https://github.com/gerfru/NilesAI/commit/4a21789e3b40452d190532912e1affa92257f928))
* use dynamic timestamps in WhatsApp fetch_messages tests ([eba6290](https://github.com/gerfru/NilesAI/commit/eba6290a5046a617f5051fe904c0055cba46638e))
* use innerHTML swap on admin create-user form ([6c13ae6](https://github.com/gerfru/NilesAI/commit/6c13ae642c3c8f942b58f790bda295a49372af6d))
* use ISO date strings for Evolution API messageTimestamp filter ([f6b9926](https://github.com/gerfru/NilesAI/commit/f6b9926a6c00719fab3901a20fd18f0a286cd69e))
* use OrderedDict for O(1) rate limiter eviction (L3) ([#136](https://github.com/gerfru/NilesAI/issues/136)) ([e5b4273](https://github.com/gerfru/NilesAI/commit/e5b4273dcb5d9d657787ae6c4ee6903aa62be0eb))
* use per-user WhatsApp session for briefing delivery ([ac144ce](https://github.com/gerfru/NilesAI/commit/ac144ce11773534b5daaf23168067cf50239ed1b))
* use SearXNG default port 8080 instead of 8888 ([cf8b28d](https://github.com/gerfru/NilesAI/commit/cf8b28dd34bb925775f75c9a3676522d9f241f1d))
* **user_store:** filter inactive users in create_password_user is_first check ([f26cb6f](https://github.com/gerfru/NilesAI/commit/f26cb6f4e57739c0ea838f37faf0e233cd324d8b))
* UUID path normalization + LLM_DURATION on stream errors ([0f436e3](https://github.com/gerfru/NilesAI/commit/0f436e39678e485b4746e1891bdeac679cabf376))


### Performance

* share httpx.AsyncClient instances via HttpClients container ([10ffef4](https://github.com/gerfru/NilesAI/commit/10ffef4c3cae17a4d809025d3ff4faf2dc9a93ac))


### Documentation

* add benchmark results for llama3.1:8b and mistral:7b ([84b68c3](https://github.com/gerfru/NilesAI/commit/84b68c3803ecc92174e80d95ba0295e18843fbcd))
* add CLAUDE.md project rules ([d5b3a28](https://github.com/gerfru/NilesAI/commit/d5b3a28f7e4cc75a1f98fac394ccc81491c9da39))
* add comprehensive Deployment Guide, refactor Development.md ([1481c2d](https://github.com/gerfru/NilesAI/commit/1481c2d02ec2f6b535147f84d23344d459c425d7))
* add LEGAL.md with third-party licenses and risk disclosures ([902be87](https://github.com/gerfru/NilesAI/commit/902be87cf5526f380228f3653cf9325886722373))
* Add LLM_BASE_URL and LLM_MODEL to .env.example ([74c9f0d](https://github.com/gerfru/NilesAI/commit/74c9f0d3e8e860cadcd8b7f8e603093fe2893e4e))
* add RAG architecture documentation ([5537e2f](https://github.com/gerfru/NilesAI/commit/5537e2fe547c098a2ea5ea5b04c6d8d2d95e1e96))
* Clean up and update documentation to match current code ([51d6e23](https://github.com/gerfru/NilesAI/commit/51d6e23c9f97f76380ad73098b8dc04cf6700919))
* document homelab-gateway dependency and clarify BASE_URL for OAuth ([9b57ca9](https://github.com/gerfru/NilesAI/commit/9b57ca91a5211556f5addd3b236a2e1c23f13b42))
* Document POSTGRES_HOST_PORT env var for debugging ([b2417be](https://github.com/gerfru/NilesAI/commit/b2417bee5ef8083a4c9fc7e29c8e618f4c1741e5))
* fix Google OAuth setup — correct scope, add API activation step, add doc links ([db5ba9d](https://github.com/gerfru/NilesAI/commit/db5ba9dfe65d97d401093ccd3b364c92e5c64b4f))
* integrate Notion-RAG.md into standard docs, update for per-user Google MCP ([6d5a384](https://github.com/gerfru/NilesAI/commit/6d5a384e5421070854b834e1d100a672bc5b7833))
* integrate search + fetch specs into existing documentation ([4464548](https://github.com/gerfru/NilesAI/commit/4464548b50f06ca1b71b23ec47ab16177075e19f))
* license audit and Quality Assessment rewrite ([359187a](https://github.com/gerfru/NilesAI/commit/359187accd5a5224f172148f172195f9bb088b6f))
* merge Architecture.md into Spec, update all docs, archive Stage-10-Plan ([6949dee](https://github.com/gerfru/NilesAI/commit/6949dee1164276fe81d7b88d5e04a091a5099a9c))
* reconcile Quality-Assessment.md with current codebase ([ad19ef7](https://github.com/gerfru/NilesAI/commit/ad19ef76cbe356d4e217f3d76b6df60c894beb2c))
* Rewrite technical documentation and remove emojis ([439645f](https://github.com/gerfru/NilesAI/commit/439645f48ab6e32ac359679782a94c728e9ce9dd))
* **spec:** add missing Google MCP + Notion fields to §3.1–3.3 ([d1656a5](https://github.com/gerfru/NilesAI/commit/d1656a54b19cc479b5df4d8430c3305c59a743cf))
* sync documentation with current codebase ([717d736](https://github.com/gerfru/NilesAI/commit/717d736f6a09538138a1ddc0baecce05e8202f8d))
* Update all documentation and scripts for Stage 9-10 ([f08293c](https://github.com/gerfru/NilesAI/commit/f08293c1ce7ad6108dc8186186761cb99240a179))
* update all documentation to match current codebase ([b376fb4](https://github.com/gerfru/NilesAI/commit/b376fb41a272cfc059be147348b469384b55b590))
* update all documentation to reflect 12-factor compliance changes ([d3fb52b](https://github.com/gerfru/NilesAI/commit/d3fb52b99ae2e2bd55f637150e8157fbc9d1f854))
* update all documentation to reflect web/ package and tool registry ([1d58edc](https://github.com/gerfru/NilesAI/commit/1d58edc3a02617726602ca61c71836c6839e5b60))
* update all documentation, integrate alembic.md into Development.md ([e3f639c](https://github.com/gerfru/NilesAI/commit/e3f639c00cfa934982877b4c9aba5456251b3de8))
* update documentation for 12-factor compliance ([fcc1e30](https://github.com/gerfru/NilesAI/commit/fcc1e3044dc014c0ba9a4952e5272e4c7fb9a6bf))
* update LM Studio references to Ollama ([550aa12](https://github.com/gerfru/NilesAI/commit/550aa12d1253a5e6c05dedc94341346450abd1df))
* update Notion RAG docs for hierarchical chunking and breadcrumbs ([ee7f7ee](https://github.com/gerfru/NilesAI/commit/ee7f7ee71f88e745dd330f05fddca9e45c01f7d0))
* update Quality Assessment for Phase 2 results ([d042aa4](https://github.com/gerfru/NilesAI/commit/d042aa4b1f9f1e6b7e8cca5d9407f639fe62f179))
* update Quality Assessment with latest scores and improvements ([772133a](https://github.com/gerfru/NilesAI/commit/772133a60afd2a1a9801ea36fbbe3d0db2213faa))
* update references to Python 3.14 ([986acc8](https://github.com/gerfru/NilesAI/commit/986acc8b6dffc2537a9b6558921d6ffbd47e3f4c))
* Update spec to v3.0, add build.sh, start.sh --build flag ([14091f4](https://github.com/gerfru/NilesAI/commit/14091f42e46958e6d4011163fb84b1983c82741d))


### Miscellaneous

* add release-please and fix CI ([#147](https://github.com/gerfru/NilesAI/issues/147)) ([f999035](https://github.com/gerfru/NilesAI/commit/f9990354a9069d8749c815c688c2434d4020d6e3))
* align release management with homelab-gateway ([#150](https://github.com/gerfru/NilesAI/issues/150)) ([9d434d4](https://github.com/gerfru/NilesAI/commit/9d434d457735cf42d7204e3593fbfbc74d486bd4))
* bump version to 0.2.0 — public release ([#152](https://github.com/gerfru/NilesAI/issues/152)) ([e3c34a8](https://github.com/gerfru/NilesAI/commit/e3c34a8aa63ef1bbd2427774f67a9967f8aa43a9))
* **ci:** overhaul CI pipeline following PulseBase patterns ([71babbb](https://github.com/gerfru/NilesAI/commit/71babbb2cd8af9806423ee1fec072db8a7d9c90d))
* clean up scripts — delete setup-interactive, update others ([ba88d10](https://github.com/gerfru/NilesAI/commit/ba88d1052eb3c84e1ca1fbddcf74a17e29c897c3))
* **deps:** pin dependencies ([#66](https://github.com/gerfru/NilesAI/issues/66)) ([f51c701](https://github.com/gerfru/NilesAI/commit/f51c7018491c450d6c1c8555a60875afcb5f5e69))
* **deps:** pin dependencies ([#87](https://github.com/gerfru/NilesAI/issues/87)) ([696ae0e](https://github.com/gerfru/NilesAI/commit/696ae0e84e0d61697b0deb0060758cc4f6a8580f))
* **deps:** update actions/checkout action to v6 ([#95](https://github.com/gerfru/NilesAI/issues/95)) ([412d2ef](https://github.com/gerfru/NilesAI/commit/412d2efa6fc8e15c23af57bc25db9e49c7230164))
* **deps:** update anthropics/claude-code-action digest to 0cb4f3e ([#109](https://github.com/gerfru/NilesAI/issues/109)) ([e75906e](https://github.com/gerfru/NilesAI/commit/e75906e184d2557aad61db49294a5da9131362db))
* **deps:** update anthropics/claude-code-action digest to 0f97b95 ([#90](https://github.com/gerfru/NilesAI/issues/90)) ([745f5bb](https://github.com/gerfru/NilesAI/commit/745f5bb3d6bba421e720e66290aa0a77a2043358))
* **deps:** update anthropics/claude-code-action digest to fbda2eb ([#81](https://github.com/gerfru/NilesAI/issues/81)) ([e38d8fc](https://github.com/gerfru/NilesAI/commit/e38d8fc8a6161c32c2c5e37ec6d14dce33b54fcd))
* **deps:** update bbernhard/signal-cli-rest-api docker digest to 419d08b ([#67](https://github.com/gerfru/NilesAI/issues/67)) ([f780002](https://github.com/gerfru/NilesAI/commit/f780002084366e4dc7af9a8b4f1d7c97c117d758))
* **deps:** update evoapicloud/evolution-api docker digest to e15508d ([#70](https://github.com/gerfru/NilesAI/issues/70)) ([6e56c86](https://github.com/gerfru/NilesAI/commit/6e56c8632c2e3487c00727de57bd6193c551e50b))
* **deps:** update ghcr.io/astral-sh/uv docker tag to v0.11.20 ([#88](https://github.com/gerfru/NilesAI/issues/88)) ([6e49406](https://github.com/gerfru/NilesAI/commit/6e49406c0c7e30fd657f1376944916079b41463a))
* **deps:** update python:3.12-slim docker digest to 090ba77 ([#71](https://github.com/gerfru/NilesAI/issues/71)) ([481237f](https://github.com/gerfru/NilesAI/commit/481237f6e9e9038c480d792e7393a80ed6edd978))
* **deps:** update python:3.14-slim docker digest to d7a925f ([#91](https://github.com/gerfru/NilesAI/issues/91)) ([0c859b7](https://github.com/gerfru/NilesAI/commit/0c859b710a9987639a7fd8d31366ba05750f0c40))
* **deps:** update searxng/searxng docker digest to 1081d08 ([#73](https://github.com/gerfru/NilesAI/issues/73)) ([e765bbe](https://github.com/gerfru/NilesAI/commit/e765bbef32e71206da751069d67c21a7ef506b9b))
* **deps:** update searxng/searxng docker digest to 14d3168 ([#89](https://github.com/gerfru/NilesAI/issues/89)) ([6789f40](https://github.com/gerfru/NilesAI/commit/6789f405414e2cd00696b20b92d4df346514292b))
* **deps:** update searxng/searxng docker digest to 4baf815 ([#105](https://github.com/gerfru/NilesAI/issues/105)) ([7c500fb](https://github.com/gerfru/NilesAI/commit/7c500fb2011171f8e4ab673cdc94496f27fc8b90))
* **deps:** update searxng/searxng docker digest to e4fade7 ([#79](https://github.com/gerfru/NilesAI/issues/79)) ([efbe6dd](https://github.com/gerfru/NilesAI/commit/efbe6dd613ee6907ac947ffad621d62a90fe5e85))
* **deps:** update trufflesecurity/trufflehog action to v3.95.5 ([#76](https://github.com/gerfru/NilesAI/issues/76)) ([1ab2778](https://github.com/gerfru/NilesAI/commit/1ab27780dfe282c4a4c1e3fdf1d1bdb38f412f1a))
* **deps:** update vikunja/vikunja docker digest to 9e664c8 ([#74](https://github.com/gerfru/NilesAI/issues/74)) ([4f707c3](https://github.com/gerfru/NilesAI/commit/4f707c36d7e9b9826d67886f7598f323f9a532fb))
* Expose Postgres port for local debugging ([87ca841](https://github.com/gerfru/NilesAI/commit/87ca84180c3274f22d135726965968ea5351a02d))
* fix repo-url placeholders and enable Renovate OSV alerts ([#138](https://github.com/gerfru/NilesAI/issues/138)) ([b5bd630](https://github.com/gerfru/NilesAI/commit/b5bd630ff0958454949bb783a6a8696b377d1189))
* harden repo settings, docs, and README (PulseBase alignment) ([#93](https://github.com/gerfru/NilesAI/issues/93)) ([3d3ea57](https://github.com/gerfru/NilesAI/commit/3d3ea57c0414fa89c89d3c110c7e919f785a2837))
* **license:** add SPDX-License-Identifier headers to all src Python files ([#157](https://github.com/gerfru/NilesAI/issues/157)) ([53cde0c](https://github.com/gerfru/NilesAI/commit/53cde0c7e7e39d6f575465635dc384d7dc2aa827))
* monthly Docker digest schedule + enable check_untyped_defs (L13, M16) ([#103](https://github.com/gerfru/NilesAI/issues/103)) ([46a62c1](https://github.com/gerfru/NilesAI/commit/46a62c1238cb1a9057d169cfd744e13ef8dd4381))
* **oss-hygiene:** document Vikunja root-user, add .mypy_cache, CI secret pragmas ([#156](https://github.com/gerfru/NilesAI/issues/156)) ([68c1ccc](https://github.com/gerfru/NilesAI/commit/68c1ccc3ef6b80c3eed9da2dbc6a3d982081d941))
* public release quality fixes ([#145](https://github.com/gerfru/NilesAI/issues/145)) ([b13c616](https://github.com/gerfru/NilesAI/commit/b13c61648dc4a495e28cc5306b6bb379eb5be9c7))
* remove audit report artifact ([ef1d820](https://github.com/gerfru/NilesAI/commit/ef1d82092901804b911cde7de797349d8efdebce))
* replace internal domain with example.local for public release ([652e2ac](https://github.com/gerfru/NilesAI/commit/652e2ac12426909ea2b105a1f6c0d051fd67c569))
* **security:** public release cleanup — PII, fixtures, hardening ([#160](https://github.com/gerfru/NilesAI/issues/160)) ([83ebe3f](https://github.com/gerfru/NilesAI/commit/83ebe3f4b840407dc47f621c96e108a8e1cc066f))
* translate docs to English, apply ruff format, add pre-commit ([7f33f4e](https://github.com/gerfru/NilesAI/commit/7f33f4ee95afc18d4523485f680b5350cda0d8c8))
* translate docs to English, apply ruff format, add pre-commit ([908ef1e](https://github.com/gerfru/NilesAI/commit/908ef1eaaa8863c88f90b9bc5c306f3551ac1690))
* upgrade all dependencies and ignore uv audit CVE ([9f5f207](https://github.com/gerfru/NilesAI/commit/9f5f207a2f0d7a992c7dcfdbb2a915ca2b640085))
* upgrade Python runtime to 3.14 ([8c8aa3b](https://github.com/gerfru/NilesAI/commit/8c8aa3bf43cdbb7905fee6c5d8a1fc8776fc6da9))
* upgrade to Python 3.14 ([e6bacfc](https://github.com/gerfru/NilesAI/commit/e6bacfc4226d42783ce416e440b0d495498722b9))


### CI/CD

* add pip-audit dependency vulnerability scanning ([001928d](https://github.com/gerfru/NilesAI/commit/001928d3fe05247b4eb4505dd503d4cfedd9ae0a))
* disable CI trigger on push to main ([#143](https://github.com/gerfru/NilesAI/issues/143)) ([38564c7](https://github.com/gerfru/NilesAI/commit/38564c7e6a271e63afe5b4fb3c8484b2ed250dd0))
* ignore PYSEC-2026-196 pip path traversal (build tool, not runtime) ([08ca887](https://github.com/gerfru/NilesAI/commit/08ca887ecbd3241488c21c6f7471b1093166afd4))


### Tests

* add coverage for dedup, bool return, _filter_overdue edges ([c0976e0](https://github.com/gerfru/NilesAI/commit/c0976e0e75d3b6ef0acd66f52604a1ca4ee8fbed))
* add OAuth callback tests covering all 10 branches (13 tests) ([#98](https://github.com/gerfru/NilesAI/issues/98)) ([dcc3d60](https://github.com/gerfru/NilesAI/commit/dcc3d6021e7b2cd9cfac21a897ba8731968ec2be))
* add round-trip encryption tests for credential and settings stores ([#137](https://github.com/gerfru/NilesAI/issues/137)) ([fb87407](https://github.com/gerfru/NilesAI/commit/fb87407f607036227915da4ec64a52876c6e89c3))
* add UserStore unit tests (25 tests, all 12 public methods) ([#97](https://github.com/gerfru/NilesAI/issues/97)) ([43ff168](https://github.com/gerfru/NilesAI/commit/43ff16808ec21ce30e29ec4c0f5685581071ab30))
* add web route handler auth-guard tests (28 tests, H11) ([#101](https://github.com/gerfru/NilesAI/issues/101)) ([5337906](https://github.com/gerfru/NilesAI/commit/5337906e2023a8f26c3d92f98fc5af6df28ee37f))
* add WhatsAppStore + EchoGuard tests, bump fail_under to 70 (M14, M15, L11) ([#102](https://github.com/gerfru/NilesAI/issues/102)) ([4d5aa4b](https://github.com/gerfru/NilesAI/commit/4d5aa4b7656fcddc3d76fe855324b9601a7d6766))
* update calendar tests for user_id scoping ([df14535](https://github.com/gerfru/NilesAI/commit/df1453526e1af31c3fdd6f63c7787af41ddc623a))

## [0.2.0](https://github.com/gerfru/NilesAI/releases/tag/v0.2.0) (2026-06-12)

First public release. Major security hardening, infrastructure improvements, and
preparation for open-source publication since the initial private baseline.

### Security

* Replace `xml.etree` with `defusedxml` for CalDAV XML parsing (XXE protection)
* Add SSRF protection for CardDAV `test_connection` endpoint
* Fail-closed SSRF check on DNS resolution failure
* Enforce single Uvicorn worker process at startup (prevents shared state across forks)
* Protect LLM hot-reload and Vikunja `_in_flight` set with `asyncio.Lock`
* Cap login rate limiter with `OrderedDict` to prevent memory exhaustion
* Remove PostgreSQL pool stats from unauthenticated `/health` endpoint
* Scope contact lookups and memory store to authenticated `user_id`
* Add user context and message length limit to `/chat` endpoint
* Decouple credential encryption gate from `LOG_LEVEL`
* Require admin auth for `notion_connect` and `briefing_test` endpoints
* OAuth hardening: error sanitization, credential encryption docs, `/ready` endpoint

### Features

* Conversation history pruning to prevent unbounded memory growth
* Per-user memory store scoping
* Opt-in Sentry error tracking (`SENTRY_DSN` env var)
* DB connection pool saturation metrics
* Configurable phone country code (`PHONE_COUNTRY_CODE`)
* Static asset cache-busting and search toggle visual feedback

### Infrastructure

* Upgrade Python runtime to **3.14**
* Modernize Dockerfile to `uv sync --frozen` with venv
* Add Docker resource limits and named volumes
* Set up Release Please (automated changelog + GitHub Releases)
* Add tag-triggered SBOM generation as release asset
* Branch protection on `main` (CI gate, linear history, enforce admins)
* Pin all Docker base images and GitHub Actions to exact SHAs
* Monthly Renovate schedule for Docker digest updates

### Refactoring

* Extract God Functions across agent core, web routes, and sync layer
* Reduce cyclomatic complexity in calendar, context, and briefing modules
* Extract `SettingsStore` validator registry
* Add `AppState` Protocol and `TypedDict` types throughout
* Add tuple-form `except` clauses replacing Python-2-style comma syntax

### Tests

* Add auth-guard tests for all 28 web route handlers
* Add `UserStore` unit tests (25 tests, all public methods)
* Add OAuth callback branch coverage (13 tests)
* Add `WhatsAppStore` + `EchoGuard` tests; raise `fail_under` to 70%
* Add round-trip encryption tests for credential and settings stores

### Chore

* Replace internal hostnames with `example.local` for public release
* Harden repo settings, README, and documentation
* Enable `check_untyped_defs` in mypy

## [0.1.0](https://github.com/gerfru/NilesAI/releases/tag/v0.1.0) (2026-03-13)

Initial private baseline. Core agent loop, WhatsApp/Signal integration, CalDAV/CardDAV
sync, Notion RAG, Vikunja task management, and web UI.
