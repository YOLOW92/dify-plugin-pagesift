"""Package Dify Plugin (.difypkg) dynamically from manifest.yaml and compute SHA-256 checksum."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import zipfile
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
DIST_DIR.mkdir(parents=True, exist_ok=True)


def load_manifest_meta() -> tuple[str, str]:
    manifest = yaml.safe_load((ROOT_DIR / "manifest.yaml").read_text(encoding="utf-8"))
    name = str(manifest.get("name") or "pagesift").strip()
    version = str(manifest.get("version") or "0.2.0").strip()
    return name, version


# Files and directories allowed in runtime plugin package
INCLUDED_FILES = [
    "manifest.yaml",
    "main.py",
    "requirements.txt",
    "PRIVACY.md",
    "LICENSE",
    "README.md",
    "README.zh_Hans.md",
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


def build_package() -> Path:
    name, version = load_manifest_meta()
    package_name = f"{name}-{version}.difypkg"
    out_path = DIST_DIR / package_name
    sha_path = DIST_DIR / f"{package_name}.sha256"

    print(f"[PACKAGING] Building {out_path} (version {version})...")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in INCLUDED_FILES:
            fp = ROOT_DIR / fn
            if fp.exists():
                zf.write(fp, arcname=fn)
                print(f"  + Added file: {fn}")

        for d in INCLUDED_DIRS:
            dp = ROOT_DIR / d
            if not dp.exists():
                continue
            for root, _dirs, files in os.walk(dp):
                for f in sorted(files):
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(ROOT_DIR)
                    if not should_exclude(str(rel_p)):
                        zf.write(full_p, arcname=str(rel_p))
                        print(f"  + Added: {rel_p}")

    h = hashlib.sha256()
    with open(out_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    sha256_hex = h.hexdigest()

    sha_path.write_text(f"{sha256_hex}  {package_name}\n", encoding="utf-8")

    pkg_size_kb = out_path.stat().st_size / 1024.0
    print("\n[DONE] Successfully created package:")
    print(f"  * File: {out_path} ({pkg_size_kb:.2f} KB)")
    print(f"  * SHA-256: {sha256_hex}")
    print(f"  * Checksum file: {sha_path}")
    return out_path


if __name__ == "__main__":
    build_package()
