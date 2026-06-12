# SPDX-License-Identifier: AGPL-3.0-only
"""Text-based tool-call detection for local LLMs.

Local models (e.g. llama3.1 via Ollama) sometimes output tool calls as
plain text instead of using the function-calling API.  This module detects
and parses such text into proper tool-call dicts.
"""

import json
import re


def try_parse_text_tool_call(
    text: str,
    known_tools: frozenset[str],
) -> dict | None:
    """Detect a tool call embedded as JSON in the LLM text response.

    Handles several patterns:
    - Pure JSON: ``{"name": "tool", "parameters": {...}}``
    - Markdown-fenced: ````json\\n{...}\\n````
    - Prefixed text: ``Ich rufe tool auf... {"name": "tool", ...}``
    - Malformed JSON: ``"parameters{"`` / ``"parameters>{"``

    Returns {"name": str, "arguments": str} or None.
    """
    # Strip markdown code fences if present
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # If text doesn't start with '{', try to find JSON embedded in it
    if not cleaned.startswith("{"):
        # Look for the first '{' that could start a tool-call JSON object
        brace_pos = cleaned.find("{")
        if brace_pos == -1:
            return None
        cleaned = cleaned[brace_pos:]

    result = parse_json_tool_call(cleaned, known_tools)
    if result:
        return result

    return None


def parse_json_tool_call(
    cleaned: str,
    known_tools: frozenset[str],
) -> dict | None:
    """Parse a JSON string into a tool call dict.

    Tries three strategies:
    1. Standard ``json.loads()``
    2. Regex repair for llama3.1-specific ``"parameters..."`` patterns
    3. ``json_repair.repair_json()`` as broad fallback

    Returns {"name": str, "arguments": str} or None.
    """
    obj: dict | None = None

    # Stage 1: Standard parse
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Stage 2: llama3.1-specific repair ("parameters{", "parameters>{")
    if obj is None:
        repaired = re.sub(r'"(parameters|arguments)[^"]*\{', r'"\1":{', cleaned)
        if repaired != cleaned:
            try:
                obj = json.loads(repaired)
            except json.JSONDecodeError:
                pass

    # Stage 3: json-repair library as broad fallback
    if obj is None:
        try:
            from json_repair import repair_json

            obj = repair_json(cleaned, return_objects=True)  # type: ignore[assignment]  # repair_json returns str | Any
        except Exception:
            return None

    if not isinstance(obj, dict):
        return None

    # Format: {"name": "tool", "parameters": {...}}
    name = obj.get("name")
    if not name:
        return None

    if name in known_tools:
        params = obj.get("parameters") or obj.get("arguments") or {}
        return {"name": name, "arguments": json.dumps(params, ensure_ascii=False)}

    # Fuzzy match for MCP tools: LLMs often hallucinate slightly wrong names
    # (e.g. "mcp__searxng__search" instead of "mcp__searxng__web_search").
    # If there is exactly one known tool from the same MCP server, use it.
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) >= 2:
            prefix = f"mcp__{parts[1]}__"
            candidates = [t for t in known_tools if t.startswith(prefix)]
            if len(candidates) == 1:
                params = obj.get("parameters") or obj.get("arguments") or {}
                return {
                    "name": candidates[0],
                    "arguments": json.dumps(params, ensure_ascii=False),
                }

    return None


def is_rejected_tool_call(text: str) -> str | None:
    """Check if *text* looks like a tool call for an unavailable tool.

    Called **after** ``try_parse_text_tool_call`` returned ``None`` to
    distinguish "not a tool call at all" from "tool call for a filtered
    tool".  Returns the tool name when the text is structurally a tool
    call (JSON with ``name`` + ``parameters``/``arguments`` keys), or
    ``None`` otherwise.
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    if not cleaned.startswith("{"):
        brace_pos = cleaned.find("{")
        if brace_pos == -1:
            return None
        cleaned = cleaned[brace_pos:]

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            obj = repair_json(cleaned, return_objects=True)  # type: ignore[assignment]  # repair_json returns str | Any
        except Exception:
            return None

    if not isinstance(obj, dict):
        return None

    name = obj.get("name")
    if not name or not isinstance(name, str):
        return None

    # Must have parameters or arguments to look like a tool call
    if obj.get("parameters") is not None or obj.get("arguments") is not None:
        return name

    return None


def synthetic_tool_call(parsed: dict) -> tuple[dict, dict]:
    """Build a synthetic tool-call dict and assistant message from parsed text.

    Returns (tc_dict, assistant_message) where tc_dict has keys
    "id", "name", "arguments" and assistant_message is ready to append
    to the messages list.
    """
    tc = {
        "id": f"text_{parsed['name']}",
        "name": parsed["name"],
        "arguments": parsed["arguments"],
    }
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            }
        ],
    }
    return tc, message
