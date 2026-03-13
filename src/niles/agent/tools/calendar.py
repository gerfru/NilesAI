"""Calendar tools: find_event and create_event."""

import logging

import httpx

from . import ToolContext, register_tool

logger = logging.getLogger(__name__)


@register_tool("find_event")
async def handle_find_event(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    if not ctx.calendar:
        return {"error": "Kalender ist nicht konfiguriert"}

    # Guard 1: small LLMs sometimes put a contact name into date_from
    # (e.g. find_event(date_from="mama") when they should use
    # find_contact).  Detect and redirect.
    date_from = args.get("date_from", "")
    date_to = args.get("date_to", "")
    _date_chars = set("0123456789-/.T:+Z ")
    for df in (date_from, date_to):
        if df and not set(df).issubset(_date_chars):
            # Looks like a name, not a date — treat as query instead
            logger.info("find_event: moving non-date value '%s' to query", df)
            if not args.get("query"):
                args["query"] = df
            if df == date_from:
                date_from = ""
            else:
                date_to = ""

    # Guard 2: small LLMs often confuse the user's name with a
    # calendar source name and pass it as filter on general date
    # queries.  Only honour the calendar filter when a search term
    # is present (e.g. birthday lookups).
    cal_filter = args.get("calendar", "")
    if cal_filter and not args.get("query"):
        logger.debug(
            "Dropping calendar filter '%s' on general date query",
            cal_filter,
        )
        cal_filter = ""

    events = await ctx.calendar.find_by_query(
        query=args.get("query", ""),
        date_from=date_from,
        date_to=date_to,
        calendar=cal_filter,
        user_id=ctx.user_id,
    )
    if events:
        result: dict = {"events": events, "count": len(events)}
        result["hinweis"] = (
            "Nenne NUR diese Termine. Erfinde keine zusätzlichen Termine."
        )
        return result
    return {"error": "Keine Termine gefunden"}


@register_tool("create_event")
async def handle_create_event(args: dict, chat_id: str, ctx: ToolContext) -> dict:
    if not ctx.calendar_manager:
        return {"error": "Kalender ist nicht konfiguriert"}
    try:
        writable = await ctx.calendar_manager.get_writable_source(user_id=ctx.user_id)
        if not writable:
            return {"error": "Kein beschreibbarer Kalender konfiguriert"}
        return await ctx.calendar_manager.create_event(
            source=writable,
            summary=args["summary"],
            dtstart_str=args["start"],
            dtend_str=args.get("end"),
            description=args.get("description", ""),
            location=args.get("location", ""),
        )
    except httpx.HTTPError as e:
        logger.error("HTTP error creating event: %s", e)
        return {"error": "Termin konnte nicht erstellt werden (Netzwerkfehler)"}
    except Exception as e:
        logger.error("Failed to create event: %s", e)
        return {"error": "Termin konnte nicht erstellt werden"}
