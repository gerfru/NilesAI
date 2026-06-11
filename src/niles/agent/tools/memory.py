"""Memory tools: remember and recall."""

from . import ToolContext, register_tool

_NO_USER_ERROR = {"error": "Kein Benutzer identifiziert."}


@register_tool("remember")
async def handle_remember(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    if ctx.user_id is None:
        return _NO_USER_ERROR
    await ctx.memory.set(ctx.user_id, args["key"], args["value"])
    return {"status": "saved", "key": args["key"]}


@register_tool("recall")
async def handle_recall(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    if ctx.user_id is None:
        return _NO_USER_ERROR
    value = await ctx.memory.get(ctx.user_id, args["key"])
    if value is not None:
        return {"key": args["key"], "value": value}
    return {"error": f"Nichts gespeichert unter '{args['key']}'"}
