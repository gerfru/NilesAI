# LLM Model Evaluation

> **Date:** YYYY-MM-DD
> **Environment:** Mac Mini M4, XX GB RAM, Ollama vX.X.X

## Test Environment

- **Hardware:** Apple Mac Mini M4, XX GB unified memory
- **Ollama version:** `ollama --version`
- **Test framework:** Claude-as-Judge (`tests/e2e/test_llm_judge.py`)
- **Judge model:** Claude Sonnet 4.6
- **Score threshold:** 7/10 (passing)
- **Test count:** ~22 scenarios (tool selection, no-tool, ambiguous, multi-tool)

## Results

| Model             | Tool Sel. | Tool Args | Response | Personality | Language | Avg  |
|-------------------|-----------|-----------|----------|-------------|----------|------|
| llama3.1:8b       |           |           |          |             |          |      |
| llama3.3:latest   |           |           |          |             |          |      |
| qwen3:8b          |           |           |          |             |          |      |
| mistral:latest    |           |           |          |             |          |      |

## Performance

| Model             | Tokens/s | RAM Usage | Model Size |
|-------------------|----------|-----------|------------|
| llama3.1:8b       |          |           |            |
| llama3.3:latest   |          |           |            |
| qwen3:8b          |          |           |            |
| mistral:latest    |          |           |            |

## Scoring Criteria

1. **tool_selection** (0-10): Did the agent select the correct tool?
2. **tool_arguments** (0-10): Were the tool arguments correct?
3. **response_quality** (0-10): Is the response helpful and correct?
4. **personality** (0-10): Does the tone match the butler character?
5. **language** (0-10): Is the response in proper German?

## Recommendation

> Fill in after running `./scripts/benchmark-llm.sh`

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
