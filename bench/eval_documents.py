"""Evaluate multi-format document extraction (PDF, DOCX, XLSX, PPTX, CSV) with PageSift."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import write_json

BENCH_DIR = Path(__file__).resolve().parent
DOCS_DIR = BENCH_DIR / "corpus" / "docs"
OUT_FILE = BENCH_DIR / "results" / "document_evaluation.json"
PAGESIFT_BASE = "http://127.0.0.1:3002"


def parse_doc(file_path: Path) -> dict:
    content = file_path.read_bytes()
    filename = file_path.name
    boundary = "----WebKitFormBoundaryDOCParseBench77"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{PAGESIFT_BASE}/v2/parse",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": "Bearer bench"
        },
        method="POST"
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            data = json.loads(resp.read().decode("utf-8"))
            ok = data.get("success", False)
            md = data.get("data", {}).get("markdown", "")
            return {
                "filename": filename,
                "format": file_path.suffix.lstrip(".").upper(),
                "size_bytes": len(content),
                "ok": ok,
                "latency_ms": round(elapsed_ms, 3),
                "char_count": len(md),
                "markdown_preview": md[:200]
            }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "filename": filename,
            "format": file_path.suffix.lstrip(".").upper(),
            "size_bytes": len(content),
            "ok": False,
            "latency_ms": round(elapsed_ms, 3),
            "error": str(e)
        }


def run_document_evaluation():
    doc_files = sorted(DOCS_DIR.glob("*.*"))
    doc_files = [f for f in doc_files if f.suffix in (".pdf", ".docx", ".xlsx", ".pptx", ".csv")]
    print(f"[DOCUMENT EVAL] Evaluating {len(doc_files)} format samples...")

    results = []
    for f in doc_files:
        res = parse_doc(f)
        results.append(res)
        print(f"  * [{res['format']:4s}] {res['filename']:24s} | OK: {res['ok']} | Latency: {res['latency_ms']:6.2f} ms | Chars: {res.get('char_count', 0)}")

    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_documents": len(results),
        "successful": sum(1 for r in results if r["ok"]),
        "results": results
    }
    write_json(OUT_FILE, out)
    print(f"\n[DONE] Saved document evaluation to {OUT_FILE}")


if __name__ == "__main__":
    run_document_evaluation()
