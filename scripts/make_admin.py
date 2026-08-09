#!/usr/bin/env python3
"""Grant or revoke site admin for an existing user.

Admin is never granted by registration order. Either set ADMIN_USERNAME before
the account is created, or run this against a running deployment's database.

    python scripts/make_admin.py arthur          # promote
    python scripts/make_admin.py arthur --revoke # demote
    python scripts/make_admin.py --list          # show current users

DB_PATH is honoured, so this works against a container volume:
    DB_PATH=/app/db/app.db python scripts/make_admin.py arthur
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Grant or revoke site admin.")
    ap.add_argument("username", nargs="?", help="user to promote or demote")
    ap.add_argument("--revoke", action="store_true", help="remove admin instead of granting it")
    ap.add_argument("--list", action="store_true", help="list users and exit")
    args = ap.parse_args()

    db.init_db()

    if args.list:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT username, is_admin, created_at FROM users ORDER BY id"
            ).fetchall()
        if not rows:
            print("No users yet.")
            return 0
        print(f"{'username':<34} {'admin':<7} created")
        for r in rows:
            print(f"{r['username']:<34} {'yes' if r['is_admin'] else 'no':<7} {r['created_at']}")
        return 0

    if not args.username:
        ap.error("username is required unless --list is given")

    if not db.set_admin(args.username, not args.revoke):
        print(f"No user named {args.username!r}. Use --list to see existing users.",
              file=sys.stderr)
        return 1

    verb = "revoked from" if args.revoke else "granted to"
    print(f"Admin {verb} {args.username!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
