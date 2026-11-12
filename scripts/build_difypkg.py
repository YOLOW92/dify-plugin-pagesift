"""Package Dify Plugin (.difypkg) and compute SHA-256 checksum."""

import hashlib
import os
from pathlib import Path
import zipfile

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
DIST_DIR.mkdir(parents=True, exist_ok=True)

PACKAGE_NAME = "pagesift-0.1.0.difypkg"
OUT_PATH = DIST_DIR / PACKAGE_NAME
SHA_PATH = DIST_DIR / f"{PACKAGE_NAME}.sha256"

# Files and directories allowed in runtime plugin package
INCLUDED_FILES = [
    "manifest.yaml",
    "main.py",
    "requirements.txt",
    "PRIVACY.md",
    "LICENSE",
    "README.md",
]

INCLUDED_DIRS = [
    "provider",
    "tools",
    "lib",
    "_assets",
]

EXCLUDED_PATTERNS = [
    "__pycache__",
    ".pytest_cache",
    ".pyc",
    ".git",
    ".venv",
]


def should_exclude(path_str: str) -> bool:
    return any(p in path_str for p in EXCLUDED_PATTERNS)


def build_package():
    print(f"[PACKAGING] Building {OUT_PATH}...")
    with zipfile.ZipFile(OUT_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add root files
        for fn in INCLUDED_FILES:
            fp = ROOT_DIR / fn
            if fp.exists():
                zf.write(fp, arcname=fn)
                print(f"  + Added file: {fn}")

        # Add directories
        for d in INCLUDED_DIRS:
            dp = ROOT_DIR / d
            if not dp.exists():
                continue
            for root, dirs, files in os.walk(dp):
                for f in files:
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(ROOT_DIR)
                    if not should_exclude(str(rel_p)):
                        zf.write(full_p, arcname=str(rel_p))
                        print(f"  + Added: {rel_p}")

    # Compute SHA-256
    h = hashlib.sha256()
    with open(OUT_PATH, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    sha256_hex = h.hexdigest()

    checksum_line = f"{sha256_hex}  {PACKAGE_NAME}\n"
    SHA_PATH.write_text(checksum_line, encoding="utf-8")

    pkg_size_kb = OUT_PATH.stat().st_size / 1024.0
    print(f"\n[DONE] Successfully created package:")
    print(f"  * File: {OUT_PATH} ({pkg_size_kb:.2f} KB)")
    print(f"  * SHA-256: {sha256_hex}")
    print(f"  * Checksum file: {SHA_PATH}")


if __name__ == "__main__":
    build_package()
