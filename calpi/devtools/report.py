"""Print a bench result as a table and check it against the US-36 D1 targets. No gi imports.

    python3 -m calpi.devtools.report bench.json      (accepts the raw JSON or a CALPI_BENCH_RESULT line)
Exit status 1 when a target is missed.
"""
from __future__ import annotations

import json
import sys

# (label, scenario, metric, field, limit, unit)
TARGETS = [
    ("Boot -> first paint (kernel clock)", "startup", "boot_to_first_paint", "p50", 35000, "ms"),
    ("Process start -> first paint", "startup", "start_to_first_paint", "p50", 3000, "ms"),
    ("Process start -> first paint with events", "startup", "start_to_events_paint", "p50", 4000, "ms"),
    ("Month change p90", "month_nav", "month_change", "p90", 150, "ms"),
    ("Month change max", "month_nav", "month_change", "max", 300, "ms"),
    ("Open day detail p90", "day_open", "day_open_bench", "p90", 150, "ms"),
    ("Back to calendar p90", "day_open", "back_to_calendar", "p90", 100, "ms"),
    ("Open Settings p90", "settings_open", "settings_open", "p90", 250, "ms"),
    ("OSK first show", "osk", "osk_show_first", "p50", 300, "ms"),
    ("OSK later show p90", "osk", "osk_show", "p90", 50, "ms"),
    ("OSK key press p90", "osk", "osk_key", "p90", 50, "ms"),
    ("Month change during sync p90", "during_sync", "month_change_sync", "p90", 150, "ms"),
]
IDLE_CPU_MAX = 2.0
RSS_MAX = 150.0
SECTION_FIRST_MAX = 400.0


def load(text: str) -> dict:
    text = text.strip()
    if "CALPI_BENCH_RESULT " in text:
        text = text.split("CALPI_BENCH_RESULT ", 1)[1].splitlines()[0]
    return json.loads(text)


def evaluate(d: dict) -> list[tuple[str, str, str, str]]:
    """Rows of (label, measured, target, verdict). Verdict is OK, MISS or -- (not measured)."""
    sc = d.get("scenarios", {})
    rows = []
    for label, scen, metric, field, limit, unit in TARGETS:
        st = sc.get(scen, {})
        st = st.get(metric) if isinstance(st, dict) else None
        if not st or not st.get("n"):
            rows.append((label, "--", f"<= {limit} {unit}", "--"))
            continue
        v = st[field]
        rows.append((label, f"{v:.0f} {unit}", f"<= {limit} {unit}", "OK" if v <= limit else "MISS"))
    first = sc.get("settings_open", {}).get("first", {})
    worst = max((v["max"] for v in first.values() if isinstance(v, dict) and v.get("n")), default=None)
    rows.append(("Settings section first open (worst)", "--" if worst is None else f"{worst:.0f} ms",
                 f"<= {SECTION_FIRST_MAX:.0f} ms", "--" if worst is None else ("OK" if worst <= SECTION_FIRST_MAX else "MISS")))
    idle = sc.get("idle", {})
    if "total_cpu_pct" in idle:
        v = idle["total_cpu_pct"]
        rows.append(("Idle CPU (app + parent)", f"{v:.2f} %", f"<= {IDLE_CPU_MAX} %", "OK" if v <= IDLE_CPU_MAX else "MISS"))
    else:
        rows.append(("Idle CPU (app + parent)", "--", f"<= {IDLE_CPU_MAX} %", "--"))
    meta = d.get("meta", {})
    rss = [v for v in (meta.get("rss_mb_start"), meta.get("rss_mb_end")) if v is not None]
    rows.append(("UI RSS (max of start/end)", f"{max(rss):.0f} MB" if rss else "--", f"<= {RSS_MAX:.0f} MB",
                 "--" if not rss else ("OK" if max(rss) <= RSS_MAX else "MISS")))
    return rows


def format_table(d: dict) -> str:
    rows = evaluate(d)
    w = max(len(r[0]) for r in rows)
    meta = d.get("meta", {})
    head = (f"build={meta.get('build')} gtk={meta.get('gtk')} python={meta.get('python')} "
            f"renderer={meta.get('renderer')} events={meta.get('events')} machine={meta.get('machine')}\n"
            f"throttled before/after: {meta.get('throttled_before')} / {meta.get('throttled_after')}  "
            f"temp before/after: {meta.get('temp_c_before')} / {meta.get('temp_c_after')}\n")
    lines = [f"{r[0]:<{w}}  {r[1]:>12}  {r[2]:>12}  {r[3]}" for r in rows]
    idle = d.get("scenarios", {}).get("idle", {})
    if "app_wakeups_per_s" in idle:
        lines.append(f"(app wakeups while idle: {idle['app_wakeups_per_s']}/s voluntary context switches)")
    return head + "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    d = load(open(argv[0]).read() if argv else sys.stdin.read())
    print(format_table(d))
    return 1 if any(r[3] == "MISS" for r in evaluate(d)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
