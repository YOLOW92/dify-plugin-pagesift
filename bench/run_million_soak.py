#!/usr/bin/env python3
"""L1 Scale & Soak Pipeline: 1,000,000 requests soak test with continuous RSS/FD telemetry.

Usage:
    python3 run_million_soak.py [--target-requests 1000000] [--concurrency 32]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import http.client
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import threading
import time

BENCH_DIR = Path(__file__).resolve().parent
STRESS_RESULTS = BENCH_DIR / "results" / "stress"
STRESS_RESULTS.mkdir(parents=True, exist_ok=True)

TARGET_HOST = "127.0.0.1"
TARGET_PORT = 3002
CORPUS_URL = "http://127.0.0.1:8800/wcxb/4011.html"


def get_pagesift_rss_mb() -> float:
    page_size = os.sysconf("SC_PAGE_SIZE")
    out = subprocess.run(["pgrep", "-f", "pagesift serve --port 3002"], capture_output=True, text=True)
    pids = [int(p) for p in out.stdout.split()]
    total_rss = 0
    for pid in pids:
        try:
            statm = Path(f"/proc/{pid}/statm").read_text().split()
            rss = int(statm[1]) * page_size
            total_rss += rss
        except Exception:
            continue
    return round(total_rss / 1048576.0, 2)


def get_pagesift_fd_count() -> int:
    out = subprocess.run(["pgrep", "-f", "pagesift serve --port 3002"], capture_output=True, text=True)
    pids = [int(p) for p in out.stdout.split()]
    total_fds = 0
    for pid in pids:
        try:
            fd_dir = Path(f"/proc/{pid}/fd")
            if fd_dir.exists():
                total_fds += len(list(fd_dir.iterdir()))
        except Exception:
            continue
    return total_fds


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    idx = max(0, min(len(sv) - 1, math.ceil(p * len(sv)) - 1))
    return round(sv[idx], 3)


def run_million_soak(
    target_requests: int = 1000000,
    concurrency: int = 32,
    out_csv: Path = STRESS_RESULTS / "million_soak.csv",
    out_json: Path = STRESS_RESULTS / "million_soak_summary.json",
):
    print(f"\n========================================================")
    print(f" [MILLION SOAK TEST] 1,000,000 Extreme Soak Pipeline")
    print(f" Target   : {target_requests:,} requests")
    print(f" Workers  : {concurrency} persistent HTTP connections")
    print(f" Corpus   : {CORPUS_URL}")
    print(f" Telemetry: {out_csv.name} & {out_json.name}")
    print(f"========================================================\n")

    initial_rss = get_pagesift_rss_mb()
    initial_fd = get_pagesift_fd_count()
    print(f"[*] Initial Baseline: RSS = {initial_rss:.2f} MB, FDs = {initial_fd}")

    payload_bytes = json.dumps({
        "url": CORPUS_URL,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer bench",
        "Connection": "keep-alive",
    }

    t0 = time.perf_counter()
    completed = 0
    errors = 0
    lock = threading.Lock()

    # Telemetry records
    telemetry_records: list[dict] = []
    # Sample latencies (reservoir sampling: 20,000 samples)
    sample_cap = 20000
    latencies: list[float] = []

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    csv_file = open(out_csv, "w", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    writer.writerow(["elapsed_sec", "completed_requests", "rss_mb", "fd_count", "instant_qps"])

    checkpoint_step = 25000
    last_completed = 0
    last_time = t0

    def worker(worker_id: int, requests_to_send: int):
        nonlocal completed, errors, last_completed, last_time
        conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=10.0)

        for i in range(requests_to_send):
            req_t0 = time.perf_counter()
            status = 0
            try:
                conn.request("POST", "/v2/scrape", payload_bytes, headers)
                resp = conn.getresponse()
                resp.read()
                status = resp.status
            except Exception:
                try:
                    conn.close()
                    conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=10.0)
                except Exception:
                    pass

            req_ms = (time.perf_counter() - req_t0) * 1000.0

            with lock:
                completed += 1
                if status != 200:
                    errors += 1

                # Reservoir sampling for latency
                if len(latencies) < sample_cap:
                    latencies.append(req_ms)
                else:
                    idx = random.randint(0, completed)
                    if idx < sample_cap:
                        latencies[idx] = req_ms

                # Checkpoint telemetry
                if completed % checkpoint_step == 0 or completed == target_requests:
                    now = time.perf_counter()
                    interval_time = now - last_time
                    interval_reqs = completed - last_completed
                    instant_qps = interval_reqs / interval_time if interval_time > 0 else 0.0
                    total_elapsed = now - t0
                    overall_qps = completed / total_elapsed

                    current_rss = get_pagesift_rss_mb()
                    current_fd = get_pagesift_fd_count()

                    writer.writerow([round(total_elapsed, 2), completed, current_rss, current_fd, round(instant_qps, 1)])
                    csv_file.flush()

                    telemetry_records.append({
                        "elapsed_sec": round(total_elapsed, 2),
                        "completed": completed,
                        "rss_mb": current_rss,
                        "fd_count": current_fd,
                        "instant_qps": round(instant_qps, 1),
                        "overall_qps": round(overall_qps, 1),
                    })

                    last_completed = completed
                    last_time = now

                    print(
                        f"  -> [{completed:8,d} / {target_requests:,d}] "
                        f"Elapsed: {total_elapsed:5.1f}s | "
                        f"QPS: {instant_qps:6.1f} (Avg: {overall_qps:6.1f}) | "
                        f"RSS: {current_rss:6.2f}MB | "
                        f"FDs: {current_fd:3d} | "
                        f"Errors: {errors}"
                    )

        conn.close()

    per_worker = target_requests // concurrency
    remainder = target_requests % concurrency

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for wid in range(concurrency):
            count = per_worker + (1 if wid < remainder else 0)
            futures.append(executor.submit(worker, wid, count))
        concurrent.futures.wait(futures)

    csv_file.close()
    total_time = time.perf_counter() - t0
    final_rss = get_pagesift_rss_mb()
    final_fd = get_pagesift_fd_count()
    overall_qps = completed / total_time if total_time > 0 else 0.0

    # Linear regression on RSS over checkpoints
    if len(telemetry_records) > 1:
        xs = [r["completed"] / 10000.0 for r in telemetry_records]
        ys = [r["rss_mb"] for r in telemetry_records]
        x_mean = statistics.mean(xs)
        y_mean = statistics.mean(ys)
        denom = sum((x - x_mean) ** 2 for x in xs)
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom if denom > 0 else 0.0
    else:
        slope = 0.0

    summary_data = {
        "test_name": "million_soak_test",
        "target_requests": target_requests,
        "completed_requests": completed,
        "successful_requests": completed - errors,
        "failed_requests": errors,
        "success_rate_pct": round((completed - errors) / completed * 100.0, 4) if completed > 0 else 0.0,
        "total_elapsed_sec": round(total_time, 2),
        "overall_qps": round(overall_qps, 1),
        "concurrency": concurrency,
        "initial_rss_mb": initial_rss,
        "final_rss_mb": final_rss,
        "rss_drift_mb": round(final_rss - initial_rss, 3),
        "rss_drift_slope_mb_per_10k_req": round(slope, 6),
        "initial_fd_count": initial_fd,
        "final_fd_count": final_fd,
        "fd_delta": final_fd - initial_fd,
        "latency_sampled_count": len(latencies),
        "latency_ms": {
            "p50": pct(latencies, 0.50),
            "p90": pct(latencies, 0.90),
            "p95": pct(latencies, 0.95),
            "p99": pct(latencies, 0.99),
            "p999": pct(latencies, 0.999),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
        },
        "telemetry_checkpoints": telemetry_records,
    }

    out_json.write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n========================================================")
    print(f" [COMPLETE] 1,000,000 Soak Test Finished Successfully!")
    print(f" Total Requests : {completed:,}")
    print(f" Success Rate   : {summary_data['success_rate_pct']:.2f}% ({completed - errors:,}/{completed:,})")
    print(f" Total Duration : {total_time:.1f} s ({total_time / 60.0:.2f} min)")
    print(f" Average QPS    : {overall_qps:,.1f}")
    print(f" Latency (ms)   : p50={summary_data['latency_ms']['p50']}, p90={summary_data['latency_ms']['p90']}, p99={summary_data['latency_ms']['p99']}, p99.9={summary_data['latency_ms']['p999']}")
    print(f" Memory (RSS)   : {initial_rss:.2f} MB -> {final_rss:.2f} MB (Drift: {summary_data['rss_drift_mb']:+.3f} MB, Slope: {slope:+.6f} MB/10k)")
    print(f" File Descriptors: {initial_fd} -> {final_fd} (Delta: {final_fd - initial_fd:+d})")
    print(f" Saved Summary  : {out_json.resolve()}")
    print(f"========================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-requests", type=int, default=1000000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--out-csv", type=Path, default=STRESS_RESULTS / "million_soak.csv")
    parser.add_argument("--out-json", type=Path, default=STRESS_RESULTS / "million_soak_summary.json")
    args = parser.parse_args()

    run_million_soak(args.target_requests, args.concurrency, args.out_csv, args.out_json)
