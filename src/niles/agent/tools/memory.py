"""Memory tools: remember and recall."""

from . import ToolContext, register_tool


@register_tool("remember")
async def handle_remember(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    await ctx.memory.set(args["key"], args["value"])
    return {"status": "saved", "key": args["key"]}


@register_tool("recall")
async def handle_recall(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    value = await ctx.memory.get(args["key"])
    if value is not None:
        return {"key": args["key"], "value": value}
    return {"error": f"Nichts gespeichert unter '{args['key']}'"}
