"""Render eval/results.json as eval/report.html: quality vs cost and speed vs cost.

    python3 -I eval/chart.py
"""

import json
import statistics
from pathlib import Path

EVAL = Path(__file__).resolve().parent


def points() -> list[dict]:
    results = json.loads((EVAL / "results.json").read_text())
    out = []
    for name, s in results["summary"].items():
        runs = [r for r in results["runs"] if r["config"] == name and r["rep"] > 0]
        costs = [r["cost_usd"] for r in runs if r["cost_usd"] is not None]
        out.append({
            "name": name, "label": s["label"],
            "provider": "Codex" if s["provider"] == "codex" else "Claude",
            "quality": s["quality"] * 100, "runs": s["runs"],
            "p50": s["total_ms_p50"] / 1000, "min": s["total_ms_min"] / 1000, "max": s["total_ms_max"] / 1000,
            "cost": statistics.mean(costs), "under10": s["under_10s"],
        })
    return out


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dispatcher Model Grader</title>
<style>
  :root {
    color-scheme: light;
    --surface: #fcfcfb; --surface-2: #f3f2ef; --text: #0b0b0b; --text-2: #52514e; --muted: #8a8984;
    --grid: #e6e5e1; --axis: #c9c8c3; --limit: #d03b3b;
    --codex: #2a78d6; --claude: #eb6834;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface: #1a1a19; --surface-2: #232321; --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e88;
      --grid: #2e2e2c; --axis: #4a4a46; --limit: #e66767;
      --codex: #3987e5; --claude: #d95926;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e88;
    --grid: #2e2e2c; --axis: #4a4a46; --limit: #e66767;
    --codex: #3987e5; --claude: #d95926;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--surface); color: var(--text);
         font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 860px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  h2 { font-size: 15px; margin: 32px 0 2px; }
  p { margin: 4px 0; color: var(--text-2); }
  .note { font-size: 12px; color: var(--muted); }
  .legend { display: flex; gap: 16px; margin: 12px 0 0; font-size: 12px; color: var(--text-2); }
  .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                         margin-right: 6px; vertical-align: -1px; background: var(--c); }
  .chart { position: relative; }
  svg { width: 100%; height: auto; display: block; overflow: visible; }
  svg text { fill: var(--text-2); font-size: 11px; }
  svg .label { fill: var(--text); font-size: 11.5px; }
  .tip { position: absolute; pointer-events: none; background: var(--surface-2); border: 1px solid var(--axis);
         border-radius: 6px; padding: 8px 10px; font-size: 12px; line-height: 1.45; opacity: 0;
         transition: opacity .1s; white-space: nowrap; color: var(--text); }
  .tip b { display: block; margin-bottom: 2px; }
  details { margin-top: 32px; }
  summary { cursor: pointer; color: var(--text-2); }
  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; margin-top: 8px; font-size: 13px; min-width: 560px; }
  th, td { text-align: right; padding: 4px 10px; border-bottom: 1px solid var(--grid); }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--text-2); font-weight: 600; }
</style>
</head>
<body>
<main>
  <h1>Which model should run the Linear dispatcher?</h1>
  <p>__SUBTITLE__</p>
  <div class="legend"><span style="--c: var(--codex)">Codex</span><span style="--c: var(--claude)">Claude</span></div>

  <h2>Quality vs cost</h2>
  <p class="note">Share of runs that made exactly the right dispatch call and no other tool call. Higher is better.</p>
  <div class="chart" id="quality"></div>

  <h2>Speed vs cost</h2>
  <p class="note">Median time from T3 starting the run to the dispatch call, with the fastest and slowest run. Lower is better. Linear needs a reply within 10 s of sending the webhook; the relay and T3 add about 0.6 s before this clock starts.</p>
  <div class="chart" id="speed"></div>

  <details>
    <summary>Table</summary>
    <div class="table-wrap"><table>
      <thead><tr><th>Config</th><th>Runs</th><th>Quality</th><th>Median</th><th>Range</th><th>Under 10 s</th><th>Cost / run</th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
  </details>
  <p class="note" style="margin-top:24px">Cost is the list-price equivalent from each provider's session log, priced with T3's rate table. On a subscription it shows relative cost, not what you're billed. Opus fast mode was requested but not applied, so it's left out.</p>
</main>
<script>
const DATA = __DATA__;
const W = 640, H = 300, M = { l: 52, r: 24, t: 34, b: 40 };
const X0 = Math.log10(0.003), X1 = Math.log10(0.4);
const x = c => M.l + (Math.log10(c) - X0) / (X1 - X0) * (W - M.l - M.r);
const color = p => `var(--${p.provider.toLowerCase()})`;
const money = c => c < 0.01 ? `$${c.toFixed(4)}` : `$${c.toFixed(3)}`;
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  parent?.appendChild(n); return n;
};

function chart(id, yMin, yMax, yTicks, yFmt, yOf, extra) {
  const host = document.getElementById(id);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, host);
  const tip = Object.assign(document.createElement("div"), { className: "tip" });
  host.appendChild(tip);
  const y = v => M.t + (yMax - v) / (yMax - yMin) * (H - M.t - M.b);

  for (const t of yTicks) {
    el("line", { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t), stroke: "var(--grid)" }, svg);
    el("text", { x: M.l - 8, y: y(t) + 4, "text-anchor": "end" }, svg).textContent = yFmt(t);
  }
  for (const c of [0.003, 0.01, 0.03, 0.1, 0.3]) {
    el("line", { x1: x(c), x2: x(c), y1: H - M.b, y2: H - M.b + 4, stroke: "var(--axis)" }, svg);
    el("text", { x: x(c), y: H - M.b + 18, "text-anchor": "middle" }, svg).textContent = money(c).replace(/0+$/, "");
  }
  el("line", { x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b, stroke: "var(--axis)" }, svg);
  el("text", { x: (M.l + W - M.r) / 2, y: H - 4, "text-anchor": "middle" }, svg).textContent = "Cost per dispatch (log scale)";
  extra?.(svg, y);

  DATA.forEach((p, i) => {
    const cx = x(p.cost), cy = y(yOf(p));
    if (id === "speed") {
      el("line", { x1: cx, x2: cx, y1: y(p.min), y2: y(p.max), stroke: color(p), "stroke-width": 2, "stroke-linecap": "round", opacity: .55 }, svg);
    }
    el("circle", { cx, cy, r: 6, fill: color(p), stroke: "var(--surface)", "stroke-width": 2 }, svg);
    const up = id === "quality" ? i % 2 === 0 : false;
    const label = el("text", id === "quality"
      ? { x: cx, y: up ? cy - 14 : cy + 22, "text-anchor": "middle", class: "label" }
      : { x: cx + 12, y: cy + 4, class: "label" }, svg);
    label.textContent = p.label;
    const hit = el("circle", { cx, cy, r: 16, fill: "transparent", tabindex: 0 }, svg);
    const show = () => {
      tip.innerHTML = `<b>${p.label}</b>${p.provider} · ${p.runs} runs<br>Quality ${p.quality.toFixed(0)}%<br>`
        + `Median ${p.p50.toFixed(1)} s (${p.min.toFixed(1)}–${p.max.toFixed(1)} s)<br>`
        + `${p.under10} of ${p.runs} under 10 s<br>${money(p.cost)} per dispatch`;
      const box = host.getBoundingClientRect(), s = box.width / W;
      const left = Math.min(cx * s + 12, box.width - tip.offsetWidth - 4);
      tip.style.left = `${Math.max(4, left)}px`; tip.style.top = `${cy * s + 12}px`; tip.style.opacity = 1;
    };
    hit.addEventListener("mouseenter", show); hit.addEventListener("focus", show);
    hit.addEventListener("mouseleave", () => tip.style.opacity = 0);
    hit.addEventListener("blur", () => tip.style.opacity = 0);
  });
}

chart("quality", 0, 100, [0, 25, 50, 75, 100], v => `${v}%`, p => p.quality);
chart("speed", 0, 12, [0, 2, 4, 6, 8, 10, 12], v => `${v} s`, p => p.p50, (svg, y) => {
  el("line", { x1: M.l, x2: W - M.r, y1: y(10), y2: y(10), stroke: "var(--limit)", "stroke-dasharray": "4 4", "stroke-width": 1.5 }, svg);
  el("text", { x: M.l + 6, y: y(10) - 6 }, svg).textContent = "Linear's 10 s limit";
});

document.getElementById("rows").innerHTML = DATA.map(p => `<tr><td>${p.label}</td><td>${p.runs}</td>
  <td>${p.quality.toFixed(0)}%</td><td>${p.p50.toFixed(1)} s</td><td>${p.min.toFixed(1)}–${p.max.toFixed(1)} s</td>
  <td>${p.under10} / ${p.runs}</td><td>${money(p.cost)}</td></tr>`).join("");
</script>
</body>
</html>
"""


def main() -> None:
    data = sorted(points(), key=lambda p: p["cost"])
    runs = sum(p["runs"] for p in data)
    subtitle = (f"{runs} graded runs across {len(data)} configs, each handed a real-shaped Linear webhook "
                "and asked to run one command. Every config got every run right, so cost and speed decide.")
    html = PAGE.replace("__DATA__", json.dumps(data)).replace("__SUBTITLE__", subtitle)
    (EVAL / "report.html").write_text(html)
    print(EVAL / "report.html")


if __name__ == "__main__":
    main()
