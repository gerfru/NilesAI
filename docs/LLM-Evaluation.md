# LLM Model Evaluation

> **Date:** 2026-03-09
> **Environment:** Mac Mini M4, 16 GB RAM, Ollama v0.13.1

## Test Environment

- **Hardware:** Apple Mac Mini M4, 16 GB unified memory
- **Ollama version:** 0.13.1
- **Test framework:** Claude-as-Judge (`tests/e2e/test_llm_judge.py`)
- **Judge model:** see `tests/e2e/judge.py` (currently `claude-sonnet-4-6`)
- **Score threshold:** 7/10 (passing)
- **Test count:** 19 scenarios (tool selection, no-tool, ambiguous, multi-tool)
- **System prompt:** minimal ("Du bist Niles.") — full `config/soul.md` not loaded in E2E

## Results

| Model             | Tool Sel. | Tool Args | Response | Personality | Language | Avg  |
|-------------------|-----------|-----------|----------|-------------|----------|------|
| llama3.1:8b       | 5.7       | 4.9       | 5.3      | 5.1         | 7.7      | 5.7  |
| mistral:7b        | 2.1       | 5.2       | 2.1      | 4.0         | 6.3      | 3.9  |
| llama3.3:latest   |           |           |          |             |          |      |
| qwen3:8b          |           |           |          |             |          |      |

### Per-Test Breakdown: llama3.1:8b

| Test                  | Tool Sel. | Tool Args | Response | Personality | Language |
|-----------------------|-----------|-----------|----------|-------------|----------|
| find_contact          | 10        | 7         | 8        | 5           | 9        |
| remember              | 10        | 5         | 7        | 7           | 9        |
| find_event            | 10        | 8         | 7        | 5           | 8        |
| greeting              | 3         | 4         | 6        | 5           | 8        |
| create_task           | 10        | 7         | 6        | 5           | 7        |
| web_search (*)        | 1         | 2         | 1        | 4           | 7        |
| fetch_url (*)         | 1         | 2         | 1        | 5           | 8        |
| send_whatsapp         | 7         | 3         | 6        | 5           | 8        |
| get_whatsapp_messages | 6         | 4         | 5        | 4           | 8        |
| create_event          | 5         | 6         | 3        | 3           | 5        |
| list_tasks            | 10        | 10        | 8        | 7           | 9        |
| remember_wifi         | 7         | 5         | 3        | 4           | 8        |
| recall_wifi           | 10        | 8         | 8        | 5           | 9        |
| no_tool_knowledge     | 2         | 5         | 9        | 5           | 8        |
| no_tool_explanation   | 3         | 4         | 7        | 4           | 7        |
| no_tool_thanks        | 1         | 2         | 7        | 7           | 9        |
| ambiguous_whats_new   | 4         | 5         | 5        | 6           | 8        |
| ambiguous_contact     | 5         | 4         | 3        | 5           | 8        |
| multi_remember_event  | 4         | 3         | 1        | 2           | 6        |

(*) No search/fetch tool available — correct response is to explain the limitation.

### Per-Test Breakdown: mistral:7b

| Test                  | Tool Sel. | Tool Args | Response | Personality | Language |
|-----------------------|-----------|-----------|----------|-------------|----------|
| find_contact          | 2         | 2         | 2        | 3           | 5        |
| remember              | 0         | 10        | 2        | 5           | 7        |
| find_event            | 0         | 0         | 1        | 4           | 6        |
| greeting              | 0         | 10        | 1        | 5           | 6        |
| create_task           | 0         | 0         | 2        | 5           | 7        |
| web_search (*)        | 0         | 10        | 1        | 6           | 7        |
| fetch_url (*)         | 0         | 10        | 0        | 2           | 6        |
| send_whatsapp         | 2         | 1         | 1        | 1           | 3        |
| get_whatsapp_messages | 1         | 1         | 1        | 3           | 6        |
| create_event          | 0         | 0         | 1        | 5           | 6        |
| list_tasks            | 0         | 0         | 1        | 5           | 6        |
| remember_wifi         | 2         | 10        | 1        | 2           | 6        |
| no_tool_knowledge     | 10        | 10        | 10       | 5           | 9        |
| no_tool_explanation   | 10        | 10        | 7        | 4           | 7        |
| no_tool_thanks        | 10        | 10        | 2        | 3           | 8        |
| ambiguous_whats_new   | 1         | 10        | 2        | 5           | 6        |
| ambiguous_contact     | 0         | 0         | 2        | 5           | 7        |
| multi_remember_event  | 0         | 0         | 1        | 4           | 6        |

## Performance

| Model             | Tokens/s | RAM Usage | Model Size |
|-------------------|----------|-----------|------------|
| llama3.1:8b       |          |           | 4.7 GB     |
| mistral:7b        |          |           | 4.1 GB     |
| llama3.3:latest   |          |           |            |
| qwen3:8b          |          |           |            |

## Scoring Criteria

1. **tool_selection** (0-10): Did the agent select the correct tool?
2. **tool_arguments** (0-10): Were the tool arguments correct?
3. **response_quality** (0-10): Is the response helpful and correct?
4. **personality** (0-10): Does the tone match the butler character?
5. **language** (0-10): Is the response in proper German?

## Recommendation

**llama3.1:8b remains the default model.** It is the only tested model that reliably
uses the function-calling API for tool invocation.

**mistral:7b is unsuitable** — it systematically hallucinates tool calls as text instead
of using the function-calling API, presenting fabricated data as real results. This is
the worst possible failure mode: the user receives convincing but false information.

### Key Findings

- **llama3.1:8b strengths:** Core tool calling works (find_contact, remember, recall,
  find_event, list_tasks, create_task). German language quality is consistently high (7.7).
- **llama3.1:8b weaknesses:** Unnecessarily calls `recall` for general knowledge questions.
  Butler personality too casual (avg 5.1). Multi-tool scenarios unreliable. Raw JSON
  sometimes leaks into responses.
- **mistral:7b** almost never uses the function-calling API. Instead, it writes tool calls
  as code blocks in the response text and then invents the results.

### Next Steps

1. Test `llama3.3:latest` (70B) and `qwen3:8b` — both expected to be stronger at
   function calling
2. Load full `config/soul.md` system prompt in E2E tests for more representative
   personality scores
3. Improve `_try_parse_text_tool_call()` fallback to catch more text-based tool patterns

## How to Run

```bash
# Run with default models
./scripts/benchmark-llm.sh

# Run with specific models
./scripts/benchmark-llm.sh llama3.1:8b qwen3:8b

# Run individual judge tests
./scripts/test-e2e.sh judge
```

## Notes

- MCP-dependent tests (weather, search, fetch) are skipped unless the corresponding
  services are running and feature flags are enabled
- Feature-gated tests (Notion, Signal) require `FEATURE_NOTION=true` / `SIGNAL_PHONE` set
- Token speed and RAM usage should be measured separately with `ollama run <model>`
