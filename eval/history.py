"""Append-only log of eval runs (eval/history.jsonl), stamped with git commit and
dirty state so every number traces back to the code that produced it."""
import json
import os
import subprocess
import time
from pathlib import Path

HISTORY = Path(__file__).parent / "history.jsonl"

# Headline metrics; for all of them larger is better, which labels deltas gain/loss.
METRICS = ("recall_at_1", "recall_at_3", "mrr",
           "faithfulness", "context_precision", "context_recall")
HIGHER_IS_BETTER = set(METRICS)


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip()
    except Exception:
        return ""


def _provenance() -> dict:
    dirty = bool(_git("status", "--porcelain"))
    return {
        "commit": _git("rev-parse", "--short", "HEAD") or None,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD") or None,
        # A dirty tree means the commit alone doesn't identify the code that ran.
        "dirty": dirty,
    }


def record(kind: str, metrics: dict, *, config: dict | None = None,
           corpus: dict | None = None, notes: str | None = None) -> dict:
    """Append one run. `config` is what was varied, `corpus` the size of what was indexed."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        **_provenance(),
        "config": config or {},
        "corpus": corpus or {},
        "metrics": {k: (round(v, 4) if isinstance(v, (int, float)) else v)
                    for k, v in metrics.items()},
    }
    if notes:
        entry["notes"] = notes
    with HISTORY.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def load(kind: str | None = None, config_match: dict | None = None) -> list[dict]:
    if not HISTORY.exists():
        return []
    runs = []
    for line in HISTORY.read_text().splitlines():
        if not line.strip():
            continue
        try:
            run = json.loads(line)
        except json.JSONDecodeError:
            continue  # a partially written line shouldn't break reporting
        if kind and run.get("kind") != kind:
            continue
        if config_match and any(run.get("config", {}).get(k) != v
                                for k, v in config_match.items()):
            continue
        runs.append(run)
    return runs


def previous(kind: str, config_match: dict | None = None) -> dict | None:
    runs = load(kind, config_match)
    return runs[-1] if runs else None


def compare(current: dict, prior: dict | None) -> dict[str, dict]:
    if not prior:
        return {}
    out = {}
    for name, now in current.items():
        before = prior.get("metrics", {}).get(name)
        if not isinstance(now, (int, float)) or not isinstance(before, (int, float)):
            continue
        delta = round(now - before, 4)
        if delta == 0:
            direction = "flat"
        elif name in HIGHER_IS_BETTER:
            direction = "better" if delta > 0 else "worse"
        else:
            direction = "up" if delta > 0 else "down"
        out[name] = {"before": before, "after": now, "delta": delta,
                     "direction": direction}
    return out


def format_deltas(deltas: dict[str, dict], prior: dict) -> str:
    if not deltas:
        return ""
    arrow = {"better": "▲", "worse": "▼", "flat": "=", "up": "▲", "down": "▼"}
    stamp = prior.get("commit") or prior.get("ts", "")
    lines = [f"\nvs previous run ({stamp}{' dirty' if prior.get('dirty') else ''}):"]
    for name, d in deltas.items():
        sign = "+" if d["delta"] > 0 else ""
        lines.append(
            f"  {arrow[d['direction']]} {name:18} {d['before']:.3f} → {d['after']:.3f}"
            f"  ({sign}{d['delta']:.3f})"
        )
    regressions = [n for n, d in deltas.items() if d["direction"] == "worse"]
    if regressions:
        lines.append(f"  ! regressed: {', '.join(regressions)}")
    return "\n".join(lines)


def enabled() -> bool:
    """Set EVAL_NO_HISTORY=1 to score something without polluting the log."""
    return os.environ.get("EVAL_NO_HISTORY", "") not in ("1", "true", "True")
