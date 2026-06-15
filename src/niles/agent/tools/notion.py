# SPDX-License-Identifier: AGPL-3.0-only
"""Notion RAG search tool."""

from ..prompts import wrap_untrusted
from . import ToolContext, register_tool


@register_tool("search_notion")
async def handle_search_notion(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    retriever = getattr(ctx, "notion_retriever", None)
    if not retriever:
        return {"error": "Notion-Integration nicht konfiguriert."}

    query = args.get("query", "")
    if not query.strip():
        return {"error": "query must not be empty"}
    max_results = min(int(args.get("max_results", 5)), 10)

    results = await retriever.search(query, max_results=max_results)

    if not results:
        return {"message": "Keine relevanten Notion-Inhalte gefunden.", "results": []}

    # Format for LLM context
    formatted = []
    for r in results:
        formatted.append(
            {
                "source": r["page_title"],
                "url": r["page_url"],
                # Indexed page content is externally controlled → isolate as data.
                "content": wrap_untrusted("notion", r["chunk_text"]),
                "relevance": r["similarity"],
            }
        )

    return {
        "message": f"{len(formatted)} relevante Notion-Abschnitte gefunden.",
        "results": formatted,
    }
