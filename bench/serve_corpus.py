#!/usr/bin/env python3
"""Static file server for the corpus (threaded, binds 0.0.0.0 so the Firecrawl containers reach it).

    serve_corpus.py [--port 8800]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import CORPUS  # noqa: E402

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv; charset=utf-8",
    ".epub": "application/epub+zip",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def log_message(self, *args):  # quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    args = ap.parse_args()
    handler = functools.partial(Handler, directory=str(CORPUS))
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    srv.daemon_threads = True
    print(f"serving {CORPUS} on 0.0.0.0:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
