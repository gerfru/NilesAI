"""Niles CLI — user management commands.

Usage:
    # Create user (interactive):
    docker exec -it niles_core python -m niles.cli create-user \\
        --email admin@example.com --name "Admin"

    # Create user (non-interactive):
    echo "secure-pw" | docker exec -i niles_core python -m niles.cli create-user \\
        --email admin@example.com --name "Admin" --password-stdin

    # Reset password (interactive):
    docker exec -it niles_core python -m niles.cli reset-password \\
        --email admin@example.com

    # Reset password (non-interactive):
    echo "new-pw" | docker exec -i niles_core python -m niles.cli reset-password \\
        --email admin@example.com --password-stdin
"""

import argparse
import asyncio
import getpass
import sys

import asyncpg
from argon2 import PasswordHasher

from .config import Settings
from .user_store import UserStore

ph = PasswordHasher()


async def _get_pool():
    settings = Settings()
    return await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=1,
        max_size=2,
    )


async def _reset_password(email: str, password: str) -> None:
    pool = await _get_pool()
    try:
        store = UserStore(pool)
        await store.initialize()

        user = await store.get_by_email(email)
        if not user:
            print(f"Error: No user found with email '{email}'")
            sys.exit(1)

        hashed = ph.hash(password)
        updated = await store.update_password(user["id"], hashed)
        if updated:
            print(f"Password reset for {email} (id={user['id']})")
        else:
            print(f"Error: Could not update password for '{email}'")
            sys.exit(1)
    finally:
        await pool.close()


async def _create_user(email: str, name: str, password: str) -> None:
    pool = await _get_pool()
    try:
        store = UserStore(pool)
        await store.initialize()

        # Check if email already exists
        existing = await store.get_by_email(email)
        if existing:
            print(
                f"Error: User with email '{email}' already exists (id={existing['id']})"
            )
            sys.exit(1)

        hashed = ph.hash(password)
        user = await store.create_password_user(email, name, hashed)
        admin_str = " (admin)" if user.get("is_admin") else ""
        print(f"User created: {user['email']} (id={user['id']}){admin_str}")
    finally:
        await pool.close()


async def _delete_user(email: str, confirm: bool) -> None:
    pool = await _get_pool()
    try:
        store = UserStore(pool)
        await store.initialize()

        user = await store.get_by_email(email)
        if not user:
            print(f"Error: No user found with email '{email}'")
            sys.exit(1)

        if not confirm:
            answer = input(
                f"Permanently delete user '{email}' (id={user['id']}) "
                "and ALL associated data? [y/N]: "
            )
            if answer.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                sys.exit(0)

        deleted = await store.hard_delete_user(user["id"])
        if deleted:
            print(f"User '{email}' (id={user['id']}) and all data permanently deleted.")
        else:
            print(f"Error: Could not delete user '{email}'")
            sys.exit(1)
    finally:
        await pool.close()


def _read_password(args) -> str:
    """Read password from --password-stdin or interactive prompt."""
    if args.password_stdin:
        pw = sys.stdin.readline().rstrip("\n")
        if not pw:
            print("Error: empty password from stdin")
            sys.exit(1)
        return pw
    return getpass.getpass("Password (min 12 chars): ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Niles CLI")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create-user", help="Create a new user with password")
    create.add_argument("--email", required=True, help="User email address")
    create.add_argument("--name", required=True, help="Display name")
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read password from stdin (for scripts)",
    )

    reset = sub.add_parser("reset-password", help="Reset password for existing user")
    reset.add_argument("--email", required=True, help="User email address")
    reset.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read password from stdin (for scripts)",
    )

    delete = sub.add_parser(
        "delete-user", help="Permanently delete a user and all data (GDPR Art. 17)"
    )
    delete.add_argument("--email", required=True, help="User email address")
    delete.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt (for scripts)",
    )

    args = parser.parse_args()
    if args.command == "create-user":
        password = _read_password(args)
        if len(password) < 12:
            print("Error: password must be at least 12 characters")
            sys.exit(1)
        asyncio.run(_create_user(args.email, args.name, password))
    elif args.command == "reset-password":
        password = _read_password(args)
        if len(password) < 12:
            print("Error: password must be at least 12 characters")
            sys.exit(1)
        asyncio.run(_reset_password(args.email, password))
    elif args.command == "delete-user":
        asyncio.run(_delete_user(args.email, args.confirm))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
