"""Prepare manifest with ground truth for WCXB test split (511 pages) with exact metadata."""

import json
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
TEST_DIR = CORPUS_DIR / "wcxb_test"
HTML_DIR = TEST_DIR / "html"
GT_DIR = TEST_DIR / "ground-truth"
METADATA_PATH = Path("/home/yolow92/pagesift/benchmarks/data/fresh/data/wcxb/metadata.json")
MANIFEST_OUT = CORPUS_DIR / "wcxb_test511.jsonl"


def build_manifest():
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8")) if METADATA_PATH.exists() else {}
    files_meta = meta.get("files", {})

    count = 0
    with open(MANIFEST_OUT, "w", encoding="utf-8") as out_f:
        for gt_file in sorted(GT_DIR.glob("*.json")):
            fid = gt_file.stem
            html_p = HTML_DIR / f"{fid}.html"
            if not html_p.exists():
                continue

            try:
                data = json.loads(gt_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            gt_obj = data.get("ground_truth", {})
            ref = gt_obj.get("main_content", "")

            # Exact category from official metadata.json
            file_meta = files_meta.get(fid, {})
            ptype = file_meta.get("page_type") or "article"
            domain = file_meta.get("domain", "")
            url = data.get("url") or f"https://{domain}/{fid}"

            row = {
                "id": fid,
                "url": url,
                "local_url": f"http://127.0.0.1:8800/wcxb_test/html/{fid}.html",
                "page_type": str(ptype).lower(),
                "domain": domain,
                "ref": ref,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1

    print(f"Successfully generated {MANIFEST_OUT} with {count} pages.")


if __name__ == "__main__":
    build_manifest()
