"""Write data/sp500_history.json: point-in-time S&P 500 membership.

Today's list only holds survivors, so replaying Wikipedia's dated change log
backward recovers who was actually in the index on past dates.
"""
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import requests  # noqa: E402

from data import replay_membership  # noqa: E402

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OUT = Path(__file__).resolve().parents[1] / "data" / "sp500_history.json"


def _norm(ticker) -> str | None:
    if not isinstance(ticker, str):
        return None
    t = ticker.strip().upper().replace(".", "-")
    return t or None


def fetch() -> tuple[list[str], list[dict]]:
    html = requests.get(WIKI, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    tables = pd.read_html(io.StringIO(html))

    current = sorted({_norm(t) for t in tables[0]["Symbol"]} - {None})

    raw = tables[1]
    raw.columns = ["date", "add_ticker", "add_name", "rm_ticker", "rm_name", "reason"]
    changes = []
    for _, r in raw.iterrows():
        try:
            when = pd.to_datetime(r["date"], errors="coerce")
        except Exception:
            continue
        if pd.isna(when):
            continue
        added, removed = _norm(r["add_ticker"]), _norm(r["rm_ticker"])
        if not added and not removed:
            continue
        changes.append({
            "date": when.date().isoformat(),
            "added": added,
            "removed": removed,
            "reason": str(r["reason"]).split("[")[0].strip()[:120],
        })
    changes.sort(key=lambda c: c["date"])
    return current, changes


def main() -> None:
    current, changes = fetch()
    print(f"current members: {len(current)}")
    print(f"dated changes:   {len(changes)}  ({changes[0]['date']} → {changes[-1]['date']})")

    snapshots = {}
    for year in range(2010, date.today().year + 1):
        as_of = f"{year}-01-01"
        if as_of < changes[0]["date"]:
            continue
        snapshots[as_of] = replay_membership(as_of, current, changes)

    departed = sorted({c["removed"] for c in changes if c["removed"]} - set(current))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "source": WIKI,
        "generated": date.today().isoformat(),
        "coverage_from": changes[0]["date"],
        "note": (
            "Membership before coverage_from cannot be reconstructed from this "
            "source. Snapshots are point-in-time; `departed` lists tickers that "
            "left the index and are absent from today's list."
        ),
        "current": current,
        "changes": changes,
        "snapshots": dict(snapshots),
        "departed": departed,
    }, indent=1) + "\n")

    print(f"departed (no longer in the index): {len(departed)}")
    print(f"snapshots: {len(snapshots)} yearly, {min(snapshots)} → {max(snapshots)}")
    for y in sorted(snapshots)[:3] + sorted(snapshots)[-2:]:
        print(f"  {y}: {len(snapshots[y])} members")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
