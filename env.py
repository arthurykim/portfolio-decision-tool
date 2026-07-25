"""Load key=value pairs from a local .env file. Stdlib only, no dependency.

Real environment variables always win, so an exported value overrides the file.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # A blank value means "not set" — exporting "" would break callers that
        # do int(os.environ.get(NAME, default)), since the default never applies.
        if key and value and key not in os.environ:
            os.environ[key] = value
