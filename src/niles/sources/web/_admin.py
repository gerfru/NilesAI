"""Admin user management routes."""

import logging

from argon2 import PasswordHasher
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

_ph = PasswordHasher()


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    """Admin page: list and manage users."""
    user, error = await _require_admin_page(request)
    if error:
        return error
    assert user is not None
    user_store = request.app.state.user_store
    users = await user_store.list_all()
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

    user_store = request.app.state.user_store

    # Validate input
    email = email.strip().lower()
    display_name = display_name.strip()
    if not email or not display_name or not password:
        users = await user_store.list_all()
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {
                "current_user": user,
                "users": users,
                "error": "Alle Felder müssen ausgefüllt sein.",
                "success": None,
            },
            status_code=400,
        )

    if len(password) < 8:
        users = await user_store.list_all()
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {
                "current_user": user,
                "users": users,
                "error": "Passwort muss mindestens 8 Zeichen lang sein.",
                "success": None,
            },
            status_code=400,
        )

    # Check if email already taken
    existing = await user_store.get_by_email(email)
    if existing:
        users = await user_store.list_all()
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {
                "current_user": user,
                "users": users,
                "error": f"E-Mail '{email}' ist bereits vergeben.",
                "success": None,
            },
            status_code=409,
        )

    hashed = _ph.hash(password)
    new_user = await user_store.create_password_user(email, display_name, hashed)
    logger.info(
        "Admin %s created user: %s (id=%s)", user["email"], email, new_user["id"]
    )

    users = await user_store.list_all()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "current_user": user,
            "users": users,
            "error": None,
            "success": f"User '{display_name}' ({email}) angelegt.",
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

    if len(password) < 8:
        return Response(
            content="Passwort muss mindestens 8 Zeichen lang sein.",
            status_code=400,
        )

    user_store = request.app.state.user_store
    target = await user_store.get_by_id(user_id)
    if not target:
        return Response(content="User nicht gefunden.", status_code=404)

    hashed = _ph.hash(password)
    await user_store.update_password(user_id, hashed)
    logger.info("Admin %s reset password for user_id=%s", admin["email"], user_id)
    return Response(
        content="Passwort geändert.",
        headers={"HX-Trigger": "userUpdated"},
    )


@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(request: Request, user_id: int):
    """Delete a user (admin only, cannot delete own account)."""
    admin, error = await _require_admin(request)
    if error:
        return error
    assert admin is not None

    if admin["uid"] == user_id:
        return Response(
            content="Eigenen Account kann man nicht löschen.",
            status_code=400,
        )

    user_store = request.app.state.user_store
    target = await user_store.get_by_id(user_id)
    if not target:
        return Response(content="User nicht gefunden.", status_code=404)

    await user_store.delete_user(user_id)
    logger.info(
        "Admin %s deleted user_id=%s (%s)", admin["email"], user_id, target["email"]
    )
    return Response(
        content="User gelöscht.",
        headers={"HX-Trigger": "userUpdated"},
    )
