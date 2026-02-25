"""Niles CLI — user management commands.

Usage:
    # Interactive (password prompt, not visible in ps):
    docker exec -it niles_core python -m niles.cli create-user \\
        --email admin@example.com --name "Admin"

    # Non-interactive (for scripts):
    echo "secure-pw" | docker exec -i niles_core python -m niles.cli create-user \\
        --email admin@example.com --name "Admin" --password-stdin
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


async def _create_user(email: str, name: str, password: str) -> None:
    settings = Settings()
    pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=1,
        max_size=2,
    )
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


def _read_password(args) -> str:
    """Read password from --password-stdin or interactive prompt."""
    if args.password_stdin:
        pw = sys.stdin.readline().rstrip("\n")
        if not pw:
            print("Error: empty password from stdin")
            sys.exit(1)
        return pw
    return getpass.getpass("Password (min 8 chars): ")


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

    args = parser.parse_args()
    if args.command == "create-user":
        password = _read_password(args)
        if len(password) < 8:
            print("Error: password must be at least 8 characters")
            sys.exit(1)
        asyncio.run(_create_user(args.email, args.name, password))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
