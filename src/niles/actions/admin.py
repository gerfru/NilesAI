"""Admin user management: create, password reset, deactivate."""

from argon2 import PasswordHasher

from ..user_store import UserStore


class DuplicateEmailError(ValueError):
    """Raised when attempting to create a user with an existing email."""


class AdminAction:
    """Admin user management with validation and password hashing."""

    def __init__(self, user_store: UserStore):
        self.user_store = user_store
        self._ph = PasswordHasher()

    async def create_user(self, email: str, display_name: str, password: str) -> dict:
        """Validate, hash password, create user.

        Raises ValueError on validation failure or duplicate email.
        """
        email = email.strip().lower()
        display_name = display_name.strip()
        if not email or not display_name or not password:
            raise ValueError("Alle Felder müssen ausgefüllt sein.")
        if len(password) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein.")
        existing = await self.user_store.get_by_email(email)
        if existing:
            raise DuplicateEmailError(f"E-Mail '{email}' ist bereits vergeben.")
        hashed = self._ph.hash(password)
        return await self.user_store.create_password_user(email, display_name, hashed)

    async def reset_password(self, user_id: int, password: str) -> None:
        """Validate and reset password.

        Raises ValueError for short password, KeyError if user not found.
        """
        if len(password) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein.")
        target = await self.user_store.get_by_id(user_id)
        if not target:
            raise KeyError("User nicht gefunden.")
        hashed = self._ph.hash(password)
        await self.user_store.update_password(user_id, hashed)

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

    async def list_users(self) -> list[dict]:
        """List all users for admin page."""
        return await self.user_store.list_all()
