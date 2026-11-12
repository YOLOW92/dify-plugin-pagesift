"""Shared helpers for the PageSift vs Firecrawl benchmark (standard library only)."""

from __future__ import annotations

import json
import math
import random
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
RESULTS = BENCH / "results"
CORPUS = BENCH / "corpus"

ENGINES = {
    # PageSift listens on the host; Firecrawl's api container is published on 3012.
    "pagesift": "http://127.0.0.1:3002",
    "firecrawl": "http://127.0.0.1:3012",
}

# URL prefix each engine uses to reach the local corpus server. Firecrawl runs in Docker,
# so it reaches the host through host.docker.internal.
CORPUS_BASE = {
    "pagesift": "http://127.0.0.1:8800",
    "firecrawl": "http://host.docker.internal:8800",
}


def post_json(url: str, payload: dict, timeout: float = 120.0, headers: dict | None = None):
    """POST JSON, return (http_status, parsed_body_or_None, elapsed_ms, error_text)."""
    body = json.dumps(payload).encode()
    h = {"Content-Type": "application/json", "Authorization": "Bearer bench"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ms = (time.perf_counter() - t0) * 1000.0
            return resp.status, json.loads(raw), ms, ""
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        try:
            data = json.loads(e.read())
        except Exception:
            data = None
        return e.code, data, ms, f"HTTP {e.code}"
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000.0
        return 0, None, ms, f"{type(e).__name__}: {e}"


def get_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


# ---- text scoring (same normalisation as WCXB's evaluate.py / pagesift's wcxb.py) ----

IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)|[*_`|]+", re.M)


def plain(md: str) -> str:
    """Markdown to text: images removed, links reduced to their text, formatting stripped."""
    text = IMAGE.sub("", md or "")
    prev = None
    while prev != text:
        prev, text = text, LINK.sub(lambda m: m.group(1), text)
    text = re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", text)
    text = MARKS.sub("", text)
    return "\n".join(
        line.strip() for line in text.splitlines() if line.strip() and set(line.strip()) - set("-:= ")
    )


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").lower())


def word_prf(pred: str, ref: str) -> tuple[float, float, float]:
    p, r = tokens(pred), tokens(ref)
    if not r:
        return (1.0, 1.0, 1.0) if not p else (0.0, 0.0, 0.0)
    if not p:
        return (0.0, 0.0, 0.0)
    common = sum((Counter(p) & Counter(r)).values())
    if common == 0:
        return (0.0, 0.0, 0.0)
    prec, rec = common / len(p), common / len(r)
    return prec, rec, 2 * prec * rec / (prec + rec)


def pct(values: list[float], q: float) -> float:
    """
    Standard Nearest-Rank Percentile (k = ceil(p * n) - 1, 0-indexed).
    Satisfies NIST/ISO specifications and avoids small-sample underestimation.
    """
    if not values:
        return float("nan")
    s = sorted(values)
    n = len(s)
    k = max(0, min(n - 1, int(math.ceil((q / 100.0) * n)) - 1))
    return s[k]


def bootstrap_ci(values: list[float], n_resamples: int = 2000, ci: float = 0.95) -> tuple[float, float]:
    """Calculate non-parametric bootstrap confidence interval for the mean."""
    if not values:
        return (float("nan"), float("nan"))
    if len(values) == 1:
        return (values[0], values[0])

    n = len(values)
    means = []
    # Deterministic pseudo-random seed for strict reproducibility
    rng = random.Random(42)
    for _ in range(n_resamples):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(statistics.fmean(sample))

    means.sort()
    lower_idx = int(((1.0 - ci) / 2.0) * n_resamples)
    upper_idx = int((ci + (1.0 - ci) / 2.0) * n_resamples) - 1
    lower_idx = max(0, min(n_resamples - 1, lower_idx))
    upper_idx = max(0, min(n_resamples - 1, upper_idx))
    return round(means[lower_idx], 4), round(means[upper_idx], 4)


def summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ci_low, ci_high = bootstrap_ci(values)
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3),
        "ci95": [ci_low, ci_high],
        "p50": round(pct(values, 50), 3),
        "p90": round(pct(values, 90), 3),
        "p95": round(pct(values, 95), 3),
        "p99": round(pct(values, 99), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
    }


def paired_difference_test(pairs: list[tuple[float, float]]) -> dict:
    """
    Perform paired difference analysis on matched samples [(a_i, b_i)].
    Returns mean diff, paired standard error, and estimated t-statistic.
    """
    if not pairs:
        return {"n": 0}
    diffs = [a - b for a, b in pairs]
    n = len(diffs)
    mean_diff = statistics.fmean(diffs)
    s_diff = statistics.stdev(diffs) if n > 1 else 0.0
    se = s_diff / math.sqrt(n) if n > 0 else 0.0
    t_stat = mean_diff / se if se > 0 else float("inf")
    ci_low, ci_high = bootstrap_ci(diffs)

    return {
        "n": n,
        "mean_difference": round(mean_diff, 4),
        "std_error": round(se, 4),
        "t_statistic": round(t_stat, 2),
        "ci95": [ci_low, ci_high],
    }


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
