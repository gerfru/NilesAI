# Phase 1: LM Studio Installation & Setup

## Übersicht

Installation von LM Studio mit Apple MLX-optimiertem Modell für lokale LLM-Inferenz auf Mac Mini M4.

## Voraussetzungen

- Mac Mini M4 mit 16 GB RAM
- macOS (Darwin 25.2.0)
- Internetverbindung für Download

## Schritte

### 1. LM Studio installieren

```bash
# Download von https://lmstudio.ai/download
# Für Apple Silicon (M4): lmstudio-0.3.4-arm64.dmg

# Nach Installation öffnen:
open -a "LM Studio"
```

### 2. MLX-optimiertes Modell herunterladen

**Empfohlenes Modell für 16 GB RAM:**
- **Qwen2.5-Coder:7b** (8-bit MLX Version)
- Größe: ~8 GB
- Performance: ~100 tokens/sec auf M4
- Tool-Calling Accuracy: ~65%

**In LM Studio:**
1. Search → "qwen2.5-coder 7b mlx"
2. Download: `lmstudio-community/Qwen2.5-Coder-7B-Instruct-MLX-8bit`
3. **WICHTIG:** MLX-Version wählen (nicht GGUF!)

**Warum 8-bit statt 4-bit?**
- 8-bit: ~65% Tool-Calling Accuracy
- 4-bit: ~55% Tool-Calling Accuracy
- Für AI-Agent ist höhere Genauigkeit wichtiger

### 3. LM Studio Server starten

**In LM Studio:**
1. Tab: "Local Server"
2. Model: Qwen2.5-Coder:7b (MLX)
3. Port: `1234` (Standard)
4. "Start Server"

### 4. Verifikation

```bash
# Test API
curl http://localhost:1234/v1/models

# Sollte JSON mit Modell-Info zurückgeben
```

## Wichtige Dateien

- `~/Library/Application Support/LM Studio/` - Config & Models
- Model-Speicherort: In LM Studio GUI einsehbar

## API-Endpunkt

- **Base URL:** `http://localhost:1234/v1`
- **Format:** OpenAI-kompatibel
- **API Key:** Nicht erforderlich (lokal)

## Troubleshooting

### Server startet nicht
- Prüfen ob Port 1234 bereits belegt: `lsof -i :1234`
- LM Studio neu starten

### Modell lädt nicht / Out of Memory
- Kleineres Modell wählen: Llama 3.2:3b (~4 GB RAM)
- Andere Apps schließen

### Langsame Inferenz
- Sicherstellen dass MLX-Version geladen ist (nicht llama.cpp)
- Apple MLX ist 19-27% schneller auf M4

## Nächste Schritte

→ [Phase 2: n8n Installation](02-n8n.md)
