# SPDX-License-Identifier: AGPL-3.0-only
"""Vikunja task tools: list_tasks, create_task, complete_task."""

import time

from . import ToolContext, register_tool

_VIKUNJA_NOT_CONFIGURED = "Aufgaben nicht konfiguriert. Bitte Vikunja-Token in den Einstellungen hinterlegen."


@register_tool("list_tasks")
async def handle_list_tasks(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    tasks_action = await ctx.resolve_vikunja(chat_id)
    if not tasks_action:
        return {"error": _VIKUNJA_NOT_CONFIGURED}
    tasks = await tasks_action.list_tasks(
        project=args.get("project", ""),
        include_done=args.get("include_done", False),
    )
    if tasks:
        return {"tasks": tasks, "count": len(tasks)}
    return {"error": "Keine Aufgaben gefunden"}


@register_tool("create_task")
async def handle_create_task(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    tasks_action = await ctx.resolve_vikunja(chat_id)
    if not tasks_action:
        return {"error": _VIKUNJA_NOT_CONFIGURED}
    return await tasks_action.create_task(
        title=args["title"],
        description=args.get("description", ""),
        due_date=args.get("due_date", ""),
        priority=args.get("priority", 0),
        project=args.get("project", ""),
    )


@register_tool("complete_task")
async def handle_complete_task(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    tasks_action = await ctx.resolve_vikunja(chat_id)
    if not tasks_action:
        return {"error": _VIKUNJA_NOT_CONFIGURED}
    found = await tasks_action.find_task(title=args["title"])
    if "error" in found:
        return found
    matched_title = found["title"]
    ctx.pending_confirmations[chat_id] = {
        "action": "complete_task",
        "params": {"title": matched_title},
        "display": f"Aufgabe '{matched_title}' als erledigt markieren",
        "expires_at": time.monotonic() + 300,
    }
    return {"confirm": f"Aufgabe '{matched_title}' als erledigt markieren — ok?"}
