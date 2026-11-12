#!/usr/bin/env python3
"""L1 Scale & Soak Pipeline: 1,000,000 requests soak test with continuous RSS/FD telemetry.

Usage:
    python3 run_million_soak.py [--target-requests 1000000] [--concurrency 64]
"""

import argparse
import concurrent.futures
import csv
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stress_suite import CORPUS_BASE, TARGET_BASE, get_pagesift_fd_count, get_pagesift_rss_mb, send_scrape


def run_million_pipeline(target_requests: int = 1000000, concurrency: int = 64, out_csv: Path = Path("million_soak.csv")):
    print(f"[SOAK PIPELINE] Starting {target_requests} requests soak test (concurrency={concurrency})...")
    url = f"{CORPUS_BASE}/wcxb/5105.html"

    t0 = time.perf_counter()
    completed = 0
    errors = 0

    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "completed_requests", "rss_mb", "fd_count", "qps"])

        def worker(chunk_size: int):
            nonlocal completed, errors
            for _ in range(chunk_size):
                code, _ = send_scrape(url)
                if code != 200:
                    errors += 1
                completed += 1
                if completed % 10000 == 0:
                    elapsed = time.perf_counter() - t0
                    qps = completed / elapsed if elapsed > 0 else 0
                    rss = get_pagesift_rss_mb()
                    fd = get_pagesift_fd_count()
                    writer.writerow([round(elapsed, 1), completed, rss, fd, round(qps, 1)])
                    f.flush()
                    print(f"  -> [{completed:8d}/{target_requests}] Elapsed: {elapsed:6.1f}s | QPS: {qps:6.1f} | RSS: {rss:6.1f}MB | FDs: {fd:3d} | Errors: {errors}")

        per_worker = target_requests // concurrency
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker, per_worker) for _ in range(concurrency)]
            concurrent.futures.wait(futures)

    total_time = time.perf_counter() - t0
    final_qps = completed / total_time
    print(f"\n[COMPLETE] Finished {completed} requests in {total_time:.1f}s (Avg QPS: {final_qps:.1f}, Errors: {errors})")
    print(f"Detailed telemetry logged to {out_csv.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-requests", type=int, default=1000000)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results" / "stress" / "million_soak.csv")
    args = parser.parse_args()
    run_million_pipeline(args.target_requests, args.concurrency, args.out)
