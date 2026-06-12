# SPDX-License-Identifier: AGPL-3.0-only
"""Admin user management: create, password reset, deactivate."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from argon2 import PasswordHasher

from ..types import UserInfo, UserListItem
from ..user_store import UserStore

if TYPE_CHECKING:
    from ..vikunja_provisioning import VikunjaProvisioner
    from ..vikunja_store import VikunjaCredentialStore

logger = logging.getLogger(__name__)


class DuplicateEmailError(ValueError):
    """Raised when attempting to create a user with an existing email."""


class AdminAction:
    """Admin user management with validation and password hashing."""

    def __init__(
        self,
        user_store: UserStore,
        *,
        vikunja_provisioner: VikunjaProvisioner | None = None,
        vikunja_store: VikunjaCredentialStore | None = None,
    ):
        self.user_store = user_store
        self._ph = PasswordHasher()
        self._vikunja = vikunja_provisioner
        self._vikunja_store = vikunja_store

    async def create_user(self, email: str, display_name: str, password: str) -> UserInfo:
        """Validate, hash password, create user.

        Raises ValueError on validation failure or duplicate email.
        """
        email = email.strip().lower()
        display_name = display_name.strip()
        if not email or not display_name or not password:
            raise ValueError("Alle Felder müssen ausgefüllt sein.")
        if len(password) < 12:
            raise ValueError("Passwort muss mindestens 12 Zeichen lang sein.")
        existing = await self.user_store.get_by_email(email)
        if existing:
            raise DuplicateEmailError(f"E-Mail '{email}' ist bereits vergeben.")
        hashed = self._ph.hash(password)
        user = await self.user_store.create_password_user(email, display_name, hashed)

        # Best-effort Vikunja password sync
        if self._vikunja:
            try:
                await self._vikunja.sync_password(user["id"], email, password)
            except Exception:
                logger.warning("Vikunja sync failed for new user %s", email)

        return user

    async def reset_password(self, user_id: int, password: str) -> None:
        """Validate and reset password.

        Raises ValueError for short password, KeyError if user not found.
        """
        if len(password) < 12:
            raise ValueError("Passwort muss mindestens 12 Zeichen lang sein.")
        target = await self.user_store.get_by_id(user_id)
        if not target:
            raise KeyError("User nicht gefunden.")
        hashed = self._ph.hash(password)
        await self.user_store.update_password(user_id, hashed)

        # Mark Vikunja password as out-of-sync; will be re-synced on next login
        if self._vikunja_store:
            try:
                await self._vikunja_store.set_password_synced(user_id, False)
            except Exception:
                logger.warning(
                    "Failed to mark Vikunja password as unsynced for user_id=%d",
                    user_id,
                )

    async def deactivate_user(self, user_id: int, admin_uid: int) -> None:
        """Deactivate user.

        Raises ValueError if deactivating self, KeyError if user not found.
        """
        if admin_uid == user_id:
            raise ValueError("Eigenen Account kann man nicht deaktivieren.")
        target = await self.user_store.get_by_id(user_id)
        if not target:
            raise KeyError("User nicht gefunden.")
        await self.user_store.deactivate_user(user_id)

    async def hard_delete_user(self, user_id: int, admin_uid: int) -> None:
        """Permanently delete user and all data (GDPR Art. 17).

        Raises ValueError if deleting self, KeyError if user not found.
        """
        if admin_uid == user_id:
            raise ValueError("Eigenen Account kann man nicht löschen.")
        target = await self.user_store.get_by_id(user_id)
        if not target:
            raise KeyError("User nicht gefunden.")
        await self.user_store.hard_delete_user(user_id)

    async def list_users(self) -> list[UserListItem]:
        """List all users for admin page."""
        return await self.user_store.list_all()
