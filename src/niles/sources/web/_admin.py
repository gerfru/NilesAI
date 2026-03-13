"""Admin user management routes."""

import logging

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from ._core import (
    _ensure_csrf_cookie,
    _require_admin,
    _require_admin_page,
    router,
    templates,
)

logger = logging.getLogger(__name__)


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    """Admin page: list and manage users."""
    user, error = await _require_admin_page(request)
    if error:
        return error
    assert user is not None
    admin_action = request.app.state.admin_action
    users = await admin_action.list_users()
    response = templates.TemplateResponse(
        request,
        "admin_users.html",
        {"current_user": user, "users": users, "error": None, "success": None},
    )
    _ensure_csrf_cookie(request, response)
    return response


@router.post("/api/admin/users")
async def admin_create_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
):
    """Create a new user with password authentication."""
    user, error = await _require_admin(request)
    if error:
        return error
    assert user is not None

    admin_action = request.app.state.admin_action

    try:
        new_user = await admin_action.create_user(email, display_name, password)
    except ValueError as e:
        users = await admin_action.list_users()
        # Duplicate email → 409, other validation → 400
        status = 409 if "bereits vergeben" in str(e) else 400
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {
                "current_user": user,
                "users": users,
                "error": str(e),
                "success": None,
            },
            status_code=status,
        )

    clean_email = email.strip().lower()
    clean_name = display_name.strip()
    logger.info(
        "Admin %s created user: %s (id=%s)",
        user["email"],
        clean_email,
        new_user["id"],
    )

    users = await admin_action.list_users()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "current_user": user,
            "users": users,
            "error": None,
            "success": f"User '{clean_name}' ({clean_email}) angelegt.",
        },
    )


@router.post("/api/admin/users/{user_id}/password")
async def admin_reset_password(
    request: Request,
    user_id: int,
    password: str = Form(...),
):
    """Reset password for a user (admin only)."""
    admin, error = await _require_admin(request)
    if error:
        return error
    assert admin is not None

    admin_action = request.app.state.admin_action

    try:
        await admin_action.reset_password(user_id, password)
    except ValueError as e:
        return Response(content=str(e), status_code=400)
    except KeyError as e:
        return Response(content=str(e), status_code=404)

    logger.info("Admin %s reset password for user_id=%s", admin["email"], user_id)
    return Response(
        content="Passwort geändert.",
        headers={"HX-Trigger": "userUpdated"},
    )


@router.post("/api/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(request: Request, user_id: int):
    """Deactivate a user (admin only, cannot deactivate own account)."""
    admin, error = await _require_admin(request)
    if error:
        return error
    assert admin is not None

    admin_action = request.app.state.admin_action

    try:
        await admin_action.deactivate_user(user_id, admin["uid"])
    except ValueError as e:
        return Response(content=str(e), status_code=400)
    except KeyError as e:
        return Response(content=str(e), status_code=404)

    logger.info(
        "Admin %s deactivated user_id=%s",
        admin["email"],
        user_id,
    )
    return Response(
        content="User deaktiviert.",
        headers={"HX-Trigger": "userUpdated"},
    )
