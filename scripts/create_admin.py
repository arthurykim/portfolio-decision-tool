"""Create or promote an admin user.

Credentials come from the environment so nothing secret lands in the repo:

    ADMIN_USER=arthur.kim ADMIN_PASS='your-password' python scripts/create_admin.py

If the user already exists, their password is reset and they are made admin.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import load_env  # noqa: E402

load_env()

import db  # noqa: E402
from auth import USERNAME_RE, hash_password  # noqa: E402


def main() -> None:
    username = os.environ.get("ADMIN_USER")
    password = os.environ.get("ADMIN_PASS")
    if not username or not password:
        sys.exit("Set ADMIN_USER and ADMIN_PASS environment variables")
    if not USERNAME_RE.match(username):
        sys.exit("Username must be 3-32 chars: letters, digits, dot, underscore, hyphen")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters")

    db.init_db()
    existing = db.get_user_by_name(username)
    with db.connect() as conn:
        if existing:
            conn.execute(
                "UPDATE users SET password_hash = ?, is_admin = 1 WHERE id = ?",
                (hash_password(password), existing["id"]),
            )
            print(f"Updated {username}: password reset, admin granted")
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                (username, hash_password(password)),
            )
            print(f"Created admin user {username}")


if __name__ == "__main__":
    main()
