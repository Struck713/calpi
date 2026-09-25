#!/usr/bin/env python3
"""Soak analysis (US-37 D5). Standard library only; runs on the dev machine.

Usage:
  scripts/soak-analyze.py from-journal JOURNAL.txt OUT.csv     journalctl text -> CSV (used by `scripts/pi soak collect`)
  scripts/soak-analyze.py analyze scratch-soak.csv [--journal JOURNAL.txt] [--markdown out.md]
                                                    [--warmup-hours 12] [--normal-days N]

The CSV has one row per hourly `health:` line (kind=sample) or mini-run line (kind=minirun):
  kind,ts,rss_mb,fds,threads,sources,sync_procs,db_mb,wal_mb,journal_mb,uptime_s,p90_ms
Journal lines look like `2026-09-25T10:00:03+0200 calpi calpi-kiosk[123]: ... health: rss=87.3MB ...`.
Exit code: 0 all thresholds pass, 1 at least one fails, 2 bad input.
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import datetime

FIELDS = ["kind", "ts", "rss_mb", "fds", "threads", "sources", "sync_procs", "db_mb", "wal_mb",
          "journal_mb", "uptime_s", "p90_ms"]

LINE = re.compile(r"health: rss=(?P<rss_mb>[\d.]+)MB fds=(?P<fds>\d+) threads=(?P<threads>\d+) "
                  r"sources=(?P<sources>\d+) sync_procs=(?P<sync_procs>\d+) db=(?P<db_mb>[\d.]+)MB "
                  r"wal=(?P<wal_mb>[\d.]+)MB journal=(?P<journal_mb>[\d.]+MB|n/a) uptime=(?P<d>\d+)d(?P<h>\d+)h")
MINIRUN = re.compile(r"health: minirun month_nav n=(?P<n>\d+) p50=(?P<p50>[\d.]+)ms p90=(?P<p90>[\d.]+)ms")
TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)")

# thresholds (acceptance criterion 3)
RSS_SLOPE_MB_DAY = 0.5
RSS_MAX_MB = 150.0
FLAT_SPREAD = 2
DB_FLAT_FRACTION = 0.20
WAL_MAX_MB = 8.0
JOURNAL_CAP_MB = 32.0
MINIRUN_GROWTH = 0.20
BAD_JOURNAL_PATTERNS = ("Watchdog timeout", "uncaught exception", "SAFE MODE")


# ---------------------------------------------------------------- parsing
def journal_to_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = TS.match(line)
        if not m:
            continue
        ts = m.group(1)
        h = LINE.search(line)
        if h:
            g = h.groupdict()
            rows.append({"kind": "sample", "ts": ts, "rss_mb": g["rss_mb"], "fds": g["fds"],
                         "threads": g["threads"], "sources": g["sources"], "sync_procs": g["sync_procs"],
                         "db_mb": g["db_mb"], "wal_mb": g["wal_mb"],
                         "journal_mb": "" if g["journal_mb"] == "n/a" else g["journal_mb"][:-2],
                         "uptime_s": int(g["d"]) * 86400 + int(g["h"]) * 3600, "p90_ms": ""})
            continue
        r = MINIRUN.search(line)
        if r:
            rows.append({"kind": "minirun", "ts": ts, "p90_ms": r.group("p90")})
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _t(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def _num(row: dict, key: str):
    v = row.get(key, "")
    return float(v) if v not in ("", None) else None


# ---------------------------------------------------------------- statistics
def slope_per_day(ts_days: list[float], ys: list[float]) -> float:
    """Least squares: sum((t - tm)(y - ym)) / sum((t - tm)^2), t in days."""
    n = len(ts_days)
    if n < 2:
        return 0.0
    tm, ym = sum(ts_days) / n, sum(ys) / n
    den = sum((t - tm) ** 2 for t in ts_days)
    return 0.0 if den == 0 else sum((t - tm) * (y - ym) for t, y in zip(ts_days, ys)) / den


def series(rows: list[dict], key: str, warmup_s: float):
    """(days since first sample, values) for kind=sample rows after the warm-up."""
    samples = [r for r in rows if r.get("kind") == "sample"]
    if not samples:
        return [], []
    t0 = _t(samples[0]["ts"])
    xs, ys = [], []
    for r in samples:
        t = _t(r["ts"])
        v = _num(r, key)
        if t - t0 >= warmup_s and v is not None:
            xs.append((t - t0) / 86400)
            ys.append(v)
    return xs, ys


def restarts(rows: list[dict]) -> int:
    ups = [_num(r, "uptime_s") for r in rows if r.get("kind") == "sample"]
    ups = [u for u in ups if u is not None]
    return sum(1 for a, b in zip(ups, ups[1:]) if b < a)


def analyze(rows: list[dict], journal_text: str | None = None, warmup_hours: float = 12.0) -> dict:
    """Returns {"metrics": {name: {min,max,slope,n}}, "checks": [(name, ok|None, detail)], "ok": bool}."""
    warm = warmup_hours * 3600
    metrics, checks = {}, []
    for key in ("rss_mb", "fds", "threads", "sources", "sync_procs", "db_mb", "wal_mb", "journal_mb"):
        xs, ys = series(rows, key, warm)
        if ys:
            metrics[key] = {"n": len(ys), "min": min(ys), "max": max(ys), "slope_per_day": slope_per_day(xs, ys)}
    samples = [r for r in rows if r.get("kind") == "sample"]
    if not samples:
        return {"metrics": {}, "checks": [("samples", False, "no health samples")], "ok": False}
    span_days = (_t(samples[-1]["ts"]) - _t(samples[0]["ts"])) / 86400

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    m = metrics.get("rss_mb")
    if m:
        add("rss slope <= %.1f MB/day" % RSS_SLOPE_MB_DAY, m["slope_per_day"] <= RSS_SLOPE_MB_DAY,
            "%.3f MB/day" % m["slope_per_day"])
        add("rss max <= %.0f MB" % RSS_MAX_MB, m["max"] <= RSS_MAX_MB, "%.1f MB" % m["max"])
    else:
        add("rss", False, "no samples after the warm-up (%.0f h)" % warmup_hours)
    for key in ("fds", "threads", "sources"):
        m = metrics.get(key)
        if m:
            spread = m["max"] - m["min"]
            add(f"{key} flat (max-min <= {FLAT_SPREAD})", spread <= FLAT_SPREAD, f"{m['min']:.0f}..{m['max']:.0f}")
    sp = [(_num(r, "sync_procs") or 0) for r in samples]
    run = worst = 0
    for v in sp:
        run = run + 1 if v > 0 else 0
        worst = max(worst, run)
    add("no stuck sync process (never >2 consecutive samples with sync_procs>0)", worst <= 2,
        "longest run %d" % worst)
    m = metrics.get("db_mb")
    if m and m["max"] > 0:
        mid = (m["max"] + m["min"]) / 2 or 1
        add("db size flat (+-20%)", (m["max"] - m["min"]) / 2 / mid <= DB_FLAT_FRACTION,
            "%.2f..%.2f MB" % (m["min"], m["max"]))
    wal = [(_num(r, "wal_mb") or 0) for r in samples]        # WAL bound holds always, warm-up included
    add("wal <= %.0f MB always" % WAL_MAX_MB, max(wal) <= WAL_MAX_MB, "max %.2f MB" % max(wal))
    jr = [v for v in (_num(r, "journal_mb") for r in samples) if v is not None]
    if jr:
        add("journal <= %.0f MB cap" % JOURNAL_CAP_MB, max(jr) <= JOURNAL_CAP_MB, "max %.0f MB" % max(jr))
    else:
        add("journal <= cap", None, "no journal samples (journalctl unavailable)")
    mini = [float(r["p90_ms"]) for r in rows if r.get("kind") == "minirun" and r.get("p90_ms")]
    if len(mini) >= 2:
        base = mini[0]
        add("month-render p90 within +20%% of day 1 (%.0f ms)" % base,
            max(mini[1:]) <= base * (1 + MINIRUN_GROWTH), "worst %.0f ms over %d runs" % (max(mini[1:]), len(mini)))
    else:
        add("month-render p90", None, "fewer than two mini-runs")
    n_restart = restarts(rows)
    add("no restarts during the run (uptime never decreases)", n_restart == 0, "%d restart(s)" % n_restart)
    if journal_text is not None:
        for pat in BAD_JOURNAL_PATTERNS:
            n = journal_text.count(pat)
            add(f"journal has no '{pat}'", n == 0, f"{n} occurrence(s)")
        days = journal_text.count("clock: day changed")
        need = int(span_days)
        add("midnight rollover every day", days >= need, f"{days} 'clock: day changed' for {span_days:.1f} days")
    else:
        add("watchdog / crash / rollover checks", None, "pass --journal to check them")
    add("log volume <= 1 MB/day (normal mode)", None,
        "check by hand: journalctl -u calpi-kiosk -o cat --since '1 day ago' | wc -c")
    return {"metrics": metrics, "checks": checks, "ok": all(c[1] is not False for c in checks),
            "span_days": span_days, "samples": len(samples)}


# ---------------------------------------------------------------- output
def render_text(res: dict) -> str:
    out = [f"soak analysis: {res.get('samples', 0)} samples over {res.get('span_days', 0):.1f} days", "",
           "%-12s %6s %10s %10s %14s" % ("metric", "n", "min", "max", "slope/day")]
    for k, m in res["metrics"].items():
        out.append("%-12s %6d %10.2f %10.2f %14.3f" % (k, m["n"], m["min"], m["max"], m["slope_per_day"]))
    out.append("")
    for name, ok, detail in res["checks"]:
        out.append("%-5s %s (%s)" % ({True: "PASS", False: "FAIL", None: "n/a"}[ok], name, detail))
    out.append("")
    out.append("RESULT: " + ("PASS" if res["ok"] else "FAIL"))
    return "\n".join(out)


def render_markdown(res: dict) -> str:
    out = ["| metric | n | min | max | slope/day |", "|---|---|---|---|---|"]
    for k, m in res["metrics"].items():
        out.append(f"| {k} | {m['n']} | {m['min']:.2f} | {m['max']:.2f} | {m['slope_per_day']:.3f} |")
    out += ["", "| check | result | detail |", "|---|---|---|"]
    for name, ok, detail in res["checks"]:
        out.append(f"| {name} | {({True: 'PASS', False: 'FAIL', None: 'n/a'})[ok]} | {detail} |")
    out += ["", "**" + ("PASS" if res["ok"] else "FAIL") + "**"]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "from-journal":
        with open(argv[1]) as f:
            rows = journal_to_rows(f.read())
        write_csv(rows, argv[2])
        print(f"{len(rows)} rows -> {argv[2]}")
        return 0
    if len(argv) >= 2 and argv[0] == "analyze":
        journal = md = None
        warm = 12.0
        rest = argv[2:]
        i = 0
        while i < len(rest):
            if rest[i] == "--journal":
                journal = open(rest[i + 1]).read()
            elif rest[i] == "--markdown":
                md = rest[i + 1]
            elif rest[i] == "--warmup-hours":
                warm = float(rest[i + 1])
            else:
                print("unknown option", rest[i], file=sys.stderr)
                return 2
            i += 2
        try:
            rows = read_csv(argv[1])
        except OSError as e:
            print(e, file=sys.stderr)
            return 2
        res = analyze(rows, journal, warm)
        print(render_text(res))
        if md:
            with open(md, "w") as f:
                f.write(render_markdown(res) + "\n")
        return 0 if res["ok"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
