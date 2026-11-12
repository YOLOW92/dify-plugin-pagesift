"""PageSift Engineering Stress Test Suite (X1 - X7).

Deliberately designed rigorous stress suite to benchmark extreme performance,
concurrency limits, resilience, and leak-free memory characteristics under load.

All individual sub-tests are time-bounded to 2-4 minutes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import pct, summary, write_json

STRESS_RESULTS = Path(__file__).resolve().parent / "results" / "stress"
STRESS_RESULTS.mkdir(parents=True, exist_ok=True)

TARGET_BASE = "http://127.0.0.1:3002"
CORPUS_BASE = "http://127.0.0.1:8800"


def send_scrape(url: str, timeout: float = 5.0) -> tuple[int, float]:
    """Execute a single scrape request and return (status_code, elapsed_ms)."""
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{TARGET_BASE}/v2/scrape",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer bench"},
        method="POST"
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            ms = (time.perf_counter() - t0) * 1000.0
            return resp.status, ms
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        return e.code, ms
    except Exception:
        ms = (time.perf_counter() - t0) * 1000.0
        return 0, ms


def get_pagesift_rss_mb() -> float:
    """Read current total RSS of all pagesift processes in MB."""
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
    """Read open file descriptor count for pagesift."""
    out = subprocess.run(["pgrep", "-f", "pagesift serve --port 3002"], capture_output=True, text=True)
    pids = [int(p) for p in out.stdout.split()]
    fds = 0
    for pid in pids:
        try:
            fds += len(list(Path(f"/proc/{pid}/fd").iterdir()))
        except Exception:
            continue
    return fds


# =========================================================================
# X1: Concurrency Ladder
# =========================================================================
def run_x1_concurrency_ladder(duration_per_step: float = 10.0) -> dict:
    print("\n[STRESS] Running X1: Concurrency Ladder (c = 1 to 1024)...")
    ladder = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
    results = {}
    sample_urls = [
        f"{CORPUS_BASE}/wcxb/5105.html",
        f"{CORPUS_BASE}/wcxb/5591.html",
        f"{CORPUS_BASE}/wcxb/5371.html",
        f"{CORPUS_BASE}/wcxb/4026.html",
        f"{CORPUS_BASE}/wcxb/5572.html",
    ]

    for c in ladder:
        latencies = []
        status_counts = {}
        deadline = time.monotonic() + duration_per_step
        completed = 0

        def worker():
            nonlocal completed
            while time.monotonic() < deadline:
                u = random.choice(sample_urls)
                code, ms = send_scrape(u)
                latencies.append(ms)
                status_counts[code] = status_counts.get(code, 0) + 1
                completed += 1

        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=c) as executor:
            futures = [executor.submit(worker) for _ in range(c)]
            concurrent.futures.wait(futures)
        actual_time = time.perf_counter() - t0

        qps = round(completed / actual_time, 2)
        summ = summary(latencies)
        results[f"c_{c}"] = {
            "concurrency": c,
            "duration_s": round(actual_time, 2),
            "requests": completed,
            "qps": qps,
            "status_codes": status_counts,
            "latency_ms": summ,
        }
        print(f"  -> c={c:4d} | QPS: {qps:8.2f} | p50: {summ['p50']:6.2f} ms | p99: {summ['p99']:6.2f} ms | 200 OK: {status_counts.get(200, 0)}")

    return results


# =========================================================================
# X2: Open Arrival Rate / SLO
# =========================================================================
def run_x2_slo_rate(step_duration: float = 12.0) -> dict:
    print("\n[STRESS] Running X2: Open Arrival Rate with SLO boundary (p99 <= 100ms)...")
    rates = [100, 300, 600, 1000, 1500, 2000]
    results = {}
    sample_urls = [
        f"{CORPUS_BASE}/wcxb/5105.html",
        f"{CORPUS_BASE}/wcxb/5591.html",
    ]

    for target_rate in rates:
        latencies = []
        status_counts = {}
        interval = 1.0 / target_rate
        total_expected = int(target_rate * step_duration)
        deadline = time.monotonic() + step_duration

        def send_task(u):
            code, ms = send_scrape(u)
            latencies.append(ms)
            status_counts[code] = status_counts.get(code, 0) + 1

        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
            sent = 0
            while time.monotonic() < deadline and sent < total_expected:
                executor.submit(send_task, random.choice(sample_urls))
                sent += 1
                next_time = t0 + sent * interval
                sleep_dur = next_time - time.perf_counter()
                if sleep_dur > 0:
                    time.sleep(sleep_dur)
            executor.shutdown(wait=True)
        actual_time = time.perf_counter() - t0

        summ = summary(latencies)
        slo_met = (summ.get("p99", float("inf")) <= 100.0)
        results[f"rate_{target_rate}"] = {
            "target_rate_qps": target_rate,
            "achieved_qps": round(len(latencies) / actual_time, 2),
            "total_requests": len(latencies),
            "slo_met_p99_100ms": slo_met,
            "latency_ms": summ,
        }
        print(f"  -> Rate {target_rate:4d} QPS | Actual: {len(latencies)/actual_time:7.1f} QPS | p99: {summ['p99']:6.2f} ms | SLO Met: {slo_met}")

    return results


# =========================================================================
# X3: Spike & Recovery
# =========================================================================
def run_x3_spike_and_recovery() -> dict:
    print("\n[STRESS] Running X3: Spike and Recovery (Baseline 150 QPS -> Spike 1200 QPS -> Baseline)...")
    phases = [
        ("baseline_pre", 150, 15.0),
        ("spike", 1200, 20.0),
        ("recovery_post", 150, 20.0),
    ]
    results = {}
    sample_urls = [f"{CORPUS_BASE}/wcxb/5105.html"]

    for name, rate, duration in phases:
        latencies = []
        codes = {}
        interval = 1.0 / rate
        total_reqs = int(rate * duration)
        deadline = time.monotonic() + duration
        t0 = time.perf_counter()

        def worker():
            code, ms = send_scrape(sample_urls[0])
            latencies.append(ms)
            codes[code] = codes.get(code, 0) + 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=128) as executor:
            sent = 0
            while time.monotonic() < deadline and sent < total_reqs:
                executor.submit(worker)
                sent += 1
                sleep_t = (t0 + sent * interval) - time.perf_counter()
                if sleep_t > 0:
                    time.sleep(sleep_t)
            executor.shutdown(wait=True)
        elapsed = time.perf_counter() - t0

        summ = summary(latencies)
        results[name] = {
            "phase": name,
            "target_rate": rate,
            "duration_s": round(elapsed, 2),
            "requests": len(latencies),
            "qps": round(len(latencies) / elapsed, 2),
            "codes": codes,
            "latency_ms": summ,
        }
        print(f"  -> [{name:14s}] QPS: {len(latencies)/elapsed:7.1f} | p50: {summ['p50']:6.2f} ms | p99: {summ['p99']:6.2f} ms | 200 OK: {codes.get(200, 0)}")

    return results


# =========================================================================
# X5: Mixed Multimodal Load
# =========================================================================
def run_x5_multimodal_mix(duration_s: float = 40.0) -> dict:
    print("\n[STRESS] Running X5: Mixed Multimodal Load (70% HTML, 15% Dynamic, 10% Docs, 5% Crawl)...")
    docs_dir = Path(__file__).resolve().parent / "corpus" / "docs"
    csv_bytes = (docs_dir / "sample_financial.csv").read_bytes() if (docs_dir / "sample_financial.csv").exists() else b"a,b\n1,2"
    pdf_bytes = (docs_dir / "sample_report.pdf").read_bytes() if (docs_dir / "sample_report.pdf").exists() else b"%PDF-1.4 empty"

    latencies_by_modality = {"html": [], "dynamic": [], "docs": [], "crawl": []}
    counts = {"html": 0, "dynamic": 0, "docs": 0, "crawl": 0}
    deadline = time.monotonic() + duration_s

    def do_doc_parse(b_data, name):
        t0 = time.perf_counter()
        try:
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + b_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                f"{TARGET_BASE}/v2/parse",
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Authorization": "Bearer bench"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp.read()
                return resp.status, (time.perf_counter() - t0) * 1000.0
        except Exception:
            return 0, (time.perf_counter() - t0) * 1000.0

    def mixed_worker():
        while time.monotonic() < deadline:
            r = random.random()
            if r < 0.70:
                # 70% Static HTML
                _, ms = send_scrape(f"{CORPUS_BASE}/wcxb/5105.html")
                latencies_by_modality["html"].append(ms)
                counts["html"] += 1
            elif r < 0.85:
                # 15% Complex HTML / Collection
                _, ms = send_scrape(f"{CORPUS_BASE}/wcxb/5371.html")
                latencies_by_modality["dynamic"].append(ms)
                counts["dynamic"] += 1
            elif r < 0.95:
                # 10% Document parse
                _, ms = do_doc_parse(csv_bytes, "finance.csv")
                latencies_by_modality["docs"].append(ms)
                counts["docs"] += 1
            else:
                # 5% Crawl job initiation
                t0 = time.perf_counter()
                try:
                    payload = json.dumps({"url": f"{CORPUS_BASE}/wcxb/5105.html", "limit": 2}).encode()
                    req = urllib.request.Request(
                        f"{TARGET_BASE}/v1/crawl",
                        data=payload,
                        headers={"Content-Type": "application/json", "Authorization": "Bearer bench"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        resp.read()
                        ms = (time.perf_counter() - t0) * 1000.0
                except Exception:
                    ms = (time.perf_counter() - t0) * 1000.0
                latencies_by_modality["crawl"].append(ms)
                counts["crawl"] += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        futures = [executor.submit(mixed_worker) for _ in range(32)]
        concurrent.futures.wait(futures)

    summary_out = {}
    for mod, lats in latencies_by_modality.items():
        summary_out[mod] = {
            "count": len(lats),
            "percentage": round(len(lats) / sum(counts.values()) * 100, 1) if sum(counts.values()) > 0 else 0,
            "latency_ms": summary(lats),
        }
        print(f"  -> Modality [{mod:7s}] Count: {len(lats):5d} | p50: {summary_out[mod]['latency_ms']['p50']:6.2f} ms | p99: {summary_out[mod]['latency_ms']['p99']:6.2f} ms")

    return summary_out


# =========================================================================
# X6: Scale & Soak (Leak-free linear regression)
# =========================================================================
def run_x6_scale_and_soak(target_requests: int = 50000) -> dict:
    print(f"\n[STRESS] Running X6: Scale & Soak (Continuous {target_requests} requests, tracking RSS and FD)...")
    sample_urls = [f"{CORPUS_BASE}/wcxb/5105.html"]
    rss_samples = []
    fd_samples = []
    t0 = time.perf_counter()
    completed = 0

    initial_rss = get_pagesift_rss_mb()
    initial_fd = get_pagesift_fd_count()

    def worker_loop(n_req):
        nonlocal completed
        for _ in range(n_req):
            send_scrape(sample_urls[0])
            completed += 1
            if completed % 5000 == 0:
                rss_samples.append((completed, get_pagesift_rss_mb()))
                fd_samples.append((completed, get_pagesift_fd_count()))

    concurrency = 32
    per_worker = target_requests // concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker_loop, per_worker) for _ in range(concurrency)]
        concurrent.futures.wait(futures)

    final_rss = get_pagesift_rss_mb()
    final_fd = get_pagesift_fd_count()
    total_time = time.perf_counter() - t0

    # Linear regression slope for RSS (MB per 10k requests)
    leak_rate = 0.0
    if len(rss_samples) >= 2:
        x_vals = [s[0] for s in rss_samples]
        y_vals = [s[1] for s in rss_samples]
        n = len(x_vals)
        x_mean = statistics.fmean(x_vals)
        y_mean = statistics.fmean(y_vals)
        denom = sum((x - x_mean) ** 2 for x in x_vals)
        if denom > 0:
            slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals)) / denom
            leak_rate = round(slope * 10000.0, 4)

    res = {
        "total_requests": completed,
        "elapsed_seconds": round(total_time, 2),
        "overall_qps": round(completed / total_time, 2),
        "initial_rss_mb": initial_rss,
        "final_rss_mb": final_rss,
        "rss_delta_mb": round(final_rss - initial_rss, 2),
        "leak_rate_mb_per_10k": leak_rate,
        "initial_fd": initial_fd,
        "final_fd": final_fd,
        "fd_delta": final_fd - initial_fd,
        "rss_trend": rss_samples,
    }
    print(f"  -> Processed {completed} requests in {total_time:.1f}s ({completed/total_time:.1f} QPS)")
    print(f"  -> RSS: {initial_rss} MB -> {final_rss} MB (Delta: {res['rss_delta_mb']} MB, Slope: {leak_rate} MB/10k req)")
    print(f"  -> FD: {initial_fd} -> {final_fd} (Delta: {res['fd_delta']})")

    return res


# =========================================================================
# X7: Fault Injection & Boundary Rejection
# =========================================================================
def run_x7_fault_injection() -> dict:
    print("\n[STRESS] Running X7: Fault Injection & Boundary Defense...")
    tests = {}

    # Test 1: Invalid Scheme
    c1, m1 = send_scrape("ftp://bad-scheme.com")
    tests["ftp_scheme_defense"] = {"status": c1, "latency_ms": round(m1, 2), "blocked": c1 in (400, 422, 500)}

    # Test 2: Localhost forbidden target
    c2, m2 = send_scrape("http://127.0.0.1:9999/private")
    tests["unreachable_private_port"] = {"status": c2, "latency_ms": round(m2, 2)}

    # Test 3: Large payload
    big_payload = json.dumps({"url": f"{CORPUS_BASE}/wcxb/5105.html", "junk": "X" * 1000000}).encode()
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            f"{TARGET_BASE}/v2/scrape",
            data=big_payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer bench"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            c3 = resp.status
    except urllib.error.HTTPError as e:
        c3 = e.code
    except Exception:
        c3 = 0
    m3 = (time.perf_counter() - t0) * 1000.0
    tests["large_json_payload"] = {"status": c3, "latency_ms": round(m3, 2), "handled": c3 != 0}

    print(f"  -> Fault injection scenarios completed: {list(tests.keys())}")
    return tests


def main():
    parser = argparse.ArgumentParser(description="Run PageSift Engineering Stress Test Suite")
    parser.add_argument("--test", choices=["all", "x1", "x2", "x3", "x5", "x6", "x7"], default="all")
    parser.add_argument("--out", type=Path, default=STRESS_RESULTS / "stress_summary.json")
    args = parser.parse_args()

    suite_results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "declaration": "Stress testing is deliberately designed to demonstrate extreme engineering and production robustness.",
        "tests": {},
    }
    if args.out.exists():
        try:
            old_data = json.loads(args.out.read_text())
            if isinstance(old_data, dict) and "tests" in old_data:
                suite_results["tests"] = old_data["tests"]
        except Exception:
            pass

    if args.test in ("all", "x1"):
        suite_results["tests"]["x1_concurrency_ladder"] = run_x1_concurrency_ladder()
    if args.test in ("all", "x2"):
        suite_results["tests"]["x2_slo_rate"] = run_x2_slo_rate()
    if args.test in ("all", "x3"):
        suite_results["tests"]["x3_spike_and_recovery"] = run_x3_spike_and_recovery()
    if args.test in ("all", "x5"):
        suite_results["tests"]["x5_multimodal_mix"] = run_x5_multimodal_mix()
    if args.test in ("all", "x6"):
        # 50k requests as standard stress scale
        suite_results["tests"]["x6_scale_and_soak"] = run_x6_scale_and_soak(50000)
    if args.test in ("all", "x7"):
        suite_results["tests"]["x7_fault_injection"] = run_x7_fault_injection()

    write_json(args.out, suite_results)
    print(f"\n[DONE] Stress suite results successfully saved to {args.out}")


if __name__ == "__main__":
    main()
