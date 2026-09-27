"""Create or promote an admin user (an existing user's password is reset).

    ADMIN_USER=arthur.kim ADMIN_PASS='your-password' python scripts/create_admin.py
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
    if db.upsert_admin(username, hash_password(password)):
        print(f"Created admin user {username}")
    else:
        print(f"Updated {username}: password reset, admin granted")


if __name__ == "__main__":
    main()
