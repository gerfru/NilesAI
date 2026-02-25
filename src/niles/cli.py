"""Niles CLI — user management commands.

Usage:
    docker exec -it niles_core python -m niles.cli create-user \\
        --email admin@example.com --name "Admin" --password "secure-pw"
"""

import argparse
import asyncio
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Niles CLI")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create-user", help="Create a new user with password")
    create.add_argument("--email", required=True, help="User email address")
    create.add_argument("--name", required=True, help="Display name")
    create.add_argument("--password", required=True, help="Password")

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(_create_user(args.email, args.name, args.password))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
