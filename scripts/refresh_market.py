"""Refresh price data and write data/market_snapshot.json (run hourly by CI)."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data import load_universe, period_returns  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "market_snapshot.json"


def main() -> None:
    prices = load_universe(refresh=True)
    snapshot = {
        "as_of": prices.index[-1].date().isoformat(),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "funds": [
            {k: f[k] for k in ("ticker", "name", "price", "returns")}
            for f in period_returns(prices)
        ],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"wrote {OUT} (as of {snapshot['as_of']})")


if __name__ == "__main__":
    main()
