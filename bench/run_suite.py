#!/usr/bin/env python3
"""Master Benchmark Suite: Automated PageSift vs. Firecrawl (v2 API) Comparison.

Runs:
1. Concurrency 1 (single-thread latency, extraction quality against Ground Truth, and memory monitor)
2. Concurrency 4 (throughput under multi-worker load)
3. Full evaluation & generation of JSON, Markdown, and Visual HTML reports.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"
RAW_DIR = RESULTS_DIR / "raw"
CORPUS_DIR = BENCH_DIR / "corpus"


def check_servers():
    print("[*] Verifying all benchmark services...")
    import urllib.request

    services = [
        ("Corpus Server", "http://127.0.0.1:8800/wcxb/4011.html"),
        ("PageSift Server", "http://127.0.0.1:3002/healthz"),
        ("Firecrawl API", "http://127.0.0.1:3012/v1/scrape"),  # POST / 405 or 200
    ]
    for name, url in services:
        try:
            req = urllib.request.Request(url, method="GET" if "scrape" not in url else "OPTIONS")
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"    [+] {name} is READY (HTTP {resp.status})")
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 200):
                print(f"    [+] {name} is READY (HTTP {e.code})")
            else:
                print(f"    [-] {name} error: {e}")
                sys.exit(1)
        except Exception as e:
            print(f"    [-] {name} connection failed: {e}")
            sys.exit(1)


def run_monitored_scrape(engine: str, dataset: str, concurrency: int, tag: str = ""):
    tag_suffix = f"-{tag}" if tag else ""
    run_name = f"{engine}-{dataset}-v2-c{concurrency}{tag_suffix}"
    raw_output = RAW_DIR / f"{run_name}.jsonl"
    mon_output = RAW_DIR / f"{run_name}.monitor.jsonl"

    print(f"\n========================================================")
    print(f" Running: {engine.upper()} on '{dataset}' (c={concurrency})")
    print(f" Output : {raw_output.name}")
    print(f"========================================================")

    # Start monitor process
    mon_proc = subprocess.Popen(
        [sys.executable, str(BENCH_DIR / "monitor.py"), engine, str(mon_output)]
    )

    try:
        time.sleep(1.0)  # baseline sample
        cmd = [
            sys.executable,
            str(BENCH_DIR / "scrape.py"),
            engine,
            dataset,
            "--api-version", "v2",
            "--concurrency", str(concurrency),
        ]
        if tag:
            cmd.extend(["--tag", tag])

        t0 = time.time()
        res = subprocess.run(cmd, check=True)
        elapsed = time.time() - t0
        print(f"    Finished {engine} run in {elapsed:.2f} s")
    finally:
        # Stop monitor process
        mon_proc.terminate()
        try:
            mon_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            mon_proc.kill()

    return raw_output


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    check_servers()

    dataset = "wcxb_sample50"

    # 1. Single-thread run: PageSift
    print("\n>>> Phase 1: Single-thread Latency & Quality (PageSift)")
    ps_c1 = run_monitored_scrape("pagesift", dataset, concurrency=1)

    # 2. Single-thread run: Firecrawl
    print("\n>>> Phase 2: Single-thread Latency & Quality (Firecrawl)")
    fc_c1 = run_monitored_scrape("firecrawl", dataset, concurrency=1)

    # 3. Multi-concurrency run: PageSift (c=4)
    print("\n>>> Phase 3: Multi-concurrency Throughput (PageSift c=4)")
    ps_c4 = run_monitored_scrape("pagesift", dataset, concurrency=4)

    # 4. Multi-concurrency run: Firecrawl (c=4)
    print("\n>>> Phase 4: Multi-concurrency Throughput (Firecrawl c=4)")
    fc_c4 = run_monitored_scrape("firecrawl", dataset, concurrency=4)

    # 5. Evaluate and save summary
    print("\n>>> Phase 5: Generating Evaluation Summary & Reports")
    manifest = CORPUS_DIR / f"{dataset}.jsonl"
    eval_cmd = [
        sys.executable,
        str(BENCH_DIR / "evaluate.py"),
        str(ps_c1),
        str(fc_c1),
        "--manifest", str(manifest),
        "--save-summary", str(RESULTS_DIR / "summary.json"),
    ]
    subprocess.run(eval_cmd, check=True)

    # Also evaluate c=4 throughputs and inject into summary.json
    from evaluate import evaluate_run
    p_c4_eval = evaluate_run(ps_c4, manifest)
    f_c4_eval = evaluate_run(fc_c4, manifest)

    summary_file = RESULTS_DIR / "summary.json"
    data = json.loads(summary_file.read_text())
    data["concurrency_sweep"] = {
        "pagesift": {
            "c1_qps": data["pagesift"]["qps"],
            "c1_p50_ms": data["pagesift"]["latency_ms"]["p50"],
            "c4_qps": p_c4_eval["qps"],
            "c4_p50_ms": p_c4_eval["latency_ms"]["p50"],
            "c4_wall_s": p_c4_eval["wall_time_s"],
        },
        "firecrawl": {
            "c1_qps": data["firecrawl"]["qps"],
            "c1_p50_ms": data["firecrawl"]["latency_ms"]["p50"],
            "c4_qps": f_c4_eval["qps"],
            "c4_p50_ms": f_c4_eval["latency_ms"]["p50"],
            "c4_wall_s": f_c4_eval["wall_time_s"],
        }
    }
    summary_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # Generate visual HTML report and Markdown report
    gen_reports_cmd = [sys.executable, str(BENCH_DIR / "generate_reports.py")]
    subprocess.run(gen_reports_cmd, check=True)

    print("\n[✓] Benchmark Suite Finished Successfully!")


if __name__ == "__main__":
    main()
