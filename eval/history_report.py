"""Show recorded evaluation runs as a trend, newest last.

    python eval/history_report.py                 # everything
    python eval/history_report.py retrieval       # one kind
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import history  # noqa: E402

COLUMNS = ("recall_at_1", "recall_at_3", "mrr",
           "faithfulness", "context_precision", "context_recall")


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else None
    runs = history.load(kind)
    if not runs:
        where = f" of kind {kind!r}" if kind else ""
        print(f"No runs{where} recorded yet. Run `task eval:retrieval` first.")
        return

    print(f"{len(runs)} run(s) in {history.HISTORY.name}\n")

    # Group by (kind, strategy/model) so each series is comparable.
    series: dict[tuple, list] = defaultdict(list)
    for r in runs:
        cfg = r.get("config", {})
        series[(r["kind"], cfg.get("strategy") or cfg.get("model") or "-")].append(r)

    for (run_kind, variant), group in sorted(series.items()):
        metrics = [m for m in COLUMNS if m in group[-1].get("metrics", {})]
        head = f"{'when':<20}{'commit':<10}{'chunks':>7}"
        head += "".join(f"{m.replace('recall_at_', 'r@'):>10}" for m in metrics)
        print(f"── {run_kind} · {variant} " + "─" * max(0, len(head) - len(run_kind) - len(variant) - 6))
        print(head)
        for r in group:
            stamp = r["ts"].replace("T", " ").rstrip("Z")
            commit = (r.get("commit") or "-") + ("*" if r.get("dirty") else "")
            row = f"{stamp:<20}{commit:<10}{r.get('corpus', {}).get('chunks', '-'):>7}"
            row += "".join(f"{r['metrics'].get(m, float('nan')):>10.3f}" for m in metrics)
            print(row)

        if len(group) >= 2:
            deltas = history.compare(group[-1]["metrics"], group[-2])
            regressions = [n for n, d in deltas.items() if d["direction"] == "worse"]
            gains = [n for n, d in deltas.items() if d["direction"] == "better"]
            if regressions:
                print(f"  ! last run regressed: {', '.join(regressions)}")
            elif gains:
                print(f"  last run improved: {', '.join(gains)}")
        print()

    print("* = uncommitted changes in the working tree when the run happened")


if __name__ == "__main__":
    main()
