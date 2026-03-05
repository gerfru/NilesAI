"""Claude-as-Judge — evaluate agent interactions using Claude API.

Uses Claude to score agent responses on tool selection, argument quality,
response quality, personality, and language correctness.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """\
Du bist ein QA-Tester für den AI-Butler "Niles". Bewerte die Agent-Interaktion.

## Benutzer-Nachricht
{user_message}

## Verfügbare Tools
{available_tools}

## Tool-Calls des Agents
{tool_calls}

## Tool-Ergebnisse
{tool_results}

## Agent-Antwort
{agent_response}

## Bewertungskriterien
Bewerte jeden Punkt 0-10:

1. **tool_selection**: Hat der Agent das richtige Tool gewählt? \
(10 = perfekt, 0 = falsches Tool oder Tool vergessen. \
Wenn kein Tool nötig war und keines verwendet wurde: 10)
2. **tool_arguments**: Waren die Tool-Argumente korrekt? \
(10 = perfekt, 0 = falsche/fehlende Args. \
Wenn kein Tool verwendet wurde: 10)
3. **response_quality**: Ist die Antwort hilfreich und korrekt? \
(10 = perfekt, 0 = falsch oder unbrauchbar)
4. **personality**: Passt der Ton zum Butler-Charakter (höflich, hilfsbereit, \
leicht förmlich, auf Deutsch)? \
(10 = perfekter Butler-Stil, 0 = unangemessen)
5. **language**: Ist die Antwort auf Deutsch und grammatisch korrekt? \
(10 = perfektes Deutsch, 0 = falsche Sprache oder grobe Fehler)

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt (kein Markdown, kein Text davor/danach):
{{"tool_selection": N, "tool_arguments": N, "response_quality": N, \
"personality": N, "language": N, "reasoning": "kurze Begründung"}}
"""


async def judge_interaction(
    user_message: str,
    tool_calls: list[dict],
    tool_results: list[dict],
    agent_response: str,
    available_tools: list[str],
) -> dict:
    """Use Claude to evaluate an agent interaction.

    Returns dict with scores (0-10) for each criterion and reasoning.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    import anthropic

    client = anthropic.AsyncAnthropic()

    prompt = JUDGE_PROMPT.format(
        user_message=user_message,
        available_tools=", ".join(available_tools) if available_tools else "(keine)",
        tool_calls=json.dumps(tool_calls, ensure_ascii=False)
        if tool_calls
        else "(keine)",
        tool_results=(
            json.dumps(tool_results, ensure_ascii=False) if tool_results else "(keine)"
        ),
        agent_response=agent_response or "(keine Antwort)",
    )

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Handle potential markdown wrapping
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(text)


async def run_and_judge(
    agent,
    message: str,
    chat_id: str = "judge-test",
    available_tools: list[str] | None = None,
) -> dict:
    """Run agent and evaluate its response with Claude.

    Returns dict with:
    - scores: {tool_selection, tool_arguments, response_quality, personality, language}
    - reasoning: str
    - agent_response: str
    - tool_calls: list
    - tool_results: list
    """
    event = {"type": "web", "from": chat_id, "content": message}

    collected_tool_calls: list[dict] = []
    collected_tool_results: list[dict] = []
    response_chunks: list[str] = []

    async for item in agent.process_event_stream(event):
        if item["type"] == "status":
            # Extract tool name from "tool_name..." format
            tool_name = item["text"].rstrip(".")
            collected_tool_calls.append({"name": tool_name})
        elif item["type"] == "chunk":
            response_chunks.append(item["text"])

    agent_response = "".join(response_chunks)

    if available_tools is None:
        from niles.agent.core import TOOLS

        available_tools = [t["function"]["name"] for t in TOOLS]

    scores = await judge_interaction(
        user_message=message,
        tool_calls=collected_tool_calls,
        tool_results=collected_tool_results,
        agent_response=agent_response,
        available_tools=available_tools,
    )

    return {
        "scores": scores,
        "reasoning": scores.get("reasoning", ""),
        "agent_response": agent_response,
        "tool_calls": collected_tool_calls,
    }
