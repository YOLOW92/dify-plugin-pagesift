#!/usr/bin/env python3
"""Sample memory and CPU of one engine every 0.5 s until stopped (SIGINT/SIGTERM).

    monitor.py pagesift <out.jsonl>      # sums RSS / CPU of every `pagesift serve` process (incl. children)
    monitor.py firecrawl <out.jsonl>     # sums `docker stats` over every container of compose project "firecrawl"

Each line: {"t": unix_time, "mem_mb": ..., "cpu_pct": ..., "parts": {name: mem_mb}}
CPU is in "percent of one core" (400 = four cores busy), as docker stats reports it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

STOP = False


def _stop(*_):
    global STOP
    STOP = True


def _mem_unit(s: str) -> float:
    s = s.strip()
    for unit, mul in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("GB", 1000 / 1.048576), ("MB", 1 / 1.048576), ("kB", 1 / 1048.576), ("B", 1 / 1048576)):
        if s.endswith(unit):
            return float(s[: -len(unit)]) * mul
    return float(s)


def sample_firecrawl() -> tuple[float, float, dict]:
    ids = subprocess.run(
        ["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=firecrawl"],
        capture_output=True, text=True,
    ).stdout.split()
    if not ids:
        return 0.0, 0.0, {}
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}", *ids],
        capture_output=True, text=True,
    ).stdout
    mem = cpu = 0.0
    parts = {}
    for line in out.splitlines():
        name, usage, cpup = line.split("\t")
        m = _mem_unit(usage.split("/")[0])
        mem += m
        cpu += float(cpup.rstrip("%") or 0)
        parts[name] = round(m, 1)
    return mem, cpu, parts


_prev: dict[int, tuple[float, float]] = {}
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def _pagesift_pids() -> list[int]:
    # only the benchmark instance (port 3002), not other pagesift processes on the machine
    roots = [int(p) for p in subprocess.run(["pgrep", "-f", "pagesift serve --port 3002"], capture_output=True, text=True).stdout.split()]
    pids = set(roots)
    for r in roots:  # rendering child processes (headless Chrome), if any
        kids = subprocess.run(["pgrep", "-P", str(r)], capture_output=True, text=True).stdout.split()
        pids.update(int(k) for k in kids)
    return sorted(pids)


def sample_pagesift() -> tuple[float, float, dict]:
    mem = cpu = 0.0
    parts = {}
    now = time.monotonic()
    for pid in _pagesift_pids():
        try:
            rss = int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * PAGE / 1048576
            st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            ticks = int(st[11]) + int(st[12])
        except (FileNotFoundError, ProcessLookupError, IndexError):
            continue
        mem += rss
        parts[str(pid)] = round(rss, 1)
        if pid in _prev:
            pt, pticks = _prev[pid]
            if now > pt:
                cpu += (ticks - pticks) / TICK / (now - pt) * 100
        _prev[pid] = (now, ticks)
    return mem, cpu, parts


def main() -> None:
    engine, out = sys.argv[1], Path(sys.argv[2])
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    fn = sample_firecrawl if engine == "firecrawl" else sample_pagesift
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        while not STOP:
            t = time.time()
            mem, cpu, parts = fn()
            f.write(json.dumps({"t": t, "mem_mb": round(mem, 1), "cpu_pct": round(cpu, 1), "parts": parts}) + "\n")
            f.flush()
            time.sleep(max(0.0, 0.5 - (time.time() - t)))


if __name__ == "__main__":
    main()
