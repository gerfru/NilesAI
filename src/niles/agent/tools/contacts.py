# SPDX-License-Identifier: AGPL-3.0-only
"""Contact lookup tool."""

from . import ToolContext, register_tool


@register_tool("find_contact")
async def handle_find_contact(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    query = args.get("name") or args.get("query") or ""
    if not query:
        # LLM sent wrong param names — use the first string value
        for v in args.values():
            if isinstance(v, str) and v:
                query = v
                break
    if not query:
        return {"error": "Kein Name angegeben"}
    contact = await ctx.contacts.find_by_name(query, user_id=ctx.user_id)
    if contact:
        return contact  # type: ignore[return-value]  # ContactInfo (TypedDict) is a dict
    return {"error": f"Kontakt '{query}' nicht gefunden"}
