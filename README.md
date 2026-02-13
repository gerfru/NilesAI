# Niles AI

100% local AI agent running on Mac Mini M4 with Apple Silicon optimization.

## Overview

Niles is a self-hosted AI agent that runs entirely offline on Apple Silicon hardware. All data remains local, no cloud dependencies, zero monthly costs.

**Key Features:**

- Local LLM inference using Apple MLX (80+ tokens/sec on M4)
- Visual workflow automation with n8n
- Calendar management (Google Calendar + CalDAV)
- WhatsApp integration via Evolution API
- Complete offline capability

## Architecture

```text
┌─────────────────────────────────────────┐
│         Mac Mini M4 (16GB RAM)          │
│                                         │
│  LM Studio (MLX) ──► n8n (Docker)       │
│                       │                 │
│                       ├─► Google Cal    │
│                       ├─► CalDAV        │
│                       └─► WhatsApp      │
└─────────────────────────────────────────┘
```

**Stack:**

- **LM Studio** - Apple MLX-optimized LLM inference (Port 1234)
- **n8n** - Workflow automation & AI agent builder (Port 5678)
- **Evolution API** - WhatsApp gateway with PostgreSQL (Port 8080)
- **Tailscale** - Optional remote access

## System Requirements

- Mac Mini M4 (16GB RAM minimum, 32GB recommended)
- macOS 14.0 or later
- Docker Desktop for Mac
- 20GB free disk space

## Quick Start

### 1. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and set your API keys
nano .env
```

### 2. Start Services

```bash
# Start Docker containers
./scripts/start.sh

# Start LM Studio manually
open -a "LM Studio"
# Then start server on port 1234 in LM Studio UI
```

### 3. Access

- **n8n Workflow UI:** <http://localhost:5678>
- **LM Studio API:** <http://localhost:1234/v1>
- **Evolution Manager:** <http://localhost:8080/manager>

### 4. Check Status

```bash
./scripts/status.sh
```

## Installation

See [Setup Documentation](Setup/README.md) for detailed installation steps:

1. [LM Studio Installation](Setup/01-lm-studio.md)
2. [n8n Docker Setup](Setup/02-n8n.md)
3. [Google Calendar Integration](Setup/03-google-calendar.md)
4. [CalDAV Integration](Setup/03-mailbox-caldav.md)
5. [WhatsApp Integration](Setup/05-whatsapp-evolution.md)
6. [AI Agent Configuration](Setup/06-ai-agent.md)

## Project Structure

```text
Niles/
├── docker/
│   └── docker-compose.yml    # All services (n8n, Evolution, PostgreSQL)
├── scripts/
│   ├── start.sh             # Start all services
│   ├── stop.sh              # Stop all services
│   ├── status.sh            # Check service status
│   ├── backup.sh            # Create backup
│   └── cleanup.sh           # Remove all containers
└── Setup/
    └── *.md                 # Detailed setup documentation
```

## Scripts

### Start/Stop

```bash
./scripts/start.sh    # Start all Docker services
./scripts/stop.sh     # Stop all Docker services
./scripts/status.sh   # Check if services are running
```

### Backup/Restore

```bash
./scripts/backup.sh   # Create timestamped backup
# Backups stored in ~/Backups/Niles/
# Includes: n8n data, WhatsApp sessions, PostgreSQL, configs
```

### Cleanup

```bash
./scripts/cleanup.sh  # Remove all containers and volumes
# WARNING: Destructive operation, prompts for confirmation
# Keeps: ~/.n8n and ~/.evolution as backup
```

## Performance

**Benchmarks on Mac Mini M4 (16GB RAM):**

| Component                        | Resource Usage | Notes                    |
|----------------------------------|----------------|--------------------------|
| LM Studio (Qwen2.5-Coder:7b MLX) | 8GB RAM        | 100+ tokens/sec          |
| n8n (Docker)                     | 500MB RAM      | Workflow automation      |
| Evolution API (Docker)           | 300MB RAM      | WhatsApp gateway         |
| PostgreSQL (Docker)              | 100MB RAM      | Evolution database       |
| **Total**                        | ~9GB RAM       | 7GB available for system |

## Troubleshooting

### Common Issues

**n8n "Bad request" error:**

- Disable "Use Response API" in AI Agent node settings

**Google OAuth fails:**

- Disable "Enhanced Safe Browsing" in Google account security settings

**LM Studio slow inference:**

- Verify MLX-optimized model is loaded (not GGUF)
- Check model file ends with `-mlx` in LM Studio

**WhatsApp connection stuck on "connecting":**

- Delete instance in Evolution Manager
- Create new instance and re-scan QR code
- Check `docker logs niles_evolution_api` for errors

**Evolution API 400 Bad Request:**

- Verify phone number format: `4915123456789` (country code + number, no plus sign)
- Check Evolution API is running: `docker ps | grep evolution`

### Logs

```bash
# Check Docker container logs
docker logs niles_n8n
docker logs niles_evolution_api
docker logs niles_evolution_postgres

# Check all services
docker compose -f docker/docker-compose.yml logs
```

## Security

- All services run in isolated Docker network
- No external API calls (except optional Google Calendar OAuth)
- Credentials stored encrypted in n8n database (AES-256)
- WhatsApp sessions stored locally in `~/.evolution/instances`
- Optional: Use Tailscale for secure remote access

## Contributing

This is a personal project. Issues and pull requests welcome.

## License

Open source for personal use. See LICENSE file for details.

## Support

- **n8n Community:** https://community.n8n.io/
- **LM Studio Discord:** https://discord.gg/lmstudio
- **Evolution API Docs:** https://doc.evolution-api.com/

## Acknowledgments

- Built with [n8n](https://n8n.io/)
- Powered by [LM Studio](https://lmstudio.ai/)
- WhatsApp integration via [Evolution API](https://evolution-api.com/)