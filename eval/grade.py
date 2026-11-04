"""Grade dispatcher runs on quality, latency and cost.

    python3 -I eval/grade.py      # writes eval/results.json, prints a summary

Per run:
- quality: 1.0 if the mock got exactly the expected call and the model made no
  other tool calls, 0.75 if the call was right but it made extra tool calls,
  0 otherwise (no call, wrong arguments, or more than one dispatch).
- latency: T3 run requested -> provider turn started (boot), turn started ->
  first dispatch call (model), and the sum.
- cost: list-price equivalent from the provider's own session log, priced with
  T3's rate table (~/.t3/userdata/usage-model-rates.json).

Rep 0 is a warm-up and is left out of the summary.
"""

import json
import os
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

EVAL = Path(__file__).resolve().parent
T3_HOME = Path(os.environ.get("T3CODE_HOME", Path.home() / ".t3"))
CLAUDE_PROJECT = Path.home() / ".claude/projects" / str(EVAL.parent).replace("/", "-").replace(".", "-")
CODEX_SESSIONS = Path.home() / ".codex/sessions"
# This grading session's own transcript mentions every run id.
SKIP_TRANSCRIPTS = set(filter(None, os.environ.get("GRADER_SKIP_TRANSCRIPTS", "").split(",")))


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def find_log(run_id: str, provider: str) -> Path | None:
    files = CODEX_SESSIONS.glob("**/rollout-*.jsonl") if provider == "codex" else CLAUDE_PROJECT.glob("*.jsonl")
    needle = f"/runs/{run_id}/bin/"
    hits = [f for f in files if f.stem not in SKIP_TRANSCRIPTS and needle in f.read_text(errors="ignore")]
    return max(hits, key=lambda f: f.stat().st_mtime) if hits else None


def codex_usage(log: Path, rates: dict, tier: str | None) -> tuple[float, int, dict]:
    total, tools = {}, 0
    for line in log.read_text().splitlines():
        event = json.loads(line)
        payload = event.get("payload") or {}
        if payload.get("type") == "token_count" and payload.get("info"):
            total = payload["info"]["total_token_usage"]
        if event.get("type") == "response_item" and payload.get("type") in (
                "function_call", "custom_tool_call", "local_shell_call"):
            tools += 1
    suffix = f"_{tier}" if tier == "priority" else ""
    rate = lambda key: rates[key + suffix]
    cached = total.get("cached_input_tokens", 0)
    written = total.get("cache_write_input_tokens", 0)
    cost = ((total.get("input_tokens", 0) - cached - written) * rate("input_cost_per_token")
            + cached * rate("cache_read_input_token_cost")
            + written * rate("cache_creation_input_token_cost")
            + total.get("output_tokens", 0) * rate("output_cost_per_token"))
    return cost, tools, total


def claude_usage(log: Path, rates: dict, fast_multiplier: float) -> tuple[float, int, dict]:
    messages, tools = {}, set()
    for line in log.read_text().splitlines():
        event = json.loads(line)
        if event.get("type") != "assistant":
            continue
        message = event["message"]
        messages[message["id"]] = message["usage"]
        tools.update(block["id"] for block in message.get("content", []) if block.get("type") == "tool_use")
    cost, totals = 0.0, {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    for usage in messages.values():
        split = usage.get("cache_creation") or {}
        write_1h = split.get("ephemeral_1h_input_tokens", 0)
        write_5m = usage.get("cache_creation_input_tokens", 0) - write_1h
        one = (usage["input_tokens"] * rates["input_cost_per_token"]
               + write_5m * rates["cache_creation_input_token_cost"]
               + write_1h * rates["cache_creation_input_token_cost_above_1hr"]
               + usage.get("cache_read_input_tokens", 0) * rates["cache_read_input_token_cost"]
               + usage["output_tokens"] * rates["output_cost_per_token"])
        cost += one * (fast_multiplier if usage.get("speed") == "fast" else 1)
        totals["input"] += usage["input_tokens"]
        totals["cache_write"] += usage.get("cache_creation_input_tokens", 0)
        totals["cache_read"] += usage.get("cache_read_input_tokens", 0)
        totals["output"] += usage["output_tokens"]
    return cost, len(tools), totals


def grade_run(run: Path, configs: dict, prices: dict, db: sqlite3.Connection) -> dict:
    meta = json.loads((run / "meta.json").read_text())
    config = configs[meta["config"]]
    calls_file = run / "calls.jsonl"
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []

    # A re-run reuses its title, so take the newest thread.
    thread = db.execute("SELECT thread_id FROM orchestration_v2_projection_threads WHERE title = ? "
                        "ORDER BY created_at DESC LIMIT 1", (meta["run"],)).fetchone()
    requested = started = None
    if thread:
        requested = db.execute("SELECT MIN(requested_at) FROM orchestration_v2_projection_runs WHERE thread_id = ?",
                               thread).fetchone()[0]
        started = db.execute("SELECT MIN(started_at) FROM orchestration_v2_projection_provider_turns WHERE thread_id = ?",
                             thread).fetchone()[0]

    cost = tools = usage = None
    log = find_log(meta["run"], config["provider"])
    if log:
        rates = prices[config["price"]]
        if config["provider"] == "codex":
            cost, tools, usage = codex_usage(log, rates, config.get("tier"))
        else:
            fast = prices.get(f"azure_ai/{config['price']}-fast", {}).get("input_cost_per_token")
            base = prices.get(f"azure_ai/{config['price']}", {}).get("input_cost_per_token")
            cost, tools, usage = claude_usage(log, rates, fast / base if fast and base else 1)

    correct = len(calls) == 1 and calls[0]["argv"] == meta["expected"]
    quality = (1.0 if tools == 1 else 0.75) if correct else 0.0
    first = calls[0]["ts_ms"] if calls else None
    boot = ms(started) - ms(requested) if requested and started else None
    model = first - ms(started) if first and started else None
    return {**meta, "label": config["label"], "provider": config["provider"],
            "calls": [c["argv"] for c in calls], "correct": correct, "tool_calls": tools,
            "quality": quality, "boot_ms": boot, "model_ms": model,
            "total_ms": boot + model if boot is not None and model is not None else None,
            "cost_usd": cost, "usage": usage, "log": str(log) if log else None}


def summarize(results: list[dict], configs: dict) -> dict:
    summary = {}
    for name, config in configs.items():
        runs = [r for r in results if r["config"] == name and r["rep"] > 0]
        if not runs:
            continue
        values = lambda key: [r[key] for r in runs if r[key] is not None]
        median = lambda key: statistics.median(values(key)) if values(key) else None
        summary[name] = {
            "label": config["label"], "provider": config["provider"], "runs": len(runs),
            "quality": statistics.mean(r["quality"] for r in runs),
            "total_ms_p50": median("total_ms"), "total_ms_min": min(values("total_ms"), default=None),
            "total_ms_max": max(values("total_ms"), default=None),
            "boot_ms_p50": median("boot_ms"), "model_ms_p50": median("model_ms"),
            "cost_usd_mean": statistics.mean(values("cost_usd")) if values("cost_usd") else None,
            "under_10s": sum(1 for v in values("total_ms") if v < 10_000),
        }
    return summary


def main() -> None:
    configs = json.loads((EVAL / "configs.json").read_text())
    prices = json.loads((T3_HOME / "userdata/usage-model-rates.json").read_text())["document"]
    db = sqlite3.connect(f"file:{T3_HOME / 'userdata/statev2.sqlite'}?mode=ro", uri=True)
    results = [grade_run(run, configs, prices, db) for run in sorted((EVAL / "runs").iterdir())
               if (run / "meta.json").exists()]
    summary = summarize(results, configs)
    (EVAL / "results.json").write_text(json.dumps({"runs": results, "summary": summary}, indent=2))
    print(f"{'config':<22}{'n':>3}{'quality':>9}{'p50 s':>8}{'boot':>7}{'model':>7}{'<10s':>6}{'cost $':>9}")
    for name, s in summary.items():
        fmt = lambda v, scale=1000: f"{v / scale:.1f}" if v is not None else "-"
        cost = f"{s['cost_usd_mean']:.4f}" if s["cost_usd_mean"] is not None else "-"
        print(f"{name:<22}{s['runs']:>3}{s['quality']:>9.2f}{fmt(s['total_ms_p50']):>8}"
              f"{fmt(s['boot_ms_p50']):>7}{fmt(s['model_ms_p50']):>7}{s['under_10s']:>6}{cost:>9}")


if __name__ == "__main__":
    main()
